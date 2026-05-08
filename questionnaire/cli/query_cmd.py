"""`qst list` and `qst show` — query and filter answered questionnaires."""

from __future__ import annotations

import typer

from ..domain.filtering import FilterError, apply_filters, parse_filters
from ..persistence.store import Store, default_db_path

app = typer.Typer(help="Query questionnaires.", no_args_is_help=False)


@app.command("list")
def list_cmd(
    template: str = typer.Option(
        None, "--template", "-t", help="Only questionnaires for this template id."
    ),
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
    """List answered questionnaires, optionally filtered.

    Multiple filters are combined with AND.
    By default only submitted questionnaires are listed.
    """
    store = Store(default_db_path())
    db = store.load()

    try:
        filters = parse_filters(template, includes, excludes, db.templates)
    except FilterError as e:
        typer.echo(f"invalid filter: {e}", err=True)
        raise typer.Exit(code=2)

    pool = list(db.questionnaires.values())
    if not include_drafts:
        pool = [q for q in pool if q.is_submitted]

    matches = apply_filters(pool, filters)
    if not matches:
        typer.echo("(no matches)")
        return

    for qn in matches:
        tpl = db.templates.get(qn.template_id)
        title = tpl.title if tpl else "<missing template>"
        status = "submitted" if qn.is_submitted else "draft"
        typer.echo(f"{qn.id}  template={title!r}  status={status}  answers={len(qn.answers)}")
