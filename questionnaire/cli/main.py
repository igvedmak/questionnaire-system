"""CLI entry point. Subcommands are registered as nested Typer apps."""

from __future__ import annotations

import typer

from . import answer_cmd, query_cmd, template_cmd

app = typer.Typer(
    help="Questionnaire system: define templates, answer them, query the results.",
    no_args_is_help=True,
)
app.add_typer(template_cmd.app, name="template")
app.add_typer(answer_cmd.app, name="answer")

# `qst list` for questionnaires lives at the top level for ergonomics — it's
# the most-used query command. `qst answer show <id>` shows an individual one.
app.registered_commands.extend(query_cmd.app.registered_commands)


if __name__ == "__main__":
    app()
