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
    EmailQuestion,
    FreeTextQuestion,
    MultiSelectQuestion,
    NumberQuestion,
    Question,
    RatingQuestion,
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
    """Load demo templates covering 6 domains with nested follow-ups."""
    store = default_store()
    existing = {t.id for t in store.list_templates()}
    seeds = [
        _seed_medical(),
        _seed_travel(),
        _seed_hr_onboarding(),
        _seed_product_feedback(),
        _seed_event_registration(),
        _seed_customer_support(),
    ]
    for tpl in seeds:
        if tpl.id in existing:
            typer.echo(f"  skip {tpl.id}: already exists")
            continue
        store.save_template(tpl, actor=actor)
        typer.echo(f"  seeded {tpl.id}: {tpl.title!r}")


@app.command("ai-generate")
def ai_generate(
    description: str = typer.Argument(..., help="Natural language description of the questionnaire"),
    save: bool = typer.Option(True, "--save/--dry-run", help="Save to database (default) or just print"),
    actor: str = typer.Option(None, "--actor"),
):
    """Generate a questionnaire template from a natural-language description using AI.

    Requires QST_LLM_API_KEY to be set (Anthropic API key).
    """
    typer.echo(f"Generating template for: {description!r} …")
    try:
        from ..llm.generate import generate_template
        tpl = generate_template(description)
    except RuntimeError as e:
        typer.echo(f"error: {e}", err=True)
        raise typer.Exit(code=1)

    typer.echo(f"\nGenerated: {tpl.id}  |  {tpl.title}")
    for line in _render_questions(tpl.questions, indent=1):
        typer.echo(line)

    if save:
        store = default_store()
        store.save_template(tpl, actor=actor)
        typer.echo(f"\nsaved: {tpl.id}")
    else:
        import json
        typer.echo("\n--- JSON (dry-run, not saved) ---")
        typer.echo(tpl.model_dump_json(indent=2))


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


def _seed_hr_onboarding() -> Template:
    return Template(
        id="tpl_hr_onboarding",
        title="Employee Onboarding",
        description="Collect new-hire information and preferences on day 1.",
        created_at=_now_iso(),
        questions=[
            FreeTextQuestion(id="full_name", prompt="Full legal name", pii=True),
            EmailQuestion(id="work_email", prompt="Work email address", pii=True),
            DateQuestion(id="start_date", prompt="Start date"),
            SingleSelectQuestion(
                id="employment_type",
                prompt="Employment type",
                options=["Full-time", "Part-time", "Contractor", "Intern"],
            ),
            SingleSelectQuestion(
                id="work_location",
                prompt="Primary work location",
                options=["On-site", "Remote", "Hybrid"],
                follow_ups=[SelectFollowUp(
                    when_option_selected="On-site",
                    questions=[SingleSelectQuestion(
                        id="office_site",
                        prompt="Which office?",
                        options=["HQ", "East Hub", "West Hub", "International"],
                    )],
                )],
            ),
            MultiSelectQuestion(
                id="equipment_needed",
                prompt="Equipment needed (select all that apply)",
                options=["Laptop", "Monitor", "Keyboard", "Mouse", "Headset", "Docking station"],
            ),
            BooleanQuestion(
                id="has_dietary",
                prompt="Do you have dietary restrictions or preferences?",
                follow_ups=[BoolFollowUp(
                    when_equals=True,
                    questions=[FreeTextQuestion(
                        id="dietary_details",
                        prompt="Please describe your dietary needs",
                    )],
                )],
            ),
            SingleSelectQuestion(
                id="shirt_size",
                prompt="Company swag shirt size",
                options=["XS", "S", "M", "L", "XL", "XXL"],
            ),
            RatingQuestion(
                id="onboarding_experience",
                prompt="How would you rate your onboarding experience so far?",
                min_val=1, max_val=5,
                min_label="Very poor", max_label="Excellent",
            ),
            FreeTextQuestion(id="first_day_feedback", prompt="Any questions or comments for HR?", required=False),
        ],
    )


def _seed_product_feedback() -> Template:
    return Template(
        id="tpl_product_feedback",
        title="Product Feedback Survey",
        description="Net Promoter Score + qualitative feedback for product teams.",
        created_at=_now_iso(),
        questions=[
            RatingQuestion(
                id="nps",
                prompt="How likely are you to recommend our product to a colleague? (0 = not at all, 10 = extremely likely)",
                min_val=0, max_val=10,
                min_label="Not at all likely", max_label="Extremely likely",
            ),
            SingleSelectQuestion(
                id="usage_frequency",
                prompt="How often do you use the product?",
                options=["Daily", "Several times a week", "Once a week", "A few times a month", "Rarely"],
            ),
            MultiSelectQuestion(
                id="features_used",
                prompt="Which features do you use most? (select all that apply)",
                options=["Dashboard", "Reports", "Integrations", "API", "Mobile app", "Collaboration tools"],
            ),
            RatingQuestion(
                id="ease_of_use",
                prompt="How easy is the product to use?",
                min_val=1, max_val=5,
                min_label="Very difficult", max_label="Very easy",
            ),
            BooleanQuestion(
                id="encountered_bugs",
                prompt="Have you encountered any bugs or issues in the past 30 days?",
                follow_ups=[BoolFollowUp(
                    when_equals=True,
                    questions=[FreeTextQuestion(
                        id="bug_description",
                        prompt="Please describe the issue(s) you encountered",
                    )],
                )],
            ),
            SingleSelectQuestion(
                id="biggest_pain_point",
                prompt="What is your biggest pain point with the product?",
                options=["Performance", "Missing features", "Confusing UI", "Poor documentation", "Pricing", "Other"],
                follow_ups=[SelectFollowUp(
                    when_option_selected="Other",
                    questions=[FreeTextQuestion(
                        id="pain_point_other",
                        prompt="Please describe your pain point",
                    )],
                )],
            ),
            FreeTextQuestion(
                id="improvement_suggestion",
                prompt="What one thing would most improve the product for you?",
                required=False,
            ),
        ],
    )


def _seed_event_registration() -> Template:
    return Template(
        id="tpl_event_registration",
        title="Conference Registration",
        description="Collect attendee information and session preferences for a multi-track conference.",
        created_at=_now_iso(),
        questions=[
            FreeTextQuestion(id="attendee_name", prompt="Full name", pii=True),
            EmailQuestion(id="attendee_email", prompt="Email address", pii=True),
            FreeTextQuestion(id="organisation", prompt="Organisation / company"),
            SingleSelectQuestion(
                id="ticket_type",
                prompt="Ticket type",
                options=["General admission", "VIP", "Speaker", "Sponsor", "Press"],
            ),
            MultiSelectQuestion(
                id="tracks",
                prompt="Which tracks are you most interested in?",
                options=["Engineering", "Product", "Design", "Data & AI", "Leadership", "Community"],
            ),
            SingleSelectQuestion(
                id="attendance_mode",
                prompt="Attendance mode",
                options=["In-person", "Virtual", "Hybrid (both days)"],
                follow_ups=[SelectFollowUp(
                    when_option_selected="In-person",
                    questions=[
                        BooleanQuestion(
                            id="needs_hotel",
                            prompt="Do you need hotel recommendations?",
                        ),
                        SingleSelectQuestion(
                            id="dietary_pref",
                            prompt="Dietary preference for catered meals",
                            options=["No restriction", "Vegetarian", "Vegan", "Gluten-free", "Halal", "Kosher"],
                        ),
                    ],
                )],
            ),
            BooleanQuestion(
                id="speaking",
                prompt="Are you submitting a talk or workshop proposal?",
                follow_ups=[BoolFollowUp(
                    when_equals=True,
                    questions=[FreeTextQuestion(
                        id="talk_title",
                        prompt="Proposed session title and 1-2 sentence abstract",
                    )],
                )],
            ),
            FreeTextQuestion(id="special_requests", prompt="Accessibility or special requirements", required=False),
        ],
    )


def _seed_customer_support() -> Template:
    return Template(
        id="tpl_customer_support",
        title="Customer Support Ticket",
        description="Gather structured information when a customer opens a support request.",
        created_at=_now_iso(),
        questions=[
            FreeTextQuestion(id="contact_name", prompt="Your name", pii=True),
            EmailQuestion(id="contact_email", prompt="Contact email", pii=True),
            SingleSelectQuestion(
                id="issue_category",
                prompt="What type of issue are you experiencing?",
                options=["Account / login", "Billing", "Technical / bug", "Feature request", "Performance", "Other"],
                follow_ups=[
                    SelectFollowUp(
                        when_option_selected="Technical / bug",
                        questions=[
                            SingleSelectQuestion(
                                id="affected_platform",
                                prompt="Which platform is affected?",
                                options=["Web browser", "iOS app", "Android app", "API / webhooks", "All platforms"],
                            ),
                            FreeTextQuestion(
                                id="steps_to_reproduce",
                                prompt="Steps to reproduce the issue",
                            ),
                        ],
                    ),
                    SelectFollowUp(
                        when_option_selected="Billing",
                        questions=[FreeTextQuestion(
                            id="invoice_number",
                            prompt="Invoice or order number (if applicable)",
                            required=False,
                        )],
                    ),
                    SelectFollowUp(
                        when_option_selected="Other",
                        questions=[FreeTextQuestion(
                            id="issue_other_detail",
                            prompt="Please describe your issue",
                        )],
                    ),
                ],
            ),
            SingleSelectQuestion(
                id="severity",
                prompt="How severely is this affecting your work?",
                options=["Blocking — cannot work", "Major — significantly impaired", "Minor — workaround exists", "Low — cosmetic or question"],
            ),
            BooleanQuestion(
                id="first_occurrence",
                prompt="Is this the first time you have experienced this issue?",
                follow_ups=[BoolFollowUp(
                    when_equals=False,
                    questions=[DateQuestion(
                        id="first_occurrence_date",
                        prompt="Approximately when did you first notice this issue?",
                    )],
                )],
            ),
            FreeTextQuestion(id="additional_context", prompt="Any additional context, screenshots, or logs to share?", required=False),
            RatingQuestion(
                id="support_satisfaction",
                prompt="How satisfied are you with our support experience so far?",
                min_val=1, max_val=5,
                min_label="Very dissatisfied", max_label="Very satisfied",
                required=False,
            ),
        ],
    )
