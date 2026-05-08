"""Admin / ops commands: migrate, audit, gdpr, analytics, api, webhook."""

from __future__ import annotations

import uuid
from pathlib import Path

import typer

from ..persistence import WebhookConfig, default_db_path, default_store
from ..persistence.migrate import migrate_json_to_sql
from ..persistence.store import JsonStore

migrate_app = typer.Typer(help="Migrate from the legacy JSON store.")
audit_app = typer.Typer(help="Audit log inspection.")
gdpr_app = typer.Typer(help="GDPR export and delete.")
analytics_app = typer.Typer(help="Analytics on submitted questionnaires.")
api_app = typer.Typer(help="HTTP API server.")
webhook_app = typer.Typer(help="Manage event-driven webhooks.")


# --- migrate -------------------------------------------------------------

@migrate_app.callback(invoke_without_command=True)
def migrate_default(
    ctx: typer.Context,
    json_path: Path = typer.Option(
        None, "--from-json",
        help="Source path (default: data/db.json).",
    ),
):
    """Migrate JSON → SQLite. Idempotent? No — re-running on a populated SQL
    DB will create new template versions. Run once."""
    if ctx.invoked_subcommand is not None:
        return
    src = JsonStore(json_path or default_db_path())
    if not src.path.exists():
        typer.echo(f"no JSON DB at {src.path}; nothing to migrate")
        raise typer.Exit(code=0)
    sql = default_store()
    result = migrate_json_to_sql(src, sql)
    typer.echo(
        f"migrated: {result.templates_migrated} templates, "
        f"{result.questionnaires_migrated} questionnaires "
        f"({result.questionnaires_submitted} submitted)"
    )


# --- audit ---------------------------------------------------------------

@audit_app.command("list")
def audit_list(
    since: int = typer.Option(0, "--since",
                              help="Only entries with seq > this value"),
):
    store = default_store()
    rows = store.list_audit(since_seq=since)
    if not rows:
        typer.echo("(no audit entries)")
        return
    for r in rows:
        typer.echo(
            f"#{r.seq:04d}  {r.event.ts}  {r.event.action:24s}  "
            f"target={r.event.target_type}/{r.event.target_id}  actor={r.event.actor or '-'}"
        )


@audit_app.command("verify")
def audit_verify():
    """Recompute the hash chain and confirm integrity."""
    store = default_store()
    ok, err = store.verify_audit()
    if ok:
        typer.echo("audit chain OK")
        raise typer.Exit(code=0)
    typer.echo(f"audit chain BROKEN: {err}", err=True)
    raise typer.Exit(code=1)


# --- gdpr ----------------------------------------------------------------

@gdpr_app.command("export")
def gdpr_export(
    respondent_id: str,
    out: Path = typer.Argument(..., help="Output zip path"),
):
    store = default_store()
    payload = store.respondent_export(respondent_id)
    out.write_bytes(payload)
    typer.echo(f"wrote {len(payload)} bytes to {out}")


@gdpr_app.command("delete")
def gdpr_delete(
    respondent_id: str,
    confirm: bool = typer.Option(False, "--yes", help="Skip the confirmation prompt"),
    actor: str = typer.Option(None, "--actor"),
):
    if not confirm:
        if not typer.confirm(
            f"This permanently deletes ALL questionnaires for respondent "
            f"{respondent_id}. Continue?", default=False,
        ):
            typer.echo("aborted")
            raise typer.Exit(code=1)
    store = default_store()
    n = store.respondent_delete(respondent_id, actor=actor)
    typer.echo(f"deleted {n} questionnaires for respondent {respondent_id}")


# --- analytics -----------------------------------------------------------

@analytics_app.command("cluster")
def analytics_cluster(
    question_id: str,
    min_cluster_size: int = typer.Option(3, "--min-cluster-size"),
):
    """Cluster all free-text answers to ``question_id`` semantically.

    Requires the analytics extra: pip install -e .[analytics]
    """
    store = default_store()
    items = store.list_freetext_answers(question_id)
    if not items:
        typer.echo(f"no free-text answers found for question id {question_id!r}")
        raise typer.Exit(code=1)
    try:
        from ..analytics.clustering import cluster_freetext
    except Exception as e:
        typer.echo(f"analytics extra not available: {e}", err=True)
        raise typer.Exit(code=2)

    clusters = cluster_freetext(items, min_cluster_size=min_cluster_size)
    typer.echo(f"{len(items)} answers → {len(clusters)} clusters")
    for c in clusters:
        label = f"cluster #{c.cluster_id}" if c.cluster_id != -1 else "noise (singletons)"
        typer.echo(f"  {label}  size={c.size}")
        typer.echo(f"    exemplar: {c.exemplar_text!r}")


@analytics_app.command("ai-analyze")
def analytics_ai_analyze(
    template_id: str,
    include_drafts: bool = typer.Option(False, "--include-drafts"),
):
    """Stream an AI-generated analysis report for all submitted responses to a template.

    Requires QST_LLM_API_KEY to be set (Anthropic API key).
    """
    store = default_store()
    tpl = store.get_template(template_id)
    if tpl is None:
        typer.echo(f"unknown template id: {template_id!r}", err=True)
        raise typer.Exit(code=1)

    from ..domain.filtering import apply_filters
    from ..domain.types import Questionnaire
    all_qns = store.query_questionnaires([], include_drafts=include_drafts)
    qns = [q for q in all_qns if q.template_id == template_id]

    if not qns:
        typer.echo("no responses found for this template")
        raise typer.Exit(code=1)

    typer.echo(f"Analysing {len(qns)} response(s) for '{tpl.title}' using AI …\n")
    try:
        from ..llm.analyze import stream_analysis
        for chunk in stream_analysis(tpl, qns):
            typer.echo(chunk, nl=False)
    except RuntimeError as e:
        typer.echo(f"\nerror: {e}", err=True)
        raise typer.Exit(code=1)
    typer.echo()  # trailing newline


# --- webhook -------------------------------------------------------------

@webhook_app.command("add")
def webhook_add(
    url: str,
    events: str = typer.Option("questionnaire.submit,gdpr.delete", "--events",
                                help="Comma-separated event names"),
    secret: str = typer.Option(None, "--secret", help="HMAC signing secret"),
):
    """Register a new webhook URL."""
    from datetime import datetime, timezone

    store = default_store()
    event_list = [e.strip() for e in events.split(",") if e.strip()]
    wh = WebhookConfig(
        id=str(uuid.uuid4()),
        url=url,
        events=event_list,
        secret=secret,
        created_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        active=True,
    )
    store.save_webhook(wh)
    typer.echo(f"registered webhook {wh.id} → {url}  events={event_list}")


@webhook_app.command("list")
def webhook_list():
    """List all registered webhooks."""
    store = default_store()
    hooks = store.list_webhooks()
    if not hooks:
        typer.echo("(no webhooks)")
        return
    for wh in hooks:
        status = "active" if wh.active else "disabled"
        typer.echo(f"{wh.id}  {wh.url}  events={wh.events}  status={status}")


@webhook_app.command("delete")
def webhook_delete(webhook_id: str):
    """Delete a webhook by id."""
    from ..persistence.sql_store import StoreError

    store = default_store()
    try:
        store.delete_webhook(webhook_id)
    except StoreError as e:
        typer.echo(f"error: {e}", err=True)
        raise typer.Exit(code=1)
    typer.echo(f"deleted webhook {webhook_id}")


# --- api -----------------------------------------------------------------

@api_app.callback(invoke_without_command=True)
def api_default(
    ctx: typer.Context,
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int = typer.Option(8000, "--port"),
):
    """Run the HTTP API. Same data as the CLI; OpenAPI docs at /docs."""
    if ctx.invoked_subcommand is not None:
        return
    import uvicorn
    uvicorn.run("questionnaire.api.app:app", host=host, port=port, reload=False)
