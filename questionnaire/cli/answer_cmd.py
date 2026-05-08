"""`qst answer ...` — start or resume answering a questionnaire."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import typer

from ..domain.flow import next_unanswered_question, resolve_active_questions
from ..domain.types import FreeTextQuestion, Questionnaire
from ..domain.validation import validate_answers, validate_for_submission
from ..persistence import SubmissionLockedError, default_store
from .prompt import prompt_for_answer

app = typer.Typer(help="Answer questionnaires.", no_args_is_help=True)


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@app.command("start")
def start(
    template_id: str,
    respondent: str = typer.Option(None, "--respondent",
                                   help="Optional respondent id (used for GDPR export/delete)"),
    actor: str = typer.Option(None, "--actor"),
):
    """Create a new questionnaire from a template's current version."""
    store = default_store()
    template = store.get_template(template_id)
    if template is None:
        typer.echo(f"unknown template id: {template_id}", err=True)
        raise typer.Exit(code=1)

    qn = Questionnaire(
        id=str(uuid.uuid4()),
        template_id=template_id,
        template_version=template.version,
        created_at=_now_iso(),
        respondent_id=respondent,
        answers={},
    )
    store.save_questionnaire(qn, actor=actor)
    typer.echo(f"started questionnaire {qn.id} on template {template.title!r} v{template.version}")
    typer.echo()
    _drive_loop(qn.id, actor=actor)


@app.command("resume")
def resume(questionnaire_id: str, actor: str = typer.Option(None, "--actor")):
    store = default_store()
    qn = store.get_questionnaire(questionnaire_id)
    if qn is None:
        typer.echo(f"unknown questionnaire id: {questionnaire_id}", err=True)
        raise typer.Exit(code=1)
    if qn.is_submitted:
        typer.echo(f"questionnaire {qn.id} is already submitted", err=True)
        raise typer.Exit(code=1)
    _drive_loop(questionnaire_id, actor=actor)


def _drive_loop(questionnaire_id: str, *, actor: str | None = None) -> None:
    store = default_store()
    while True:
        qn = store.get_questionnaire(questionnaire_id)
        if qn is None:
            typer.echo("questionnaire vanished", err=True)
            return
        template = store.get_template(qn.template_id, version=qn.template_version)
        if template is None:
            typer.echo("template vanished", err=True)
            return

        q = next_unanswered_question(template.questions, qn.answers)
        if q is None:
            result = validate_for_submission(template, qn.answers)
            if not result.ok:
                typer.echo("answers fail validation:", err=True)
                for err in result.errors:
                    typer.echo(f"  - {err}", err=True)
                raise typer.Exit(code=1)
            try:
                import questionary
                confirm = questionary.confirm(
                    "All questions answered. Submit?", default=True
                ).ask()
            except KeyboardInterrupt:
                typer.echo("\n(saved as draft; resume with `qst answer resume <id>`)")
                return
            if confirm is None:
                typer.echo("\n(saved as draft)")
                return
            if confirm:
                _embed_freetext_answers_if_available(store, template, qn)
                try:
                    store.submit_questionnaire(qn.id, actor=actor)
                    typer.echo(f"submitted questionnaire {qn.id}")
                except SubmissionLockedError as e:
                    typer.echo(f"could not submit: {e}", err=True)
            else:
                typer.echo(f"saved as draft; resume with `qst answer resume {qn.id}`")
            return

        try:
            ans = prompt_for_answer(q)
        except KeyboardInterrupt:
            typer.echo(f"\n(saved as draft; resume with `qst answer resume {qn.id}`)")
            return

        # Tentatively merge to validate, then upsert if structurally OK.
        merged = {**qn.answers, q.id: ans}
        result = validate_answers(template, merged)
        if not result.ok:
            typer.echo("  ! the answer failed validation:", err=True)
            for err in result.errors:
                typer.echo(f"    - {err}", err=True)
            continue

        try:
            store.upsert_answer(qn.id, q.id, ans, actor=actor)
        except SubmissionLockedError as e:
            typer.echo(f"  ! {e}", err=True)
            return


def _embed_freetext_answers_if_available(store, template, qn: Questionnaire) -> None:
    """Best-effort: embed all free-text answers on submit. Silently no-ops if
    the analytics extra isn't installed (we don't want a missing extra to
    block submission)."""
    try:
        from ..analytics.embeddings import embed_text
    except Exception:  # pragma: no cover
        return

    active = resolve_active_questions(template.questions, qn.answers)
    by_id = {q.id: q for q in active}
    for q_id, ans in qn.answers.items():
        q = by_id.get(q_id)
        if not isinstance(q, FreeTextQuestion):
            continue
        if not isinstance(ans.value, str) or not ans.value.strip():
            continue
        try:
            buf, dim = embed_text(ans.value)
        except Exception:
            return  # extra not installed or model load failed; skip silently
        store.save_embedding(qn.id, q_id, buf, dim)


@app.command("show")
def show(questionnaire_id: str):
    store = default_store()
    qn = store.get_questionnaire(questionnaire_id)
    if qn is None:
        typer.echo(f"unknown questionnaire id: {questionnaire_id}", err=True)
        raise typer.Exit(code=1)
    template = store.get_template(qn.template_id, version=qn.template_version)
    if template is None:
        typer.echo(f"orphaned questionnaire — template {qn.template_id} v{qn.template_version} missing", err=True)
        raise typer.Exit(code=1)

    status = "submitted" if qn.is_submitted else "draft"
    typer.echo(f"{qn.id}  template={template.title!r} v{qn.template_version}  status={status}")
    if qn.respondent_id:
        typer.echo(f"respondent: {qn.respondent_id}")
    typer.echo(f"created_at: {qn.created_at}")
    if qn.submitted_at:
        typer.echo(f"submitted_at: {qn.submitted_at}")
    typer.echo("answers:")
    active = resolve_active_questions(template.questions, qn.answers)
    for q in active:
        ans = qn.answers.get(q.id)
        if ans is None:
            typer.echo(f"  - {q.id} ({q.type}): <unanswered>")
        else:
            tag = " [PII]" if getattr(q, "pii", False) else ""
            typer.echo(f"  - {q.id} ({q.type}){tag}: {ans.value!r}")
