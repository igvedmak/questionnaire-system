"""`qst template ...` subcommands."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import typer
from pydantic import ValidationError as PydanticValidationError

from ..domain.types import (
    BoolFollowUp,
    BooleanQuestion,
    DateQuestion,
    FreeTextQuestion,
    MultiSelectQuestion,
    NumberQuestion,
    Question,
    SelectFollowUp,
    SingleSelectQuestion,
    Template,
)
from ..domain.validation import validate_template
from ..persistence import StoreError, default_store

app = typer.Typer(help="Manage questionnaire templates.", no_args_is_help=True)


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@app.command("create-from-file")
def create_from_file(
    path: Path = typer.Argument(..., exists=True, readable=True, dir_okay=False),
    actor: str = typer.Option(None, "--actor", help="Recorded in the audit log"),
):
    """Load a template from a JSON file. New templates start at v1; subsequent
    saves of the same id append a new version."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw.setdefault("id", str(uuid.uuid4()))
    raw.setdefault("created_at", _now_iso())

    try:
        template = Template.model_validate(raw)
    except PydanticValidationError as e:
        typer.echo(f"template JSON is malformed:\n{e}", err=True)
        raise typer.Exit(code=2)

    structural = validate_template(template)
    if not structural.ok:
        typer.echo("template failed structural validation:", err=True)
        for err in structural.errors:
            typer.echo(f"  - {err}", err=True)
        raise typer.Exit(code=2)

    store = default_store()
    saved = store.save_template(template, actor=actor)
    typer.echo(f"saved template {saved.id} v{saved.version}: {saved.title!r}")


@app.command("list")
def list_cmd():
    """List all templates at their current version."""
    store = default_store()
    templates = store.list_templates()
    if not templates:
        typer.echo("(no templates)")
        return
    for tpl in templates:
        n = _count_questions(tpl)
        typer.echo(f"{tpl.id}  v{tpl.version}  {tpl.title}  ({n} questions)")


@app.command("show")
def show(
    template_id: str,
    version: int = typer.Option(None, "--version", "-v",
                                help="Show a specific version (default: current)"),
):
    store = default_store()
    tpl = store.get_template(template_id, version=version)
    if tpl is None:
        typer.echo(f"unknown template id: {template_id}", err=True)
        raise typer.Exit(code=1)
    typer.echo(f"{tpl.id}  v{tpl.version}  {tpl.title}")
    typer.echo(f"created_at: {tpl.created_at}")
    versions = store.list_template_versions(template_id)
    if len(versions) > 1:
        typer.echo(f"versions: {versions}")
    typer.echo("questions:")
    for line in _render_questions(tpl.questions, indent=1):
        typer.echo(line)


@app.command("stats")
def stats(template_id: str):
    """Show submission/draft counts and per-question answer counts for a template."""
    store = default_store()
    result = store.get_template_stats(template_id)
    if result is None:
        typer.echo(f"unknown template id: {template_id}", err=True)
        raise typer.Exit(code=1)
    typer.echo(f"template: {result.template_id}  v{result.version}")
    typer.echo(f"submissions: {result.total_submissions}")
    typer.echo(f"drafts:      {result.total_drafts}")
    typer.echo("answer counts:")
    for qid, count in sorted(result.answer_counts.items()):
        typer.echo(f"  {qid}: {count}")


@app.command("duplicate")
def duplicate(
    template_id: str,
    new_id: str = typer.Option(None, "--new-id", help="New template id (auto-generated if omitted)"),
    actor: str = typer.Option(None, "--actor"),
):
    """Create a copy of a template with a new id."""
    store = default_store()
    try:
        copy = store.duplicate_template(template_id, new_id=new_id or None, actor=actor)
    except StoreError as e:
        typer.echo(f"error: {e}", err=True)
        raise typer.Exit(code=1)
    typer.echo(f"duplicated {template_id} → {copy.id} v{copy.version}: {copy.title!r}")


@app.command("seed")
def seed(actor: str = typer.Option(None, "--actor")):
    """Load two demo templates with nested follow-ups."""
    store = default_store()
    existing = {t.id for t in store.list_templates()}
    seeds = [_seed_medical(), _seed_travel()]
    for tpl in seeds:
        if tpl.id in existing:
            typer.echo(f"  skip {tpl.id}: already exists")
            continue
        store.save_template(tpl, actor=actor)
        typer.echo(f"  seeded {tpl.id}: {tpl.title!r}")


# --- Rendering helpers ----------------------------------------------------

def _count_questions(tpl: Template) -> int:
    n = 0

    def walk(qs: list[Question]) -> None:
        nonlocal n
        for q in qs:
            n += 1
            for fu in getattr(q, "follow_ups", []) or []:
                walk(fu.questions)

    walk(tpl.questions)
    return n


def _render_questions(qs: list[Question], indent: int) -> list[str]:
    lines: list[str] = []
    pad = "  " * indent
    for q in qs:
        suffix = ""
        if isinstance(q, (SingleSelectQuestion, MultiSelectQuestion)):
            suffix = f"  options={q.options}"
        elif isinstance(q, NumberQuestion):
            bits = []
            if q.min is not None: bits.append(f"min={q.min}")
            if q.max is not None: bits.append(f"max={q.max}")
            if q.integer: bits.append("integer")
            if bits: suffix = f"  ({', '.join(bits)})"
        if getattr(q, "pii", False):
            suffix += "  [PII]"
        lines.append(f"{pad}- [{q.type}] {q.id}: {q.prompt}{suffix}")
        for fu in getattr(q, "follow_ups", []) or []:
            if isinstance(fu, BoolFollowUp):
                lines.append(f"{pad}  if answer == {fu.when_equals}:")
            elif isinstance(fu, SelectFollowUp):
                lines.append(f"{pad}  if {fu.when_option_selected!r} selected:")
            else:  # ExprFollowUp
                lines.append(f"{pad}  if expr({fu.condition.op}):")
            lines.extend(_render_questions(fu.questions, indent + 2))
    return lines


# --- Demo templates -------------------------------------------------------

def _seed_medical() -> Template:
    return Template(
        id="tpl_medical",
        title="Medical Intake",
        created_at=_now_iso(),
        questions=[
            BooleanQuestion(
                id="has_allergies",
                prompt="Do you have any allergies?",
                follow_ups=[BoolFollowUp(
                    when_equals=True,
                    questions=[FreeTextQuestion(
                        id="allergy_details",
                        prompt="Please specify your allergies",
                        pii=True,  # PII flag triggers encryption at rest
                    )],
                )],
            ),
            SingleSelectQuestion(
                id="contact_method",
                prompt="Preferred contact method",
                options=["Email", "Phone", "SMS", "Mail"],
            ),
            DateQuestion(id="date_of_birth", prompt="Date of birth"),
            NumberQuestion(
                id="age",
                prompt="Your age",
                min=0, max=130, integer=True,
            ),
            MultiSelectQuestion(
                id="symptoms",
                prompt="Which symptoms are you experiencing?",
                options=["Headache", "Fever", "Cough", "Fatigue", "Nausea"],
                follow_ups=[SelectFollowUp(
                    when_option_selected="Fever",
                    questions=[FreeTextQuestion(
                        id="fever_duration",
                        prompt="For how many days have you had a fever?",
                    )],
                )],
            ),
        ],
    )


def _seed_travel() -> Template:
    return Template(
        id="tpl_travel",
        title="Travel Survey",
        created_at=_now_iso(),
        questions=[
            SingleSelectQuestion(
                id="region",
                prompt="Which region did you travel to?",
                options=["North America", "Europe", "Asia", "Other"],
                follow_ups=[SelectFollowUp(
                    when_option_selected="Other",
                    questions=[FreeTextQuestion(
                        id="region_other",
                        prompt="Please specify the region",
                    )],
                )],
            ),
            BooleanQuestion(
                id="business_trip",
                prompt="Was this a business trip?",
                follow_ups=[BoolFollowUp(
                    when_equals=True,
                    questions=[SingleSelectQuestion(
                        id="industry",
                        prompt="Industry",
                        options=["Tech", "Finance", "Healthcare", "Other"],
                        follow_ups=[SelectFollowUp(
                            when_option_selected="Other",
                            questions=[FreeTextQuestion(
                                id="industry_other",
                                prompt="Please specify the industry",
                            )],
                        )],
                    )],
                )],
            ),
            MultiSelectQuestion(
                id="activities",
                prompt="Which activities did you do?",
                options=["Hiking", "Sightseeing", "Food tours", "Beach", "Shopping"],
            ),
            DateQuestion(id="return_date", prompt="Return date"),
            FreeTextQuestion(
                id="favorite_moment",
                prompt="Describe your favorite moment from the trip",
            ),
        ],
    )
