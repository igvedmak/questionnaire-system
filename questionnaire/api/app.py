"""FastAPI app — HTTP face of the same engine the CLI uses.

The Pydantic discriminated unions for ``Question``/``AnswerValue`` are
reused as request/response schemas, so OpenAPI documents the type
catalogue automatically.

Conventions
-----------
- Auth is intentionally absent in this round; the ``X-Actor`` header is
  written into the audit log as the actor for state-changing requests.
  Real auth (OAuth, API keys) is the documented next step.
- Errors return ``{"detail": "..."}`` with appropriate status codes.
- All side-effecting endpoints append an audit row.
"""

from __future__ import annotations

import csv
import io
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Query, Response
from fastapi.responses import RedirectResponse, StreamingResponse
from pydantic import BaseModel, Field

from ..domain.filtering import FilterError, parse_filters
from ..domain.flow import resolve_active_questions
from ..domain.types import (
    AnswerValue,
    Question,
    Questionnaire,
    Template,
)
from ..domain.validation import validate_template
from ..persistence import SubmissionLockedError, default_store


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# --- Request / response models ------------------------------------------

class TemplateCreate(BaseModel):
    title: str
    questions: list[Question]
    id: str | None = None  # server generates if omitted


class QuestionnaireCreate(BaseModel):
    template_id: str
    respondent_id: str | None = None


class AnswerBody(BaseModel):
    answer: AnswerValue = Field(..., description="A discriminated AnswerValue")


# --- App factory --------------------------------------------------------

def create_app(store=None) -> FastAPI:
    """Build the FastAPI app. ``store`` is injected for tests; production
    paths use the default."""
    app = FastAPI(
        title="Questionnaire engine",
        version="0.2.0",
        description=(
            "Templates, instances, expression-based follow-ups, audit log, "
            "and semantic free-text analytics."
        ),
    )
    s = store or default_store()
    # Stash so route handlers can reach it via dependency-injection-lite.
    app.state.store = s

    @app.get("/", include_in_schema=False)
    def root():
        return RedirectResponse(url="/docs")

    # --- Templates ------------------------------------------------------

    @app.post("/templates", response_model=Template, status_code=201)
    def create_template(body: TemplateCreate, x_actor: str | None = Header(default=None)):
        tpl = Template(
            id=body.id or str(uuid.uuid4()),
            title=body.title,
            questions=body.questions,
            created_at=_now_iso(),
        )
        result = validate_template(tpl)
        if not result.ok:
            raise HTTPException(422, detail=[str(e) for e in result.errors])
        return s.save_template(tpl, actor=x_actor)

    @app.get("/templates", response_model=list[Template])
    def list_templates():
        return s.list_templates()

    @app.get("/templates/{template_id}", response_model=Template)
    def get_template(template_id: str, version: int | None = None):
        tpl = s.get_template(template_id, version=version)
        if tpl is None:
            raise HTTPException(404, detail="template not found")
        return tpl

    @app.get("/templates/{template_id}/versions", response_model=list[int])
    def list_template_versions(template_id: str):
        return s.list_template_versions(template_id)

    # --- Questionnaires -------------------------------------------------

    @app.post("/questionnaires", response_model=Questionnaire, status_code=201)
    def create_questionnaire(body: QuestionnaireCreate, x_actor: str | None = Header(default=None)):
        tpl = s.get_template(body.template_id)
        if tpl is None:
            raise HTTPException(404, detail="template not found")
        qn = Questionnaire(
            id=str(uuid.uuid4()),
            template_id=tpl.id,
            template_version=tpl.version,
            created_at=_now_iso(),
            respondent_id=body.respondent_id,
            answers={},
        )
        s.save_questionnaire(qn, actor=x_actor)
        return qn

    @app.get("/questionnaires/{qid}", response_model=Questionnaire)
    def get_questionnaire(qid: str):
        qn = s.get_questionnaire(qid)
        if qn is None:
            raise HTTPException(404, detail="questionnaire not found")
        return qn

    @app.get("/questionnaires", response_model=list[Questionnaire])
    def list_questionnaires(
        template: str | None = Query(None),
        includes: list[str] = Query(default_factory=list),
        excludes: list[str] = Query(default_factory=list),
        include_drafts: bool = Query(False),
    ):
        templates = {t.id: t for t in s.list_templates()}
        try:
            filters = parse_filters(template, includes, excludes, templates)
        except FilterError as e:
            raise HTTPException(400, detail=str(e))
        return s.query_questionnaires(filters, include_drafts=include_drafts)

    @app.put("/questionnaires/{qid}/answers/{question_id}", response_model=Questionnaire)
    def upsert_answer(
        qid: str, question_id: str, body: AnswerBody,
        x_actor: str | None = Header(default=None),
    ):
        try:
            s.upsert_answer(qid, question_id, body.answer, actor=x_actor)
        except SubmissionLockedError as e:
            raise HTTPException(409, detail=str(e))
        except Exception as e:
            raise HTTPException(400, detail=str(e))
        return s.get_questionnaire(qid)

    @app.delete("/questionnaires/{qid}/answers/{question_id}", response_model=Questionnaire)
    def delete_answer(
        qid: str, question_id: str,
        x_actor: str | None = Header(default=None),
    ):
        try:
            s.delete_answer(qid, question_id, actor=x_actor)
        except SubmissionLockedError as e:
            raise HTTPException(409, detail=str(e))
        return s.get_questionnaire(qid)

    @app.post("/questionnaires/{qid}/submit", response_model=Questionnaire)
    def submit_questionnaire(qid: str, x_actor: str | None = Header(default=None)):
        try:
            s.submit_questionnaire(qid, actor=x_actor)
        except SubmissionLockedError as e:
            raise HTTPException(409, detail=str(e))
        return s.get_questionnaire(qid)

    # --- Export ---------------------------------------------------------

    @app.get("/questionnaires.csv")
    def export_csv(
        template: str | None = Query(None),
        includes: list[str] = Query(default_factory=list),
        excludes: list[str] = Query(default_factory=list),
        include_drafts: bool = Query(False),
    ):
        templates = {t.id: t for t in s.list_templates()}
        try:
            filters = parse_filters(template, includes, excludes, templates)
        except FilterError as e:
            raise HTTPException(400, detail=str(e))

        def gen():
            buf = io.StringIO()
            seen_columns: list[str] = []
            seen_set: set[str] = set()
            rows_buf: list[dict[str, Any]] = []
            for qn in s.stream_query_for_export(filters, include_drafts=include_drafts):
                tpl = templates.get(qn.template_id) or s.get_template(
                    qn.template_id, qn.template_version,
                )
                active = resolve_active_questions(tpl.questions, qn.answers) if tpl else []
                for q in active:
                    if q.id not in seen_set:
                        seen_set.add(q.id)
                        seen_columns.append(q.id)
                row: dict[str, Any] = {
                    "questionnaire_id": qn.id,
                    "template_id": qn.template_id,
                    "template_version": qn.template_version,
                    "submitted_at": qn.submitted_at or "",
                    "respondent_id": qn.respondent_id or "",
                }
                for q_id, ans in qn.answers.items():
                    v = ans.value
                    if isinstance(v, list):
                        v = "|".join(v)
                    row[q_id] = v
                rows_buf.append(row)

            fieldnames = [
                "questionnaire_id", "template_id", "template_version",
                "submitted_at", "respondent_id", *seen_columns,
            ]
            writer = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            yield buf.getvalue()
            buf.seek(0); buf.truncate()
            for r in rows_buf:
                writer.writerow(r)
                yield buf.getvalue()
                buf.seek(0); buf.truncate()

        return StreamingResponse(gen(), media_type="text/csv")

    # --- Audit ----------------------------------------------------------

    @app.get("/audit")
    def list_audit(since: int = Query(0)):
        rows = s.list_audit(since_seq=since)
        return [
            {
                "seq": r.seq,
                "ts": r.event.ts,
                "actor": r.event.actor,
                "action": r.event.action,
                "target_type": r.event.target_type,
                "target_id": r.event.target_id,
                "payload": r.event.payload,
                "prev_hash": r.prev_hash,
                "hash": r.hash,
            }
            for r in rows
        ]

    @app.post("/audit/verify")
    def verify_audit():
        ok, err = s.verify_audit()
        if ok:
            return {"ok": True}
        raise HTTPException(409, detail=err)

    # --- GDPR -----------------------------------------------------------

    @app.get("/respondents/{respondent_id}/export")
    def respondent_export(respondent_id: str):
        payload = s.respondent_export(respondent_id)
        return Response(
            content=payload,
            media_type="application/zip",
            headers={
                "Content-Disposition": f'attachment; filename="{respondent_id}.zip"',
            },
        )

    @app.delete("/respondents/{respondent_id}", status_code=200)
    def respondent_delete(
        respondent_id: str, x_actor: str | None = Header(default=None),
    ):
        n = s.respondent_delete(respondent_id, actor=x_actor)
        return {"deleted_questionnaires": n}

    # --- Analytics ------------------------------------------------------

    @app.get("/analytics/{question_id}/clusters")
    def cluster_freetext_endpoint(
        question_id: str, min_cluster_size: int = Query(3),
    ):
        items = s.list_freetext_answers(question_id)
        if not items:
            raise HTTPException(404, detail="no free-text answers for that question id")
        try:
            from ..analytics.clustering import cluster_freetext
        except Exception as e:
            raise HTTPException(503, detail=f"analytics extra not installed: {e}")
        clusters = cluster_freetext(items, min_cluster_size=min_cluster_size)
        return [
            {
                "cluster_id": c.cluster_id,
                "size": c.size,
                "exemplar_text": c.exemplar_text,
                "exemplar_questionnaire_id": c.exemplar_questionnaire_id,
                "members": c.member_questionnaire_ids,
            }
            for c in clusters
        ]

    return app


app = create_app()
