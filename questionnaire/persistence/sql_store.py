"""SQLite-backed store. Default for the project; swap to Postgres by changing
the DB URL.

Design rules followed throughout:

- Templates are append-only; ``save_template`` either creates v1 or bumps
  the version on update. The ``template_current`` table tracks the latest
  per template id.
- Questionnaires are linked to a specific (template_id, template_version).
  Editing a template never invalidates prior responses.
- Answers are flattened into rows so select-type filters push down to
  indexed SQL ``WHERE`` clauses (the inverted-index optimization).
- Multi-select answers store one row per chosen option (``option_index``
  distinguishes them).
- PII free-text answers are encrypted with Fernet at write time and
  decrypted on read; ``is_pii`` flags the row.
- Once ``submitted_at`` is set, ``upsert_answer`` / ``delete_answer``
  refuse to touch the questionnaire (immutability after submission).
- Every state change emits an audit row via ``append_audit``; the chain
  hash makes tampering detectable.
"""

from __future__ import annotations

import json
import zipfile
from contextlib import contextmanager
from io import BytesIO
from pathlib import Path
from typing import Any, Iterable, Iterator

from pydantic import TypeAdapter
from sqlalchemy import (
    and_,
    create_engine,
    delete,
    exists,
    not_,
    select,
)
from sqlalchemy.orm import Session

from ..domain.audit import (
    GENESIS_HASH,
    AuditEvent,
    AuditRecord,
    compute_hash,
    now_iso,
    verify_chain,
)
from ..domain.encryption import decrypt, encrypt
from ..domain.filtering import (
    ExcludesFilter,
    Filter,
    IncludesFilter,
    TemplateFilter,
)
from ..domain.types import (
    AnswerValue,
    BooleanAnswer,
    DateAnswer,
    FreeTextAnswer,
    MultiSelectAnswer,
    NumberAnswer,
    Questionnaire,
    SingleSelectAnswer,
    Template,
)
from .models import (
    AnswerRow,
    AuditLogRow,
    Base,
    EmbeddingRow,
    QuestionnaireRow,
    TemplateCurrentRow,
    TemplateRow,
)


# --- TypeAdapters (built once, reused) ----------------------------------

_TEMPLATE_ADAPTER = TypeAdapter(Template)
_ANSWER_ADAPTER = TypeAdapter(AnswerValue)


class StoreError(Exception):
    pass


class SubmissionLockedError(StoreError):
    """Raised when an edit is attempted on a submitted questionnaire."""


def default_db_url() -> str:
    p = Path("data") / "db.sqlite"
    p.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{p.resolve()}"


class SqlStore:
    def __init__(self, url: str | None = None, *, echo: bool = False):
        self.url = url or default_db_url()
        # SQLite-specific: enable WAL for safer concurrent reads, ON DELETE
        # CASCADE. Other DB URLs ignore the connect_args.
        connect_args = {}
        if self.url.startswith("sqlite"):
            connect_args = {"check_same_thread": False}
        self.engine = create_engine(self.url, echo=echo, connect_args=connect_args)
        Base.metadata.create_all(self.engine)
        if self.url.startswith("sqlite"):
            with self.engine.begin() as conn:
                conn.exec_driver_sql("PRAGMA journal_mode = WAL")
                conn.exec_driver_sql("PRAGMA foreign_keys = ON")

    @contextmanager
    def session(self) -> Iterator[Session]:
        with Session(self.engine) as s:
            yield s
            s.commit()

    # --- Templates -------------------------------------------------------

    def save_template(self, template: Template, *, actor: str | None = None) -> Template:
        """Create v1 if the id is new; otherwise append a new version.

        The supplied ``template.version`` is *advisory* — the store assigns
        the next monotonic integer to keep history dense.
        """
        with self.session() as s:
            existing_versions = s.execute(
                select(TemplateRow.version).where(TemplateRow.id == template.id)
            ).scalars().all()
            new_version = (max(existing_versions) + 1) if existing_versions else 1
            stamped = template.model_copy(update={"version": new_version})

            s.add(TemplateRow(
                id=stamped.id,
                version=new_version,
                title=stamped.title,
                body_json=stamped.model_dump_json(),
                created_at=stamped.created_at,
            ))
            s.merge(TemplateCurrentRow(id=stamped.id, version=new_version))
            self._append_audit_in_session(s, AuditEvent(
                ts=now_iso(),
                actor=actor,
                action="template.save",
                target_type="template",
                target_id=stamped.id,
                payload={"version": new_version, "title": stamped.title},
            ))
            return stamped

    def get_template(self, template_id: str, version: int | None = None) -> Template | None:
        with self.session() as s:
            if version is None:
                cur = s.get(TemplateCurrentRow, template_id)
                if cur is None:
                    return None
                version = cur.version
            row = s.get(TemplateRow, (template_id, version))
            if row is None:
                return None
            return _TEMPLATE_ADAPTER.validate_json(row.body_json)

    def list_templates(self) -> list[Template]:
        """Return all templates at their current version."""
        with self.session() as s:
            rows = s.execute(
                select(TemplateRow)
                .join(
                    TemplateCurrentRow,
                    and_(
                        TemplateRow.id == TemplateCurrentRow.id,
                        TemplateRow.version == TemplateCurrentRow.version,
                    ),
                )
                .order_by(TemplateRow.id)
            ).scalars().all()
            return [_TEMPLATE_ADAPTER.validate_json(r.body_json) for r in rows]

    def list_template_versions(self, template_id: str) -> list[int]:
        with self.session() as s:
            return sorted(s.execute(
                select(TemplateRow.version).where(TemplateRow.id == template_id)
            ).scalars().all())

    # --- Questionnaires --------------------------------------------------

    def save_questionnaire(self, qn: Questionnaire, *, actor: str | None = None) -> None:
        """Insert or update the questionnaire metadata and rewrite its answers.

        Refuses to modify a submitted questionnaire (immutability).
        """
        with self.session() as s:
            existing = s.get(QuestionnaireRow, qn.id)
            if existing is not None and existing.submitted_at is not None:
                raise SubmissionLockedError(
                    f"questionnaire {qn.id} is submitted and cannot be modified"
                )

            row = QuestionnaireRow(
                id=qn.id,
                template_id=qn.template_id,
                template_version=qn.template_version,
                created_at=qn.created_at,
                submitted_at=qn.submitted_at,
                respondent_id=qn.respondent_id,
            )
            s.merge(row)

            # Rewrite answers (small N per questionnaire — clear-and-reinsert
            # is simpler and correct vs incremental diff).
            s.execute(delete(AnswerRow).where(AnswerRow.questionnaire_id == qn.id))
            template = self._get_template_in_session(s, qn.template_id, qn.template_version)
            pii_ids = _pii_question_ids(template) if template else set()

            for q_id, ans in qn.answers.items():
                for ar in _answer_to_rows(qn.id, q_id, ans, is_pii=q_id in pii_ids):
                    s.add(ar)

            self._append_audit_in_session(s, AuditEvent(
                ts=now_iso(),
                actor=actor,
                action="questionnaire.save",
                target_type="questionnaire",
                target_id=qn.id,
                payload={
                    "template_id": qn.template_id,
                    "template_version": qn.template_version,
                    "answer_count": len(qn.answers),
                    "submitted": qn.submitted_at is not None,
                },
            ))

    def upsert_answer(
        self,
        questionnaire_id: str,
        question_id: str,
        answer: AnswerValue,
        *,
        actor: str | None = None,
    ) -> None:
        with self.session() as s:
            qn_row = s.get(QuestionnaireRow, questionnaire_id)
            if qn_row is None:
                raise StoreError(f"unknown questionnaire {questionnaire_id}")
            if qn_row.submitted_at is not None:
                raise SubmissionLockedError(
                    f"questionnaire {questionnaire_id} is submitted; answers are frozen"
                )

            template = self._get_template_in_session(
                s, qn_row.template_id, qn_row.template_version,
            )
            is_pii = bool(template and question_id in _pii_question_ids(template))

            s.execute(delete(AnswerRow).where(and_(
                AnswerRow.questionnaire_id == questionnaire_id,
                AnswerRow.question_id == question_id,
            )))
            for ar in _answer_to_rows(questionnaire_id, question_id, answer, is_pii=is_pii):
                s.add(ar)

            self._append_audit_in_session(s, AuditEvent(
                ts=now_iso(),
                actor=actor,
                action="answer.upsert",
                target_type="questionnaire",
                target_id=questionnaire_id,
                payload={"question_id": question_id, "type": answer.type, "is_pii": is_pii},
            ))

    def delete_answer(
        self, questionnaire_id: str, question_id: str, *, actor: str | None = None,
    ) -> None:
        with self.session() as s:
            qn_row = s.get(QuestionnaireRow, questionnaire_id)
            if qn_row is None:
                raise StoreError(f"unknown questionnaire {questionnaire_id}")
            if qn_row.submitted_at is not None:
                raise SubmissionLockedError(
                    f"questionnaire {questionnaire_id} is submitted; answers are frozen"
                )
            s.execute(delete(AnswerRow).where(and_(
                AnswerRow.questionnaire_id == questionnaire_id,
                AnswerRow.question_id == question_id,
            )))
            self._append_audit_in_session(s, AuditEvent(
                ts=now_iso(),
                actor=actor,
                action="answer.delete",
                target_type="questionnaire",
                target_id=questionnaire_id,
                payload={"question_id": question_id},
            ))

    def submit_questionnaire(self, questionnaire_id: str, *, actor: str | None = None) -> None:
        with self.session() as s:
            qn_row = s.get(QuestionnaireRow, questionnaire_id)
            if qn_row is None:
                raise StoreError(f"unknown questionnaire {questionnaire_id}")
            if qn_row.submitted_at is not None:
                raise SubmissionLockedError(
                    f"questionnaire {questionnaire_id} already submitted"
                )
            qn_row.submitted_at = now_iso()
            self._append_audit_in_session(s, AuditEvent(
                ts=now_iso(),
                actor=actor,
                action="questionnaire.submit",
                target_type="questionnaire",
                target_id=questionnaire_id,
                payload={},
            ))

    def get_questionnaire(self, questionnaire_id: str) -> Questionnaire | None:
        with self.session() as s:
            row = s.get(QuestionnaireRow, questionnaire_id)
            if row is None:
                return None
            answers = self._load_answers(s, questionnaire_id)
            return Questionnaire(
                id=row.id,
                template_id=row.template_id,
                template_version=row.template_version,
                created_at=row.created_at,
                submitted_at=row.submitted_at,
                respondent_id=row.respondent_id,
                answers=answers,
            )

    def query_questionnaires(
        self,
        filters: list[Filter],
        *,
        include_drafts: bool = False,
    ) -> list[Questionnaire]:
        """SQL-pushdown filtering. Each include/exclude becomes an EXISTS clause.

        Complexity: dominated by the answers index on (question_id,
        value_text); for typical filters this is O(matching rows) rather
        than the O(N) full scan the original JSON store had to do.
        """
        with self.session() as s:
            stmt = select(QuestionnaireRow)
            if not include_drafts:
                stmt = stmt.where(QuestionnaireRow.submitted_at.isnot(None))
            for f in filters:
                if isinstance(f, TemplateFilter):
                    stmt = stmt.where(QuestionnaireRow.template_id == f.template_id)
                elif isinstance(f, IncludesFilter):
                    sub = (
                        select(AnswerRow.questionnaire_id)
                        .where(and_(
                            AnswerRow.questionnaire_id == QuestionnaireRow.id,
                            AnswerRow.question_id == f.question_id,
                            AnswerRow.value_text == f.value,
                        ))
                    )
                    stmt = stmt.where(exists(sub))
                elif isinstance(f, ExcludesFilter):
                    sub = (
                        select(AnswerRow.questionnaire_id)
                        .where(and_(
                            AnswerRow.questionnaire_id == QuestionnaireRow.id,
                            AnswerRow.question_id == f.question_id,
                            AnswerRow.value_text == f.value,
                        ))
                    )
                    stmt = stmt.where(not_(exists(sub)))
            stmt = stmt.order_by(QuestionnaireRow.created_at)

            qn_rows = s.execute(stmt).scalars().all()
            out: list[Questionnaire] = []
            for row in qn_rows:
                answers = self._load_answers(s, row.id)
                out.append(Questionnaire(
                    id=row.id,
                    template_id=row.template_id,
                    template_version=row.template_version,
                    created_at=row.created_at,
                    submitted_at=row.submitted_at,
                    respondent_id=row.respondent_id,
                    answers=answers,
                ))
            return out

    def stream_query_for_export(
        self,
        filters: list[Filter],
        *,
        include_drafts: bool = False,
        chunk_size: int = 500,
    ) -> Iterator[Questionnaire]:
        """Memory-bounded variant for CSV export; yields one Questionnaire at a time."""
        with self.session() as s:
            stmt = select(QuestionnaireRow.id)
            if not include_drafts:
                stmt = stmt.where(QuestionnaireRow.submitted_at.isnot(None))
            for f in filters:
                if isinstance(f, TemplateFilter):
                    stmt = stmt.where(QuestionnaireRow.template_id == f.template_id)
                elif isinstance(f, IncludesFilter):
                    sub = select(AnswerRow.questionnaire_id).where(and_(
                        AnswerRow.questionnaire_id == QuestionnaireRow.id,
                        AnswerRow.question_id == f.question_id,
                        AnswerRow.value_text == f.value,
                    ))
                    stmt = stmt.where(exists(sub))
                elif isinstance(f, ExcludesFilter):
                    sub = select(AnswerRow.questionnaire_id).where(and_(
                        AnswerRow.questionnaire_id == QuestionnaireRow.id,
                        AnswerRow.question_id == f.question_id,
                        AnswerRow.value_text == f.value,
                    ))
                    stmt = stmt.where(not_(exists(sub)))
            stmt = stmt.order_by(QuestionnaireRow.created_at).execution_options(
                yield_per=chunk_size,
            )
            for (qn_id,) in s.execute(stmt):
                qn = self.get_questionnaire(qn_id)
                if qn is not None:
                    yield qn

    # --- Audit log -------------------------------------------------------

    def _append_audit_in_session(self, s: Session, event: AuditEvent) -> AuditRecord:
        last = s.execute(
            select(AuditLogRow).order_by(AuditLogRow.seq.desc()).limit(1)
        ).scalar_one_or_none()
        prev_hash = last.hash if last else GENESIS_HASH
        h = compute_hash(prev_hash, event)
        row = AuditLogRow(
            ts=event.ts,
            actor=event.actor,
            action=event.action,
            target_type=event.target_type,
            target_id=event.target_id,
            payload_json=json.dumps(event.payload, sort_keys=True),
            prev_hash=prev_hash,
            hash=h,
        )
        s.add(row)
        s.flush()
        return AuditRecord(seq=row.seq, event=event, prev_hash=prev_hash, hash=h)

    def list_audit(self, since_seq: int = 0) -> list[AuditRecord]:
        with self.session() as s:
            rows = s.execute(
                select(AuditLogRow)
                .where(AuditLogRow.seq > since_seq)
                .order_by(AuditLogRow.seq)
            ).scalars().all()
            out: list[AuditRecord] = []
            for r in rows:
                out.append(AuditRecord(
                    seq=r.seq,
                    event=AuditEvent(
                        ts=r.ts,
                        actor=r.actor,
                        action=r.action,
                        target_type=r.target_type,
                        target_id=r.target_id,
                        payload=json.loads(r.payload_json) if r.payload_json else {},
                    ),
                    prev_hash=r.prev_hash,
                    hash=r.hash,
                ))
            return out

    def verify_audit(self) -> tuple[bool, str | None]:
        return verify_chain(self.list_audit())

    # --- GDPR ------------------------------------------------------------

    def respondent_export(self, respondent_id: str) -> bytes:
        """Build a zip archive of everything tied to ``respondent_id``."""
        buf = BytesIO()
        with self.session() as s:
            qn_rows = s.execute(
                select(QuestionnaireRow).where(
                    QuestionnaireRow.respondent_id == respondent_id
                )
            ).scalars().all()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
                index = []
                for row in qn_rows:
                    qn = self.get_questionnaire(row.id)
                    if qn is None:
                        continue
                    fname = f"questionnaires/{qn.id}.json"
                    zf.writestr(fname, qn.model_dump_json(indent=2))
                    index.append({
                        "id": qn.id,
                        "template_id": qn.template_id,
                        "template_version": qn.template_version,
                        "submitted_at": qn.submitted_at,
                    })
                zf.writestr("manifest.json", json.dumps({
                    "respondent_id": respondent_id,
                    "exported_at": now_iso(),
                    "questionnaires": index,
                }, indent=2))
        return buf.getvalue()

    def respondent_delete(self, respondent_id: str, *, actor: str | None = None) -> int:
        """Hard-delete every questionnaire (and its answers/embeddings) tied
        to ``respondent_id``. Audit-log records the count + a tombstone."""
        with self.session() as s:
            qn_ids = s.execute(
                select(QuestionnaireRow.id).where(
                    QuestionnaireRow.respondent_id == respondent_id
                )
            ).scalars().all()
            n = len(qn_ids)
            for qid in qn_ids:
                s.execute(delete(AnswerRow).where(AnswerRow.questionnaire_id == qid))
                s.execute(delete(EmbeddingRow).where(EmbeddingRow.questionnaire_id == qid))
            s.execute(delete(QuestionnaireRow).where(
                QuestionnaireRow.respondent_id == respondent_id
            ))
            self._append_audit_in_session(s, AuditEvent(
                ts=now_iso(),
                actor=actor,
                action="gdpr.delete",
                target_type="respondent",
                target_id=respondent_id,
                payload={"deleted_questionnaire_count": n, "ids": qn_ids},
            ))
            return n

    # --- Embeddings ------------------------------------------------------

    def save_embedding(
        self, questionnaire_id: str, question_id: str, vector: bytes, dim: int,
    ) -> None:
        with self.session() as s:
            s.merge(EmbeddingRow(
                questionnaire_id=questionnaire_id,
                question_id=question_id,
                vector=vector,
                dim=dim,
            ))

    def list_embeddings_for_question(
        self, question_id: str,
    ) -> list[tuple[str, bytes, int]]:
        """Return [(questionnaire_id, vector_bytes, dim)] for clustering."""
        with self.session() as s:
            rows = s.execute(
                select(EmbeddingRow).where(EmbeddingRow.question_id == question_id)
            ).scalars().all()
            return [(r.questionnaire_id, r.vector, r.dim) for r in rows]

    def list_freetext_answers(
        self, question_id: str,
    ) -> list[tuple[str, str]]:
        """Return [(questionnaire_id, plaintext)] of free-text answers for clustering.

        Decrypts PII rows transparently. Skips rows whose answer type is
        not free_text (defensive — clustering callers also gate by type).
        """
        out: list[tuple[str, str]] = []
        with self.session() as s:
            rows = s.execute(
                select(AnswerRow).where(and_(
                    AnswerRow.question_id == question_id,
                    AnswerRow.type == "free_text",
                ))
            ).scalars().all()
            for r in rows:
                if r.is_pii and r.value_blob:
                    out.append((r.questionnaire_id, decrypt(r.value_blob)))
                elif r.value_text is not None:
                    out.append((r.questionnaire_id, r.value_text))
        return out

    # --- Internal --------------------------------------------------------

    def _get_template_in_session(
        self, s: Session, template_id: str, version: int,
    ) -> Template | None:
        row = s.get(TemplateRow, (template_id, version))
        if row is None:
            return None
        return _TEMPLATE_ADAPTER.validate_json(row.body_json)

    def _load_answers(self, s: Session, questionnaire_id: str) -> dict[str, AnswerValue]:
        rows = s.execute(
            select(AnswerRow)
            .where(AnswerRow.questionnaire_id == questionnaire_id)
            .order_by(AnswerRow.question_id, AnswerRow.option_index)
        ).scalars().all()
        # Group multi-select rows by question_id.
        grouped: dict[str, list[AnswerRow]] = {}
        for r in rows:
            grouped.setdefault(r.question_id, []).append(r)
        return {qid: _rows_to_answer(rs) for qid, rs in grouped.items()}


# --- Pure helpers --------------------------------------------------------

def _pii_question_ids(template: Template) -> set[str]:
    out: set[str] = set()

    def walk(qs):
        for q in qs:
            if getattr(q, "pii", False):
                out.add(q.id)
            for fu in getattr(q, "follow_ups", []) or []:
                walk(fu.questions)

    walk(template.questions)
    return out


def _answer_to_rows(
    questionnaire_id: str,
    question_id: str,
    ans: AnswerValue,
    *,
    is_pii: bool,
) -> list[AnswerRow]:
    """Encode an ``AnswerValue`` as one or more ``AnswerRow`` rows."""
    base = dict(
        questionnaire_id=questionnaire_id,
        question_id=question_id,
        type=ans.type,
        is_pii=is_pii,
    )

    if isinstance(ans, BooleanAnswer):
        return [AnswerRow(**base, option_index=0, value_bool=ans.value)]

    if isinstance(ans, SingleSelectAnswer):
        return [AnswerRow(**base, option_index=0, value_text=ans.value)]

    if isinstance(ans, MultiSelectAnswer):
        return [
            AnswerRow(**base, option_index=i, value_text=v)
            for i, v in enumerate(ans.value)
        ]

    if isinstance(ans, DateAnswer):
        return [AnswerRow(**base, option_index=0, value_text=ans.value)]

    if isinstance(ans, FreeTextAnswer):
        if is_pii:
            return [AnswerRow(**base, option_index=0, value_blob=encrypt(ans.value))]
        return [AnswerRow(**base, option_index=0, value_text=ans.value)]

    if isinstance(ans, NumberAnswer):
        return [AnswerRow(**base, option_index=0, value_num=float(ans.value))]

    raise StoreError(f"unhandled answer type: {ans.type}")


def _rows_to_answer(rows: list[AnswerRow]) -> AnswerValue:
    """Decode one or more ``AnswerRow`` rows back into an ``AnswerValue``."""
    if not rows:
        raise StoreError("empty row group")
    t = rows[0].type
    if t == "boolean":
        return BooleanAnswer(value=bool(rows[0].value_bool))
    if t == "single_select":
        return SingleSelectAnswer(value=rows[0].value_text or "")
    if t == "multi_select":
        return MultiSelectAnswer(value=[r.value_text or "" for r in rows])
    if t == "date":
        return DateAnswer(value=rows[0].value_text or "")
    if t == "free_text":
        r = rows[0]
        if r.is_pii and r.value_blob:
            return FreeTextAnswer(value=decrypt(r.value_blob))
        return FreeTextAnswer(value=r.value_text or "")
    if t == "number":
        return NumberAnswer(value=float(rows[0].value_num or 0.0))
    raise StoreError(f"unknown answer type in DB: {t}")
