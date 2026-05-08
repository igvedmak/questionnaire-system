"""`qst doctor` — end-to-end self-test.

Replaces the manual checklist in the README with a single command that
exercises every CLI capability and the HTTP API. No interactive
prompts (`qst answer fill` substitutes for `qst answer start`); no
external tools (Python's stdlib `sqlite3` substitutes for the
`sqlite3` CLI in the tamper test).

Use cases:
- New environment validation.
- Pre-deploy / pre-release smoke.
- CI gate.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import sqlite3 as _sqlite
import subprocess
import sys
import tempfile
import time
import urllib.request
import uuid
import zipfile
from contextlib import closing
from io import BytesIO
from pathlib import Path
from urllib.error import HTTPError

import typer

app = typer.Typer(help="Self-tests.", no_args_is_help=False)


# --- Tiny test-runner inside the CLI ------------------------------------

class _Runner:
    """Pretty PASS/FAIL accumulator that keeps going on failure."""

    def __init__(self) -> None:
        self.passed = 0
        self.failed = 0
        self.failures: list[str] = []

    def check(self, name: str, ok: bool, detail: str = "") -> bool:
        if ok:
            self.passed += 1
            typer.echo(f"  ✓ {name}")
        else:
            self.failed += 1
            self.failures.append(f"{name}: {detail or 'failed'}")
            typer.echo(f"  ✗ {name}  ({detail})", err=True)
        return ok

    def summary(self) -> int:
        total = self.passed + self.failed
        typer.echo()
        typer.echo(f"  {self.passed}/{total} passed")
        if self.failed:
            typer.echo("  failures:", err=True)
            for f in self.failures:
                typer.echo(f"    - {f}", err=True)
            return 1
        return 0


# --- HTTP helpers -------------------------------------------------------

def _request(method: str, url: str, *, data=None, headers=None, want_status=200):
    """Tiny urllib wrapper: returns (status, body_bytes)."""
    req = urllib.request.Request(url, method=method, headers=headers or {})
    if data is not None:
        req.add_header("Content-Type", "application/json")
        body = json.dumps(data).encode("utf-8")
    else:
        body = None
    try:
        with urllib.request.urlopen(req, data=body, timeout=10) as resp:
            return resp.status, resp.read()
    except HTTPError as e:
        return e.code, e.read()


def _wait_port(host: str, port: int, *, timeout: float = 8.0) -> bool:
    """Block until something is listening on (host, port), or timeout."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
            s.settimeout(0.2)
            try:
                s.connect((host, port))
                return True
            except OSError:
                time.sleep(0.1)
    return False


def _free_port() -> int:
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# --- Domain probe (CLI side) --------------------------------------------

def _check_cli_workflow(r: _Runner, db_dir: Path) -> str | None:
    """Drive the CLI side of the checklist using the public Python API
    (so we can run inside this process — no subprocess needed)."""
    from ..domain.types import (
        BooleanAnswer, DateAnswer, FreeTextAnswer, MultiSelectAnswer,
        NumberAnswer, Questionnaire, SingleSelectAnswer,
    )
    from ..domain.filtering import (
        ExcludesFilter, IncludesFilter, TemplateFilter,
    )
    from ..persistence.sql_store import SqlStore
    from .template_cmd import _seed_medical, _seed_travel
    from datetime import datetime, timezone

    def now():
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")

    db_url = f"sqlite:///{db_dir / 'doctor.sqlite'}"
    s = SqlStore(db_url)

    # 2. Seed templates
    s.save_template(_seed_medical(), actor="doctor")
    s.save_template(_seed_travel(), actor="doctor")
    r.check("template seed", len(s.list_templates()) == 2)

    # 3. Versioning: re-save tpl_medical and check version bump
    s.save_template(_seed_medical(), actor="doctor")
    versions = s.list_template_versions("tpl_medical")
    r.check("template versioning", versions == [1, 2],
            detail=f"versions={versions}")
    cur = s.get_template("tpl_medical")
    r.check("get_template returns current version", cur and cur.version == 2)

    # 4. Submit a populated questionnaire (substitute for interactive)
    qn = Questionnaire(
        id="doctor-q1", template_id="tpl_medical", template_version=2,
        created_at=now(), respondent_id="alice",
        answers={
            "has_allergies": BooleanAnswer(value=True),
            "allergy_details": FreeTextAnswer(value="seeds"),
            "contact_method": SingleSelectAnswer(value="Email"),
            "date_of_birth": DateAnswer(value="1991-11-13"),
            "age": NumberAnswer(value=33),
            "symptoms": MultiSelectAnswer(value=["Fever", "Headache"]),
            "fever_duration": FreeTextAnswer(value="2 days"),
        },
    )
    s.save_questionnaire(qn, actor="doctor")
    s.submit_questionnaire(qn.id, actor="doctor")
    r.check("submit questionnaire (incl. number type + PII)",
            s.get_questionnaire("doctor-q1").is_submitted)

    # 5. AND-combined filters via SQL pushdown
    out = s.query_questionnaires([
        TemplateFilter("tpl_medical"),
        IncludesFilter("contact_method", "Email"),
        IncludesFilter("symptoms", "Fever"),
        ExcludesFilter("symptoms", "Beach"),
    ])
    r.check("AND filter (template + 2 includes + 1 excludes)",
            [q.id for q in out] == ["doctor-q1"])

    # 6. PII decrypted on read
    qn_loaded = s.get_questionnaire("doctor-q1")
    r.check("PII decrypted on read",
            qn_loaded.answers["allergy_details"].value == "seeds")

    # 7. Submission immutability
    from ..persistence.sql_store import SubmissionLockedError
    immut_ok = False
    try:
        s.upsert_answer("doctor-q1", "contact_method", SingleSelectAnswer(value="Phone"))
    except SubmissionLockedError:
        immut_ok = True
    r.check("submission immutability blocks edits", immut_ok)

    # 8a. Audit chain verifies
    ok, err = s.verify_audit()
    r.check("audit chain OK", ok, detail=err or "")

    # 8b. Tamper test (Python sqlite3 — no external CLI needed)
    db_path = db_dir / "doctor.sqlite"
    s.engine.dispose()  # release SQLite connection so we can open with stdlib
    with _sqlite.connect(db_path) as conn:
        conn.execute(
            "UPDATE audit_log SET payload_json = ? WHERE seq = 1",
            ('{"hacked":true}',),
        )
        conn.commit()
    s2 = SqlStore(db_url)  # fresh engine
    ok2, _ = s2.verify_audit()
    r.check("audit chain detects tampering", not ok2,
            detail="verify_audit returned ok=True after a tampered row")

    # Restore for subsequent checks (just nuke and re-seed minimally)
    db_path.unlink()
    s = SqlStore(db_url)
    s.save_template(_seed_medical(), actor="doctor")
    s.save_questionnaire(Questionnaire(
        id="doctor-q1", template_id="tpl_medical", template_version=1,
        created_at=now(), respondent_id="alice",
        answers={
            "has_allergies": BooleanAnswer(value=True),
            "allergy_details": FreeTextAnswer(value="seeds"),
            "contact_method": SingleSelectAnswer(value="Email"),
            "date_of_birth": DateAnswer(value="1991-11-13"),
            "age": NumberAnswer(value=33),
            "symptoms": MultiSelectAnswer(value=["Fever", "Headache"]),
            "fever_duration": FreeTextAnswer(value="2 days"),
        },
    ), actor="doctor")
    s.submit_questionnaire("doctor-q1", actor="doctor")

    # 9. CSV export (use the same code path as `qst export`)
    from ..domain.flow import resolve_active_questions
    csv_rows = []
    for qn_streamed in s.stream_query_for_export([]):
        tpl = s.get_template(qn_streamed.template_id, qn_streamed.template_version)
        active = resolve_active_questions(tpl.questions, qn_streamed.answers)
        csv_rows.append({q.id: qn_streamed.answers.get(q.id) for q in active})
    r.check("CSV stream produced 1 row with PII present", len(csv_rows) == 1
            and csv_rows[0].get("allergy_details") is not None)

    # 10. GDPR export + delete
    blob = s.respondent_export("alice")
    with zipfile.ZipFile(BytesIO(blob)) as zf:
        names = zf.namelist()
    r.check("GDPR export contains manifest + per-questionnaire JSON",
            "manifest.json" in names
            and any(n.startswith("questionnaires/") for n in names))
    n = s.respondent_delete("alice", actor="doctor")
    r.check("GDPR delete removes 1 questionnaire", n == 1)
    audit_tail = s.list_audit()[-1]
    r.check("GDPR delete logged in audit", audit_tail.event.action == "gdpr.delete")

    return db_url


# --- HTTP probe ---------------------------------------------------------

def _check_http_workflow(r: _Runner, db_dir: Path) -> None:
    port = _free_port()
    db_path = db_dir / "doctor_api.sqlite"
    env = dict(os.environ)
    # Force the API process to use a fresh DB and a stable PII key path
    # under our temp dir.
    env["QST_DB_URL"] = f"sqlite:///{db_path}"  # not yet honored, but ready for it
    env.pop("QST_DB_URL", None)  # keep the default; we'll probe defaults too

    # Use the default db.sqlite path; the API server will create it.
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "questionnaire.api.app:app",
         "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"],
        cwd=str(db_dir.parent),  # share the parent's data/
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=env,
    )
    try:
        if not _wait_port("127.0.0.1", port, timeout=10.0):
            r.check("API server boots", False, detail="port never opened")
            return
        r.check("API server boots", True)

        base = f"http://127.0.0.1:{port}"

        status, _ = _request("GET", f"{base}/docs")
        r.check("/docs returns 200", status == 200)

        body = {
            "title": "Doctor smoke",
            "questions": [
                {"id": "doc_color", "type": "single_select",
                 "prompt": "Color?", "options": ["red", "green", "blue"]},
                {"id": "doc_notes", "type": "free_text", "prompt": "Why?"},
            ],
        }
        status, payload = _request("POST", f"{base}/templates", data=body,
                                   headers={"X-Actor": "doctor"})
        r.check("POST /templates 201", status == 201)
        tid = json.loads(payload)["id"]

        status, payload = _request("POST", f"{base}/questionnaires",
                                   data={"template_id": tid, "respondent_id": "doc_user"})
        r.check("POST /questionnaires 201", status == 201)
        qid = json.loads(payload)["id"]

        status, _ = _request("PUT",
            f"{base}/questionnaires/{qid}/answers/doc_color",
            data={"answer": {"type": "single_select", "value": "red"}})
        r.check("PUT answer 200", status == 200)

        status, _ = _request("PUT",
            f"{base}/questionnaires/{qid}/answers/doc_notes",
            data={"answer": {"type": "free_text", "value": "because"}})
        r.check("PUT answer 200 (free-text)", status == 200)

        status, payload = _request("POST",
            f"{base}/questionnaires/{qid}/submit", data={})
        r.check("POST submit 200", status == 200
                and json.loads(payload).get("submitted_at"))

        status, _ = _request("PUT",
            f"{base}/questionnaires/{qid}/answers/doc_color",
            data={"answer": {"type": "single_select", "value": "blue"}})
        r.check("PUT after submit returns 409", status == 409)

        status, payload = _request("GET",
            f"{base}/questionnaires?includes=doc_color%3Dred")
        rows = json.loads(payload)
        r.check("filter via API returns 1", isinstance(rows, list) and len(rows) == 1)

        status, _ = _request("GET",
            f"{base}/questionnaires?includes=doc_notes%3Dhi")
        r.check("bad filter (free-text) returns 400", status == 400)

        status, payload = _request("POST", f"{base}/audit/verify", data={})
        r.check("audit/verify returns ok=true",
                status == 200 and json.loads(payload).get("ok") is True)

        status, payload = _request("GET", f"{base}/respondents/doc_user/export")
        r.check("GDPR zip non-empty", status == 200 and len(payload) > 100)

        status, payload = _request("DELETE", f"{base}/respondents/doc_user")
        body = json.loads(payload) if payload else {}
        r.check("GDPR delete returns count >= 1",
                status == 200 and body.get("deleted_questionnaires", 0) >= 1)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


# --- Migration probe ----------------------------------------------------

def _check_migration(r: _Runner, db_dir: Path) -> None:
    from ..domain.types import (
        BooleanQuestion, Database, FreeTextQuestion, Template,
    )
    from ..persistence.store import JsonStore
    from ..persistence.sql_store import SqlStore
    from ..persistence.migrate import migrate_json_to_sql

    json_path = db_dir / "legacy.json"
    sql_path = db_dir / "migrated.sqlite"
    JsonStore(json_path).save(Database(
        templates={
            "doc_legacy": Template(
                id="doc_legacy", title="Legacy", created_at="2026-01-01T00:00:00Z",
                questions=[BooleanQuestion(id="b", prompt="?")],
            ),
        },
    ))
    s = SqlStore(f"sqlite:///{sql_path}")
    res = migrate_json_to_sql(JsonStore(json_path), s)
    r.check("JSON→SQLite migration: 1 template moved",
            res.templates_migrated == 1)
    r.check("legacy JSON file kept on disk", json_path.exists())


# --- Analytics probe (only if extras installed) -------------------------

def _check_analytics_optional(r: _Runner) -> None:
    try:
        from ..analytics.embeddings import embed_text
        from ..analytics.clustering import cluster_freetext
    except Exception as e:
        typer.echo(f"  ~ analytics extra not installed; skipping clustering check ({e})")
        return
    sample = [
        ("a", "I love hiking in the mountains"),
        ("b", "Hiking trails are beautiful"),
        ("c", "Mountain trekking is amazing"),
        ("d", "Best pizza in town"),
        ("e", "Pizza place was great"),
        ("f", "I enjoyed the local pizza"),
    ]
    clusters = cluster_freetext(sample, min_cluster_size=2)
    r.check("clustering returns >= 1 group", len(clusters) >= 1)
    r.check("clustering produces an exemplar string",
            all(isinstance(c.exemplar_text, str) and c.exemplar_text for c in clusters))


# --- Entry --------------------------------------------------------------

@app.callback(invoke_without_command=True)
def doctor(
    ctx: typer.Context,
    keep: bool = typer.Option(False, "--keep",
                              help="Don't clean the temp working directory on exit"),
):
    """Run the full self-test. Exits 0 on PASS, 1 on FAIL."""
    if ctx.invoked_subcommand is not None:
        return

    typer.echo("# qst doctor: end-to-end self-test")
    typer.echo()

    work = Path(tempfile.mkdtemp(prefix="qst_doctor_"))
    data_dir = work / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    # Make the API subprocess look at this temp dir's data/ — it uses cwd.
    cwd_was = os.getcwd()
    os.chdir(work)
    try:
        r = _Runner()

        typer.echo("## CLI workflow")
        _check_cli_workflow(r, data_dir)
        typer.echo()

        typer.echo("## migration")
        _check_migration(r, data_dir)
        typer.echo()

        typer.echo("## HTTP API")
        _check_http_workflow(r, data_dir)
        typer.echo()

        typer.echo("## analytics extra (skipped if not installed)")
        _check_analytics_optional(r)
        typer.echo()

        typer.echo("=" * 50)
        rc = r.summary()
        if rc != 0:
            raise typer.Exit(code=rc)
        typer.echo("ALL GREEN.")
    finally:
        os.chdir(cwd_was)
        if not keep:
            shutil.rmtree(work, ignore_errors=True)
        else:
            typer.echo(f"\n  (kept temp dir: {work})")
