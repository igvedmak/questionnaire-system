"""`qst list` and `qst export` — query and export answered questionnaires."""

from __future__ import annotations

import csv
import sys
from pathlib import Path

import typer

from ..domain.filtering import FilterError, parse_filters
from ..domain.flow import resolve_active_questions
from ..persistence import default_store

app = typer.Typer(help="Query questionnaires.", no_args_is_help=False)


@app.command("list")
def list_cmd(
    template: str = typer.Option(None, "--template", "-t",
                                 help="Only questionnaires for this template id."),
    includes: list[str] = typer.Option(
        [], "--includes", "-i",
        help="Format: '<questionId>=<value>'. Repeatable. Single/multi-select only.",
    ),
    excludes: list[str] = typer.Option(
        [], "--excludes", "-x",
        help="Format: '<questionId>=<value>'. Repeatable. Single/multi-select only.",
    ),
    include_drafts: bool = typer.Option(
        False, "--include-drafts",
        help="Include draft (unsubmitted) questionnaires in the result.",
    ),
):
    """List answered questionnaires, optionally filtered. AND-combined."""
    store = default_store()
    templates = {t.id: t for t in store.list_templates()}
    try:
        filters = parse_filters(template, includes, excludes, templates)
    except FilterError as e:
        typer.echo(f"invalid filter: {e}", err=True)
        raise typer.Exit(code=2)

    matches = store.query_questionnaires(filters, include_drafts=include_drafts)
    if not matches:
        typer.echo("(no matches)")
        return

    for qn in matches:
        tpl = templates.get(qn.template_id) or store.get_template(qn.template_id, qn.template_version)
        title = tpl.title if tpl else "<missing>"
        status = "submitted" if qn.is_submitted else "draft"
        typer.echo(
            f"{qn.id}  template={title!r} v{qn.template_version}  "
            f"status={status}  answers={len(qn.answers)}"
        )


@app.command("export")
def export(
    out: Path = typer.Argument(..., help="Output CSV path; '-' for stdout"),
    template: str = typer.Option(None, "--template", "-t"),
    includes: list[str] = typer.Option([], "--includes", "-i"),
    excludes: list[str] = typer.Option([], "--excludes", "-x"),
    include_drafts: bool = typer.Option(False, "--include-drafts"),
):
    """Stream filtered submissions to CSV. One row per questionnaire; columns
    are derived from the union of question ids actually answered."""
    store = default_store()
    templates = {t.id: t for t in store.list_templates()}
    try:
        filters = parse_filters(template, includes, excludes, templates)
    except FilterError as e:
        typer.echo(f"invalid filter: {e}", err=True)
        raise typer.Exit(code=2)

    # Two-pass: first collect column ids in order of first appearance, then
    # write rows. We keep the first pass cheap by reading metadata only.
    seen_columns: list[str] = []
    seen_set: set[str] = set()
    rows_buf: list[dict] = []
    for qn in store.stream_query_for_export(filters, include_drafts=include_drafts):
        tpl = templates.get(qn.template_id) or store.get_template(qn.template_id, qn.template_version)
        active = resolve_active_questions(tpl.questions, qn.answers) if tpl else []
        for q in active:
            if q.id not in seen_set:
                seen_set.add(q.id)
                seen_columns.append(q.id)
        row = {
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
    fp = sys.stdout if str(out) == "-" else open(out, "w", newline="", encoding="utf-8")
    try:
        writer = csv.DictWriter(fp, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for r in rows_buf:
            writer.writerow(r)
    finally:
        if fp is not sys.stdout:
            fp.close()
            typer.echo(f"wrote {len(rows_buf)} rows to {out}")
