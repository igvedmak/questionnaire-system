"""FastAPI app — HTTP face of the same engine the CLI uses.

The Pydantic discriminated unions for ``Question``/``AnswerValue`` are
reused as request/response schemas, so OpenAPI documents the type
catalogue automatically.

Conventions
-----------
- ``X-Actor`` header is written into the audit log as the actor for
  state-changing requests.
- ``X-API-Key`` header is required when ``QST_API_KEYS`` is set.
- Errors return ``{"detail": "..."}`` with appropriate status codes.
- All side-effecting endpoints append an audit row.
"""

from __future__ import annotations

import csv
import io
import uuid
from datetime import datetime, timezone
from typing import Any, Generic, TypeVar

import uuid as uuid_lib
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Response, Security
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import RedirectResponse, StreamingResponse
from fastapi.security.api_key import APIKeyHeader
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import text

from ..config import settings
from ..domain.filtering import FilterError, parse_filters
from ..domain.flow import resolve_active_questions
from ..domain.types import (
    AnswerValue,
    Question,
    Questionnaire,
    Template,
)
from ..domain.validation import validate_for_submission, validate_template
from ..persistence import StoreError, SubmissionLockedError, WebhookConfig, default_store


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# --- Generic page envelope -----------------------------------------------

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int


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


class BulkAnswerBody(BaseModel):
    answers: dict[str, AnswerValue]


class WebhookCreate(BaseModel):
    url: str
    events: list[str] = Field(default_factory=list)
    secret: str | None = None


# --- OpenAPI tag metadata -------------------------------------------------

_OPENAPI_TAGS = [
    {"name": "templates", "description": "Template management and versioning"},
    {"name": "questionnaires", "description": "Questionnaire instances and answers"},
    {"name": "audit", "description": "Tamper-evident audit log"},
    {"name": "gdpr", "description": "GDPR export and deletion"},
    {"name": "analytics", "description": "Semantic clustering of free-text answers"},
    {"name": "webhooks", "description": "Event-driven HTTP callbacks"},
    {"name": "ops", "description": "Health, metrics, and operational endpoints"},
]


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
        openapi_tags=_OPENAPI_TAGS,
    )
    s = store or default_store()
    # Stash so route handlers can reach it via dependency-injection-lite.
    app.state.store = s

    # --- Middleware -------------------------------------------------------
    app.add_middleware(GZipMiddleware, minimum_size=500)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def request_id_middleware(request, call_next):
        rid = request.headers.get("X-Request-ID", str(uuid_lib.uuid4()))
        response = await call_next(request)
        response.headers["X-Request-ID"] = rid
        return response

    # --- API key auth ----------------------------------------------------
    api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

    def require_api_key(key: str | None = Security(api_key_header)):
        if not settings.api_keys:
            return  # auth disabled
        if key not in settings.api_keys:
            raise HTTPException(401, detail="invalid or missing API key")

    # --- Ops -------------------------------------------------------------

    @app.get("/", include_in_schema=False)
    def root():
        return RedirectResponse(url="/docs")

    @app.get("/health", tags=["ops"])
    def health():
        db_ok = False
        try:
            with Session(s.engine) as sess:
                sess.execute(text("SELECT 1"))
            db_ok = True
        except Exception:
            db_ok = False
        return {"status": "ok" if db_ok else "degraded", "db": db_ok, "version": "0.2.0"}

    # --- Templates -------------------------------------------------------

    @app.post(
        "/templates",
        response_model=Template,
        status_code=201,
        tags=["templates"],
        dependencies=[Depends(require_api_key)],
    )
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

    @app.get("/templates", response_model=list[Template], tags=["templates"])
    def list_templates():
        return s.list_templates()

    @app.get("/templates/{template_id}", response_model=Template, tags=["templates"])
    def get_template(template_id: str, version: int | None = None):
        tpl = s.get_template(template_id, version=version)
        if tpl is None:
            raise HTTPException(404, detail="template not found")
        return tpl

    @app.get("/templates/{template_id}/versions", response_model=list[int], tags=["templates"])
    def list_template_versions(template_id: str):
        return s.list_template_versions(template_id)

    @app.get("/templates/{template_id}/stats", tags=["templates"])
    def template_stats(template_id: str):
        stats = s.get_template_stats(template_id)
        if stats is None:
            raise HTTPException(404, detail="template not found")
        return stats

    @app.post(
        "/templates/{template_id}/duplicate",
        response_model=Template,
        status_code=201,
        tags=["templates"],
        dependencies=[Depends(require_api_key)],
    )
    def duplicate_template(
        template_id: str,
        new_id: str | None = Query(None),
        x_actor: str | None = Header(default=None),
    ):
        try:
            return s.duplicate_template(template_id, new_id=new_id, actor=x_actor)
        except StoreError as e:
            raise HTTPException(404, detail=str(e))

    # --- Questionnaires --------------------------------------------------

    @app.post(
        "/questionnaires",
        response_model=Questionnaire,
        status_code=201,
        tags=["questionnaires"],
        dependencies=[Depends(require_api_key)],
    )
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

    @app.get("/questionnaires/{qid}", response_model=Questionnaire, tags=["questionnaires"])
    def get_questionnaire(qid: str):
        qn = s.get_questionnaire(qid)
        if qn is None:
            raise HTTPException(404, detail="questionnaire not found")
        return qn

    @app.get("/questionnaires", response_model=list[Questionnaire], tags=["questionnaires"])
    def list_questionnaires(
        template: str | None = Query(None),
        includes: list[str] = Query(default_factory=list),
        excludes: list[str] = Query(default_factory=list),
        include_drafts: bool = Query(False),
        page: int = Query(1, ge=1),
        page_size: int = Query(settings.default_page_size, ge=1, le=settings.max_page_size),
        response: Response = None,
    ):
        templates = {t.id: t for t in s.list_templates()}
        try:
            filters = parse_filters(template, includes, excludes, templates)
        except FilterError as e:
            raise HTTPException(400, detail=str(e))
        items, total = s.query_questionnaires_page(
            filters, include_drafts=include_drafts, page=page, page_size=page_size,
        )
        if response is not None:
            response.headers["X-Total"] = str(total)
            response.headers["X-Page"] = str(page)
            response.headers["X-Page-Size"] = str(page_size)
        return items

    @app.put(
        "/questionnaires/{qid}/answers/{question_id}",
        response_model=Questionnaire,
        tags=["questionnaires"],
        dependencies=[Depends(require_api_key)],
    )
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

    @app.put(
        "/questionnaires/{qid}/answers",
        response_model=Questionnaire,
        tags=["questionnaires"],
        dependencies=[Depends(require_api_key)],
    )
    def bulk_upsert_answers(
        qid: str, body: BulkAnswerBody, x_actor: str | None = Header(default=None),
    ):
        for question_id, answer in body.answers.items():
            try:
                s.upsert_answer(qid, question_id, answer, actor=x_actor)
            except SubmissionLockedError as e:
                raise HTTPException(409, detail=str(e))
        return s.get_questionnaire(qid)

    @app.delete(
        "/questionnaires/{qid}/answers/{question_id}",
        response_model=Questionnaire,
        tags=["questionnaires"],
        dependencies=[Depends(require_api_key)],
    )
    def delete_answer(
        qid: str, question_id: str,
        x_actor: str | None = Header(default=None),
    ):
        try:
            s.delete_answer(qid, question_id, actor=x_actor)
        except SubmissionLockedError as e:
            raise HTTPException(409, detail=str(e))
        return s.get_questionnaire(qid)

    @app.post(
        "/questionnaires/{qid}/submit",
        response_model=Questionnaire,
        tags=["questionnaires"],
        dependencies=[Depends(require_api_key)],
    )
    def submit_questionnaire(qid: str, x_actor: str | None = Header(default=None)):
        try:
            s.submit_questionnaire(qid, actor=x_actor)
        except SubmissionLockedError as e:
            raise HTTPException(409, detail=str(e))
        return s.get_questionnaire(qid)

    @app.post(
        "/questionnaires/{qid}/archive",
        tags=["questionnaires"],
        dependencies=[Depends(require_api_key)],
    )
    def archive_questionnaire(qid: str, x_actor: str | None = Header(default=None)):
        try:
            s.archive_questionnaire(qid, actor=x_actor)
        except StoreError as e:
            raise HTTPException(404, detail=str(e))
        return {"archived": True}

    @app.post("/questionnaires/{qid}/validate", tags=["questionnaires"])
    def validate_questionnaire(qid: str):
        qn = s.get_questionnaire(qid)
        if qn is None:
            raise HTTPException(404, detail="questionnaire not found")
        tpl = s.get_template(qn.template_id, version=qn.template_version)
        if tpl is None:
            raise HTTPException(404, detail="template not found")
        result = validate_for_submission(tpl, qn.answers)
        return {"valid": result.ok, "errors": [str(e) for e in result.errors]}

    # --- Export ----------------------------------------------------------

    @app.get("/questionnaires.csv", tags=["questionnaires"])
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

    # --- Audit -----------------------------------------------------------

    @app.get("/audit", tags=["audit"])
    def list_audit(
        since: int = Query(0),
        page: int = Query(1, ge=1),
        page_size: int = Query(50, ge=1, le=200),
        response: Response = None,
    ):
        rows = s.list_audit(since_seq=since)
        # Apply pagination in-memory (audit is typically small and append-only).
        total = len(rows)
        start = (page - 1) * page_size
        end = start + page_size
        paged = rows[start:end]
        if response is not None:
            response.headers["X-Total"] = str(total)
            response.headers["X-Page"] = str(page)
            response.headers["X-Page-Size"] = str(page_size)
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
            for r in paged
        ]

    @app.post("/audit/verify", tags=["audit"])
    def verify_audit():
        ok, err = s.verify_audit()
        if ok:
            return {"ok": True}
        raise HTTPException(409, detail=err)

    # --- GDPR ------------------------------------------------------------

    @app.get("/respondents/{respondent_id}/export", tags=["gdpr"])
    def respondent_export(respondent_id: str):
        payload = s.respondent_export(respondent_id)
        return Response(
            content=payload,
            media_type="application/zip",
            headers={
                "Content-Disposition": f'attachment; filename="{respondent_id}.zip"',
            },
        )

    @app.delete(
        "/respondents/{respondent_id}",
        status_code=200,
        tags=["gdpr"],
        dependencies=[Depends(require_api_key)],
    )
    def respondent_delete(
        respondent_id: str, x_actor: str | None = Header(default=None),
    ):
        n = s.respondent_delete(respondent_id, actor=x_actor)
        return {"deleted_questionnaires": n}

    # --- Analytics -------------------------------------------------------

    @app.get("/analytics/{question_id}/clusters", tags=["analytics"])
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

    # --- Webhooks --------------------------------------------------------

    @app.get("/webhooks", tags=["webhooks"])
    def list_webhooks():
        return s.list_webhooks()

    @app.post(
        "/webhooks",
        status_code=201,
        tags=["webhooks"],
        dependencies=[Depends(require_api_key)],
    )
    def create_webhook(body: WebhookCreate, x_actor: str | None = Header(default=None)):
        wh = WebhookConfig(
            id=str(uuid.uuid4()),
            url=body.url,
            events=body.events,
            secret=body.secret,
            created_at=_now_iso(),
            active=True,
        )
        return s.save_webhook(wh)

    @app.delete(
        "/webhooks/{webhook_id}",
        tags=["webhooks"],
        dependencies=[Depends(require_api_key)],
    )
    def delete_webhook(webhook_id: str):
        try:
            s.delete_webhook(webhook_id)
        except StoreError as e:
            raise HTTPException(404, detail=str(e))
        return {"deleted": True}

    return app


app = create_app()
