"""`qst answer ...` — start or resume answering a questionnaire."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import typer

from ..domain.flow import next_unanswered_question, resolve_active_questions
from ..domain.types import Database, Questionnaire
from ..domain.validation import validate_answers, validate_for_submission
from ..persistence.store import Store, default_db_path
from .prompt import prompt_for_answer

app = typer.Typer(help="Answer questionnaires.", no_args_is_help=True)


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_db() -> tuple[Store, Database]:
    store = Store(default_db_path())
    return store, store.load()


@app.command("start")
def start(template_id: str):
    """Create a new questionnaire from a template and answer it interactively."""
    store, db = _load_db()
    template = db.templates.get(template_id)
    if template is None:
        typer.echo(f"unknown template id: {template_id}", err=True)
        raise typer.Exit(code=1)

    qn = Questionnaire(
        id=str(uuid.uuid4()),
        template_id=template_id,
        created_at=_now_iso(),
        answers={},
    )
    db.questionnaires[qn.id] = qn
    store.save(db)
    typer.echo(f"started questionnaire {qn.id} on template {template.title!r}")
    typer.echo()

    _drive_loop(store, db, qn.id)


@app.command("resume")
def resume(questionnaire_id: str):
    """Continue answering a draft questionnaire."""
    store, db = _load_db()
    qn = db.questionnaires.get(questionnaire_id)
    if qn is None:
        typer.echo(f"unknown questionnaire id: {questionnaire_id}", err=True)
        raise typer.Exit(code=1)
    if qn.is_submitted:
        typer.echo(f"questionnaire {qn.id} is already submitted", err=True)
        raise typer.Exit(code=1)
    _drive_loop(store, db, qn.id)


def _drive_loop(store: Store, db: Database, questionnaire_id: str) -> None:
    """The interactive answering loop.

    Reads the latest questionnaire state from `db` on each iteration so that
    follow-ups appearing as a result of the just-given answer are picked up
    immediately. Persists after every answer so a crash mid-session doesn't
    lose progress.
    """
    while True:
        qn = db.questionnaires[questionnaire_id]
        template = db.templates[qn.template_id]

        q = next_unanswered_question(template.questions, qn.answers)
        if q is None:
            # All active questions answered; offer to submit.
            result = validate_for_submission(template, qn.answers)
            if not result.ok:
                # Shouldn't happen — next_unanswered_question already handles
                # the missing-answer case. But guard against type/option errors.
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
                typer.echo("\n(saved as draft; resume with `qst answer resume <id>`)")
                return
            if confirm:
                qn.submitted_at = _now_iso()
                store.save(db)
                typer.echo(f"submitted questionnaire {qn.id}")
            else:
                typer.echo(f"saved as draft; resume with `qst answer resume {qn.id}`")
            return

        try:
            ans = prompt_for_answer(q)
        except KeyboardInterrupt:
            typer.echo(f"\n(saved as draft; resume with `qst answer resume {qn.id}`)")
            return

        # Tentatively place the answer, validate, and only persist if it's
        # well-formed. Since prompts already enforce structural correctness,
        # this is mostly a belt-and-braces check.
        qn.answers[q.id] = ans
        result = validate_answers(template, qn.answers)
        if not result.ok:
            typer.echo("  ! the answer failed validation:", err=True)
            for err in result.errors:
                typer.echo(f"    - {err}", err=True)
            del qn.answers[q.id]
            continue

        # Save after every answer so we never lose progress mid-session.
        store.save(db)


@app.command("show")
def show(questionnaire_id: str):
    """Print a questionnaire's current answers."""
    _, db = _load_db()
    qn = db.questionnaires.get(questionnaire_id)
    if qn is None:
        typer.echo(f"unknown questionnaire id: {questionnaire_id}", err=True)
        raise typer.Exit(code=1)
    template = db.templates.get(qn.template_id)
    if template is None:
        typer.echo(f"orphaned questionnaire — template {qn.template_id} missing", err=True)
        raise typer.Exit(code=1)

    status = "submitted" if qn.is_submitted else "draft"
    typer.echo(f"{qn.id}  template={template.title!r}  status={status}")
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
            typer.echo(f"  - {q.id} ({q.type}): {ans.value!r}")
