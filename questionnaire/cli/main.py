"""CLI entry point. Subcommands are registered as nested Typer apps."""

from __future__ import annotations

import typer

from . import admin_cmd, answer_cmd, query_cmd, template_cmd

app = typer.Typer(
    help="Questionnaire engine: templates, instances, expression-based "
         "follow-ups, audit log, semantic free-text analytics.",
    no_args_is_help=True,
)
app.add_typer(template_cmd.app, name="template")
app.add_typer(answer_cmd.app, name="answer")
app.add_typer(admin_cmd.migrate_app, name="migrate")
app.add_typer(admin_cmd.audit_app, name="audit")
app.add_typer(admin_cmd.gdpr_app, name="gdpr")
app.add_typer(admin_cmd.analytics_app, name="analytics")
app.add_typer(admin_cmd.api_app, name="api")
# `qst list` / `qst export` live at the top level for ergonomics.
app.registered_commands.extend(query_cmd.app.registered_commands)


if __name__ == "__main__":
    app()
