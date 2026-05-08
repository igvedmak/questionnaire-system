"""`qst template ...` subcommands."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import typer
from pydantic import ValidationError as PydanticValidationError

from ..domain.types import (
    BooleanQuestion,
    BoolFollowUp,
    DateQuestion,
    Database,
    FreeTextQuestion,
    MultiSelectQuestion,
    Question,
    SelectFollowUp,
    SingleSelectQuestion,
    Template,
)
from ..domain.validation import validate_template
from ..persistence.store import Store, default_db_path

app = typer.Typer(help="Manage questionnaire templates.", no_args_is_help=True)


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_db() -> tuple[Store, Database]:
    store = Store(default_db_path())
    return store, store.load()


def _ids_in_db(db: Database) -> set[str]:
    """Every question id currently used across all templates in the DB."""
    out: set[str] = set()

    def walk(qs: list[Question]) -> None:
        for q in qs:
            out.add(q.id)
            for fu in getattr(q, "follow_ups", []):
                walk(fu.questions)

    for tpl in db.templates.values():
        walk(tpl.questions)
    return out


def _check_no_id_collision(template: Template, db: Database) -> None:
    existing = _ids_in_db(db)
    new_ids: set[str] = set()

    def walk(qs: list[Question]) -> None:
        for q in qs:
            new_ids.add(q.id)
            for fu in getattr(q, "follow_ups", []):
                walk(fu.questions)

    walk(template.questions)
    collisions = existing & new_ids
    if collisions:
        raise typer.BadParameter(
            f"question ids already used by another template: {sorted(collisions)}"
        )


@app.command("create-from-file")
def create_from_file(
    path: Path = typer.Argument(..., exists=True, readable=True, dir_okay=False),
):
    """Load a template from a JSON file. The file should match the Template schema
    (without `id` / `created_at`, which are generated)."""
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

    store, db = _load_db()
    _check_no_id_collision(template, db)
    db.templates[template.id] = template
    store.save(db)

    typer.echo(f"created template {template.id}: {template.title!r}")


@app.command("list")
def list_cmd():
    """List all templates."""
    _, db = _load_db()
    if not db.templates:
        typer.echo("(no templates)")
        return
    for tpl in db.templates.values():
        typer.echo(f"{tpl.id}  {tpl.title}  ({_count_questions(tpl)} questions)")


@app.command("show")
def show(template_id: str):
    """Print a template tree."""
    _, db = _load_db()
    tpl = db.templates.get(template_id)
    if tpl is None:
        typer.echo(f"unknown template id: {template_id}", err=True)
        raise typer.Exit(code=1)
    typer.echo(f"{tpl.id}  {tpl.title}")
    typer.echo(f"created_at: {tpl.created_at}")
    typer.echo("questions:")
    for line in _render_questions(tpl.questions, indent=1):
        typer.echo(line)


@app.command("seed")
def seed():
    """Load two demo templates with nested follow-ups."""
    store, db = _load_db()
    templates = [_seed_medical(), _seed_travel()]
    for tpl in templates:
        if tpl.id in db.templates:
            typer.echo(f"  skip {tpl.id}: already exists")
            continue
        # Seed templates use stable ids; if the previous seed was wiped, those
        # ids may collide if other templates reused them. Sanity check.
        try:
            _check_no_id_collision(tpl, db)
        except typer.BadParameter as e:
            typer.echo(f"  cannot seed {tpl.id}: {e}", err=True)
            continue
        db.templates[tpl.id] = tpl
        typer.echo(f"  seeded {tpl.id}: {tpl.title!r}")
    store.save(db)


# --- Rendering helpers ----------------------------------------------------

def _count_questions(tpl: Template) -> int:
    n = 0

    def walk(qs: list[Question]) -> None:
        nonlocal n
        for q in qs:
            n += 1
            for fu in getattr(q, "follow_ups", []):
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
        lines.append(f"{pad}- [{q.type}] {q.id}: {q.prompt}{suffix}")
        if isinstance(q, BooleanQuestion):
            for fu in q.follow_ups:
                lines.append(f"{pad}  if answer == {fu.when_equals}:")
                lines.extend(_render_questions(fu.questions, indent + 2))
        elif isinstance(q, (SingleSelectQuestion, MultiSelectQuestion)):
            for fu in q.follow_ups:
                lines.append(f"{pad}  if {fu.when_option_selected!r} selected:")
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
                follow_ups=[
                    BoolFollowUp(
                        when_equals=True,
                        questions=[
                            FreeTextQuestion(
                                id="allergy_details",
                                prompt="Please specify your allergies",
                            ),
                        ],
                    )
                ],
            ),
            SingleSelectQuestion(
                id="contact_method",
                prompt="Preferred contact method",
                options=["Email", "Phone", "SMS", "Mail"],
            ),
            DateQuestion(id="date_of_birth", prompt="Date of birth"),
            MultiSelectQuestion(
                id="symptoms",
                prompt="Which symptoms are you experiencing?",
                options=["Headache", "Fever", "Cough", "Fatigue", "Nausea"],
                follow_ups=[
                    SelectFollowUp(
                        when_option_selected="Fever",
                        questions=[
                            FreeTextQuestion(
                                id="fever_duration",
                                prompt="For how many days have you had a fever?",
                            ),
                        ],
                    )
                ],
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
                follow_ups=[
                    SelectFollowUp(
                        when_option_selected="Other",
                        questions=[
                            FreeTextQuestion(
                                id="region_other",
                                prompt="Please specify the region",
                            ),
                        ],
                    )
                ],
            ),
            BooleanQuestion(
                id="business_trip",
                prompt="Was this a business trip?",
                follow_ups=[
                    BoolFollowUp(
                        when_equals=True,
                        questions=[
                            SingleSelectQuestion(
                                id="industry",
                                prompt="Industry",
                                options=["Tech", "Finance", "Healthcare", "Other"],
                                follow_ups=[
                                    SelectFollowUp(
                                        when_option_selected="Other",
                                        questions=[
                                            FreeTextQuestion(
                                                id="industry_other",
                                                prompt="Please specify the industry",
                                            ),
                                        ],
                                    )
                                ],
                            ),
                        ],
                    )
                ],
            ),
            MultiSelectQuestion(
                id="activities",
                prompt="Which activities did you do?",
                options=["Hiking", "Sightseeing", "Food tours", "Beach", "Shopping"],
            ),
            DateQuestion(id="return_date", prompt="Return date"),
        ],
    )
