"""`qst doctor` — end-to-end self-test.

60+ checks across every feature surface. Exits 0 on full green, 1 on any
failure. Sections run in order; failures accumulate (no early abort) so
you see the full picture in one pass.

Sections
--------
1.  Core question types    — all 6 types, per-type validation constraints
2.  Expression engine      — ExprFollowUp, all operators, SQL-NULL semantics
3.  Filter combinators     — AND / OR / NOT in-memory and SQL pushdown
4.  Submission lifecycle   — create, upsert, delete, re-add, submit, lock
5.  Audit & security       — hash-chain integrity, tamper detection, PII
6.  GDPR                   — export zip, hard delete, audit trail
7.  Template versioning    — v1 create, bump, questionnaire snapshot
8.  Validation errors      — template errors, answer errors, submit gate
9.  Migration              — JSON → SQLite fidelity
10. HTTP API               — all endpoints, success + error paths
11. Analytics (optional)   — HDBSCAN clustering
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


# ---------------------------------------------------------------------------
# Tiny test-runner
# ---------------------------------------------------------------------------

class _Runner:
    """Accumulates PASS/FAIL without aborting on first failure."""

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


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def _request(method: str, url: str, *, data=None, headers=None):
    req = urllib.request.Request(url, method=method, headers=headers or {})
    if data is not None:
        req.add_header("Content-Type", "application/json")
        body = json.dumps(data).encode()
    else:
        body = None
    try:
        with urllib.request.urlopen(req, data=body, timeout=10) as resp:
            return resp.status, resp.read()
    except HTTPError as e:
        return e.code, e.read()


def _wait_port(host: str, port: int, *, timeout: float = 10.0) -> bool:
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


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


# ---------------------------------------------------------------------------
# Section 1: Core question types
# ---------------------------------------------------------------------------

def _check_core_types(r: _Runner, db_dir: Path) -> None:
    from ..domain.types import (
        BooleanAnswer, BooleanQuestion,
        DateAnswer, DateQuestion,
        FreeTextAnswer, FreeTextQuestion,
        MultiSelectAnswer, MultiSelectQuestion,
        NumberAnswer, NumberQuestion,
        Questionnaire, SingleSelectAnswer, SingleSelectQuestion,
        Template,
    )
    from ..domain.validation import validate_answers, validate_for_submission, validate_template
    from ..persistence.sql_store import SqlStore

    s = SqlStore(f"sqlite:///{db_dir / 'types.sqlite'}")
    tpl = Template(
        id="t_types", title="All Types", created_at=_now(),
        questions=[
            BooleanQuestion(id="b", prompt="?"),
            SingleSelectQuestion(id="ss", prompt="?", options=["A", "B", "C"]),
            MultiSelectQuestion(id="ms", prompt="?", options=["X", "Y", "Z"]),
            DateQuestion(id="d", prompt="?"),
            FreeTextQuestion(id="ft", prompt="?"),
            NumberQuestion(id="n", prompt="?", min=0, max=100, integer=True),
        ],
    )
    vr = validate_template(tpl)
    r.check("validate_template: valid template passes", vr.ok, detail=str(vr.errors))
    s.save_template(tpl)

    # Boolean
    r.check("boolean True accepted",
            validate_answers(tpl, {"b": BooleanAnswer(value=True)}).ok)
    r.check("boolean False accepted",
            validate_answers(tpl, {"b": BooleanAnswer(value=False)}).ok)

    # SingleSelect
    r.check("single_select: valid option accepted",
            validate_answers(tpl, {"ss": SingleSelectAnswer(value="A")}).ok)
    res = validate_answers(tpl, {"ss": SingleSelectAnswer(value="Z")})
    r.check("single_select: invalid option rejected",
            not res.ok and any("not one of" in str(e) for e in res.errors))

    # MultiSelect
    r.check("multi_select: multiple values accepted",
            validate_answers(tpl, {"ms": MultiSelectAnswer(value=["X", "Y"])}).ok)
    res = validate_answers(tpl, {"ms": MultiSelectAnswer(value=[])})
    r.check("multi_select: empty selection rejected",
            not res.ok and any("at least one" in str(e) for e in res.errors))
    res = validate_answers(tpl, {"ms": MultiSelectAnswer(value=["X", "X"])})
    r.check("multi_select: duplicate selections rejected",
            not res.ok and any("duplicate" in str(e) for e in res.errors))

    # Date
    r.check("date: valid YYYY-MM-DD accepted",
            validate_answers(tpl, {"d": DateAnswer(value="2026-05-08")}).ok)
    res = validate_answers(tpl, {"d": DateAnswer(value="not-a-date")})
    r.check("date: invalid format rejected",
            not res.ok and any("YYYY-MM-DD" in str(e) for e in res.errors))
    res = validate_answers(tpl, {"d": DateAnswer(value="2024-02-30")})
    r.check("date: impossible calendar date rejected", not res.ok)

    # FreeText
    r.check("free_text: any string accepted",
            validate_answers(tpl, {"ft": FreeTextAnswer(value="hello world")}).ok)

    # Number
    r.check("number: in-range integer accepted",
            validate_answers(tpl, {"n": NumberAnswer(value=42.0)}).ok)
    res = validate_answers(tpl, {"n": NumberAnswer(value=3.5)})
    r.check("number: non-integer rejected when integer=True",
            not res.ok and any("integer" in str(e) for e in res.errors))
    res = validate_answers(tpl, {"n": NumberAnswer(value=-1.0)})
    r.check("number: below-min rejected",
            not res.ok and any("below min" in str(e) for e in res.errors))
    res = validate_answers(tpl, {"n": NumberAnswer(value=101.0)})
    r.check("number: above-max rejected",
            not res.ok and any("above max" in str(e) for e in res.errors))

    # Full round-trip
    full = {
        "b": BooleanAnswer(value=True),
        "ss": SingleSelectAnswer(value="B"),
        "ms": MultiSelectAnswer(value=["X", "Z"]),
        "d": DateAnswer(value="2026-01-15"),
        "ft": FreeTextAnswer(value="round-trip"),
        "n": NumberAnswer(value=42.0),
    }
    vr = validate_for_submission(tpl, full)
    r.check("validate_for_submission: all 6 types passes", vr.ok, detail=str(vr.errors))

    qn = Questionnaire(id="q_types", template_id="t_types",
                       template_version=1, created_at=_now(), answers=full)
    s.save_questionnaire(qn)
    s.submit_questionnaire("q_types")
    loaded = s.get_questionnaire("q_types")
    r.check("all 6 types round-trip through store",
            loaded is not None
            and len(loaded.answers) == 6
            and loaded.answers["n"].value == 42.0
            and loaded.answers["ms"].value == ["X", "Z"])

    vr = validate_for_submission(tpl, {"b": BooleanAnswer(value=True)})
    r.check("validate_for_submission: missing answers fails", not vr.ok)


# ---------------------------------------------------------------------------
# Section 2: Expression engine
# ---------------------------------------------------------------------------

def _check_expression_engine(r: _Runner) -> None:
    from ..domain.expression import (
        AndExpr, ContainsExpr, EqExpr, GtExpr, LitExpr,
        NotExpr, OrExpr, VarExpr, evaluate,
    )
    from ..domain.flow import resolve_active_questions
    from ..domain.types import (
        ExprFollowUp, FreeTextQuestion,
        MultiSelectAnswer, MultiSelectQuestion,
        NumberAnswer, NumberQuestion, Template,
    )

    a = {
        "score": NumberAnswer(value=80),
        "tags": MultiSelectAnswer(value=["python", "backend"]),
    }

    r.check("EqExpr: fires on matching value",
            evaluate(EqExpr(left=VarExpr(question_id="score"),
                            right=LitExpr(value=80)), a) is True)
    r.check("EqExpr: silent on non-matching value",
            evaluate(EqExpr(left=VarExpr(question_id="score"),
                            right=LitExpr(value=99)), a) is False)

    r.check("GtExpr: fires when value > threshold",
            evaluate(GtExpr(left=VarExpr(question_id="score"),
                            right=LitExpr(value=50)), a) is True)
    r.check("GtExpr: silent when value <= threshold",
            evaluate(GtExpr(left=VarExpr(question_id="score"),
                            right=LitExpr(value=100)), a) is False)

    r.check("AndExpr: fires when all operands true",
            evaluate(AndExpr(operands=[
                GtExpr(left=VarExpr(question_id="score"), right=LitExpr(value=50)),
                GtExpr(left=VarExpr(question_id="score"), right=LitExpr(value=70)),
            ]), a) is True)
    r.check("AndExpr: silent when one operand fails",
            evaluate(AndExpr(operands=[
                GtExpr(left=VarExpr(question_id="score"), right=LitExpr(value=50)),
                GtExpr(left=VarExpr(question_id="score"), right=LitExpr(value=90)),
            ]), a) is False)

    r.check("OrExpr: fires when at least one operand true",
            evaluate(OrExpr(operands=[
                GtExpr(left=VarExpr(question_id="score"), right=LitExpr(value=90)),
                GtExpr(left=VarExpr(question_id="score"), right=LitExpr(value=50)),
            ]), a) is True)

    r.check("NotExpr: fires when inner is false",
            evaluate(NotExpr(operand=GtExpr(
                left=VarExpr(question_id="score"), right=LitExpr(value=100),
            )), a) is True)

    r.check("ContainsExpr: fires when multi-select contains needle",
            evaluate(ContainsExpr(
                haystack=VarExpr(question_id="tags"), needle=LitExpr(value="python"),
            ), a) is True)
    r.check("ContainsExpr: silent when needle absent",
            evaluate(ContainsExpr(
                haystack=VarExpr(question_id="tags"), needle=LitExpr(value="java"),
            ), a) is False)

    # SQL-NULL missing-value semantics
    r.check("MISSING var: EqExpr returns False (no crash)",
            evaluate(EqExpr(left=VarExpr(question_id="nope"),
                            right=LitExpr(value="x")), a) is False)
    r.check("NOT(MISSING comparison) returns True",
            evaluate(NotExpr(operand=EqExpr(
                left=VarExpr(question_id="nope"), right=LitExpr(value="x"),
            )), a) is True)
    r.check("type-mismatch compare returns False (no crash)",
            evaluate(GtExpr(left=VarExpr(question_id="score"),
                            right=LitExpr(value="string")), a) is False)

    # End-to-end via resolve_active_questions
    tpl = Template(
        id="t_expr", title="Expr", created_at=_now(),
        questions=[
            NumberQuestion(id="sc2", prompt="?", follow_ups=[
                ExprFollowUp(
                    condition=GtExpr(left=VarExpr(question_id="sc2"),
                                     right=LitExpr(value=50)),
                    questions=[FreeTextQuestion(id="bonus", prompt="?")],
                ),
            ]),
            MultiSelectQuestion(id="techs", prompt="?",
                                options=["py", "go", "js"], follow_ups=[
                ExprFollowUp(
                    condition=ContainsExpr(haystack=VarExpr(question_id="techs"),
                                          needle=LitExpr(value="py")),
                    questions=[FreeTextQuestion(id="py_detail", prompt="?")],
                ),
            ]),
        ],
    )
    high = {"sc2": NumberAnswer(value=80), "techs": MultiSelectAnswer(value=["py", "go"])}
    active_high = {q.id for q in resolve_active_questions(tpl.questions, high)}
    r.check("ExprFollowUp (Gt): follow-up activates when score > 50",
            "bonus" in active_high)
    r.check("ContainsExpr follow-up activates when needle present",
            "py_detail" in active_high)

    low = {"sc2": NumberAnswer(value=20), "techs": MultiSelectAnswer(value=["go"])}
    active_low = {q.id for q in resolve_active_questions(tpl.questions, low)}
    r.check("ExprFollowUp (Gt): follow-up deactivates when score <= 50",
            "bonus" not in active_low)
    r.check("ContainsExpr follow-up deactivates when needle absent",
            "py_detail" not in active_low)


# ---------------------------------------------------------------------------
# Section 3: Filter combinators
# ---------------------------------------------------------------------------

def _check_filter_combinators(r: _Runner, db_dir: Path) -> None:
    from ..domain.filtering import (
        ExcludesFilter, IncludesFilter, NotFilter, OrFilter, TemplateFilter,
        apply_filters,
    )
    from ..domain.types import (
        MultiSelectAnswer, MultiSelectQuestion,
        Questionnaire, SingleSelectAnswer, SingleSelectQuestion,
        Template,
    )
    from ..persistence.sql_store import SqlStore

    def _qn(qid, tid, answers):
        return Questionnaire(id=qid, template_id=tid, created_at=_now(),
                             submitted_at=_now(), answers=answers)

    qns = [
        _qn("fa", "t1", {"color": SingleSelectAnswer(value="red")}),
        _qn("fb", "t1", {"color": SingleSelectAnswer(value="blue")}),
        _qn("fc", "t2", {"color": SingleSelectAnswer(value="red")}),
    ]

    # In-memory tests
    out = apply_filters(qns, [TemplateFilter("t1"), IncludesFilter("color", "red")])
    r.check("AND(template+includes) in-memory: narrows correctly",
            [q.id for q in out] == ["fa"])

    out = apply_filters(qns, [TemplateFilter("t1"), ExcludesFilter("color", "red")])
    r.check("AND(template+excludes) in-memory: correct negation",
            [q.id for q in out] == ["fb"])

    out = apply_filters(qns, [OrFilter(filters=[
        IncludesFilter("color", "red"), IncludesFilter("color", "blue"),
    ])])
    r.check("OrFilter in-memory: matches either branch",
            sorted(q.id for q in out) == ["fa", "fb", "fc"])

    out = apply_filters(qns, [NotFilter(inner=IncludesFilter("color", "red"))])
    r.check("NotFilter in-memory: inverts includes",
            [q.id for q in out] == ["fb"])

    out = apply_filters(qns, [
        TemplateFilter("t1"),
        OrFilter(filters=[IncludesFilter("color", "red"),
                          IncludesFilter("color", "blue")]),
    ])
    r.check("AND(template, OR) in-memory: combined correctly",
            sorted(q.id for q in out) == ["fa", "fb"])

    # SQL pushdown tests
    s = SqlStore(f"sqlite:///{db_dir / 'filters.sqlite'}")
    tpl = Template(id="tfl", title="Filter test", created_at=_now(),
                   questions=[
                       SingleSelectQuestion(id="color", prompt="?",
                                            options=["red", "blue", "green"]),
                   ])
    s.save_template(tpl)

    for qid, color in [("sa", "red"), ("sb", "blue"), ("sc", "red")]:
        qn = Questionnaire(id=qid, template_id="tfl", template_version=1,
                           created_at=_now(), submitted_at=_now(),
                           answers={"color": SingleSelectAnswer(value=color)})
        s.save_questionnaire(qn)

    out = s.query_questionnaires([IncludesFilter("color", "red")])
    r.check("SQL IncludesFilter pushdown",
            sorted(q.id for q in out) == ["sa", "sc"])

    out = s.query_questionnaires([ExcludesFilter("color", "red")])
    r.check("SQL ExcludesFilter pushdown",
            [q.id for q in out] == ["sb"])

    out = s.query_questionnaires([OrFilter(filters=[
        IncludesFilter("color", "red"), IncludesFilter("color", "blue"),
    ])])
    r.check("SQL OrFilter pushdown",
            sorted(q.id for q in out) == ["sa", "sb", "sc"])

    out = s.query_questionnaires([NotFilter(inner=IncludesFilter("color", "red"))])
    r.check("SQL NotFilter pushdown",
            [q.id for q in out] == ["sb"])

    out = s.query_questionnaires([
        TemplateFilter("tfl"),
        OrFilter(filters=[IncludesFilter("color", "red"),
                          IncludesFilter("color", "blue")]),
    ])
    r.check("SQL AND(template, OR) nested pushdown",
            sorted(q.id for q in out) == ["sa", "sb", "sc"])


# ---------------------------------------------------------------------------
# Section 4: Submission lifecycle
# ---------------------------------------------------------------------------

def _check_submission_lifecycle(r: _Runner, db_dir: Path) -> None:
    from ..domain.types import (
        FreeTextAnswer, FreeTextQuestion, Questionnaire,
        SingleSelectAnswer, SingleSelectQuestion, Template,
    )
    from ..persistence.sql_store import SqlStore, SubmissionLockedError

    s = SqlStore(f"sqlite:///{db_dir / 'lifecycle.sqlite'}")
    tpl = Template(id="t_life", title="Lifecycle", created_at=_now(),
                   questions=[
                       SingleSelectQuestion(id="q1", prompt="?",
                                            options=["A", "B", "C"]),
                       FreeTextQuestion(id="q2", prompt="?"),
                   ])
    s.save_template(tpl)

    qn = Questionnaire(id="lf-q1", template_id="t_life", template_version=1,
                       created_at=_now(), answers={})
    s.save_questionnaire(qn)
    loaded = s.get_questionnaire("lf-q1")
    r.check("questionnaire created as draft", not loaded.is_submitted)

    s.upsert_answer("lf-q1", "q1", SingleSelectAnswer(value="A"))
    r.check("upsert_answer: answer stored",
            "q1" in s.get_questionnaire("lf-q1").answers)

    s.delete_answer("lf-q1", "q1")
    r.check("delete_answer: answer removed",
            "q1" not in s.get_questionnaire("lf-q1").answers)

    s.upsert_answer("lf-q1", "q1", SingleSelectAnswer(value="B"))
    s.upsert_answer("lf-q1", "q2", FreeTextAnswer(value="hello"))
    s.submit_questionnaire("lf-q1")
    r.check("submit_questionnaire: submitted_at set",
            s.get_questionnaire("lf-q1").is_submitted)

    def _locked(fn):
        try:
            fn()
            return False
        except SubmissionLockedError:
            return True

    r.check("upsert after submit → SubmissionLockedError",
            _locked(lambda: s.upsert_answer("lf-q1", "q1",
                                            SingleSelectAnswer(value="C"))))
    r.check("delete after submit → SubmissionLockedError",
            _locked(lambda: s.delete_answer("lf-q1", "q1")))
    r.check("double submit → SubmissionLockedError",
            _locked(lambda: s.submit_questionnaire("lf-q1")))


# ---------------------------------------------------------------------------
# Section 5: Audit & security
# ---------------------------------------------------------------------------

def _check_audit_and_security(r: _Runner, db_dir: Path) -> None:
    from ..domain.types import (
        FreeTextAnswer, FreeTextQuestion, Questionnaire, Template,
    )
    from ..persistence.sql_store import SqlStore

    db_path = db_dir / "audit.sqlite"
    s = SqlStore(f"sqlite:///{db_path}")
    tpl = Template(id="t_audit", title="Audit", created_at=_now(),
                   questions=[FreeTextQuestion(id="secret", prompt="?", pii=True)])
    s.save_template(tpl, actor="alice")

    qn = Questionnaire(id="au-q1", template_id="t_audit", template_version=1,
                       created_at=_now(), respondent_id="alice",
                       answers={"secret": FreeTextAnswer(value="my secret")})
    s.save_questionnaire(qn, actor="alice")
    s.submit_questionnaire("au-q1", actor="alice")

    audit = s.list_audit()
    r.check("audit rows emitted per operation", len(audit) >= 3)
    r.check("actor recorded in all audit rows",
            all(row.event.actor == "alice" for row in audit))

    ok, err = s.verify_audit()
    r.check("audit chain verifies OK", ok, detail=err or "")

    # PII raw DB check
    s.engine.dispose()
    with _sqlite.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT value_text, value_blob, is_pii FROM answers "
            "WHERE question_id='secret'"
        ).fetchall()
    r.check("PII row stored with is_pii=1",
            len(rows) == 1 and bool(rows[0][2]))
    r.check("PII value_text is NULL (not plaintext at rest)",
            rows[0][0] is None)
    r.check("PII value_blob is non-empty ciphertext",
            rows[0][1] is not None and len(rows[0][1]) > 0)

    s2 = SqlStore(f"sqlite:///{db_path}")
    loaded = s2.get_questionnaire("au-q1")
    r.check("PII decrypted transparently on read",
            loaded.answers["secret"].value == "my secret")

    # Tamper detection
    s2.engine.dispose()
    with _sqlite.connect(db_path) as conn:
        conn.execute(
            "UPDATE audit_log SET payload_json='{\"hacked\":true}' WHERE seq=1"
        )
        conn.commit()
    ok_t, _ = SqlStore(f"sqlite:///{db_path}").verify_audit()
    r.check("audit chain detects row tampering", not ok_t,
            detail="verify returned ok=True after tampering")


# ---------------------------------------------------------------------------
# Section 6: GDPR
# ---------------------------------------------------------------------------

def _check_gdpr(r: _Runner, db_dir: Path) -> None:
    from ..domain.types import (
        FreeTextAnswer, FreeTextQuestion, Questionnaire, Template,
    )
    from ..persistence.sql_store import SqlStore

    s = SqlStore(f"sqlite:///{db_dir / 'gdpr.sqlite'}")
    tpl = Template(id="t_gdpr", title="GDPR", created_at=_now(),
                   questions=[FreeTextQuestion(id="data", prompt="?")])
    s.save_template(tpl)

    for i in range(2):
        qn = Questionnaire(id=f"gd-q{i}", template_id="t_gdpr", template_version=1,
                           created_at=_now(), respondent_id="bob",
                           answers={"data": FreeTextAnswer(value=f"resp {i}")})
        s.save_questionnaire(qn)
        s.submit_questionnaire(f"gd-q{i}")

    blob = s.respondent_export("bob")
    with zipfile.ZipFile(BytesIO(blob)) as zf:
        names = zf.namelist()
        manifest = json.loads(zf.read("manifest.json"))
    r.check("GDPR export: manifest.json present", "manifest.json" in names)
    r.check("GDPR export: 2 questionnaire JSONs in zip",
            sum(1 for n in names if n.startswith("questionnaires/")) == 2)
    r.check("GDPR export: manifest respondent_id correct",
            manifest.get("respondent_id") == "bob")
    r.check("GDPR export: manifest lists 2 questionnaires",
            len(manifest.get("questionnaires", [])) == 2)

    n = s.respondent_delete("bob", actor="admin")
    r.check("GDPR delete: correct count returned", n == 2)
    r.check("GDPR delete: questionnaires removed from store",
            s.get_questionnaire("gd-q0") is None
            and s.get_questionnaire("gd-q1") is None)
    tail = s.list_audit()[-1]
    r.check("GDPR delete: audit-logged with gdpr.delete",
            tail.event.action == "gdpr.delete")
    r.check("GDPR delete: admin actor in audit",
            tail.event.actor == "admin")


# ---------------------------------------------------------------------------
# Section 7: Template versioning
# ---------------------------------------------------------------------------

def _check_template_versioning(r: _Runner, db_dir: Path) -> None:
    from ..domain.types import (
        BooleanAnswer, BooleanQuestion, Questionnaire, Template,
    )
    from ..persistence.sql_store import SqlStore

    s = SqlStore(f"sqlite:///{db_dir / 'versioning.sqlite'}")
    tpl1 = Template(id="t_ver", title="V1", created_at=_now(),
                    questions=[BooleanQuestion(id="q1", prompt="?")])
    saved1 = s.save_template(tpl1)
    r.check("first save → version 1", saved1.version == 1)

    tpl2 = Template(id="t_ver", title="V2", created_at=_now(),
                    questions=[BooleanQuestion(id="q1", prompt="?"),
                               BooleanQuestion(id="q2", prompt="?")])
    saved2 = s.save_template(tpl2)
    r.check("re-save same id → version 2", saved2.version == 2)

    versions = s.list_template_versions("t_ver")
    r.check("list_template_versions → [1, 2]", versions == [1, 2])

    cur = s.get_template("t_ver")
    r.check("get_template (no version) → current = v2",
            cur is not None and cur.version == 2)

    v1 = s.get_template("t_ver", version=1)
    r.check("get_template(version=1) → only 1 question",
            v1 is not None and len(v1.questions) == 1)

    qn = Questionnaire(id="ver-q1", template_id="t_ver", template_version=1,
                       created_at=_now(),
                       answers={"q1": BooleanAnswer(value=True)})
    s.save_questionnaire(qn)
    s.submit_questionnaire("ver-q1")
    r.check("questionnaire retains its creation-time template_version",
            s.get_questionnaire("ver-q1").template_version == 1)


# ---------------------------------------------------------------------------
# Section 8: Validation errors
# ---------------------------------------------------------------------------

def _check_validation_errors(r: _Runner) -> None:
    from ..domain.types import (
        BoolFollowUp, BooleanAnswer, BooleanQuestion,
        FreeTextAnswer, FreeTextQuestion,
        SelectFollowUp, SingleSelectQuestion, Template,
    )
    from ..domain.validation import validate_answers, validate_for_submission, validate_template

    def _tpl(*qs) -> Template:
        return Template(id="t_err", title="err",
                        created_at=_now(), questions=list(qs))

    res = validate_template(_tpl(
        BooleanQuestion(id="dup", prompt="?"),
        BooleanQuestion(id="dup", prompt="?"),
    ))
    r.check("validate_template: duplicate question ids rejected",
            not res.ok and any("duplicate" in str(e) for e in res.errors))

    res = validate_template(_tpl(
        SingleSelectQuestion(id="ss", prompt="?", options=["A", "B"])
    ))
    r.check("validate_template: single_select ≤ 2 options rejected",
            not res.ok and any("more than 2" in str(e) for e in res.errors))

    res = validate_template(_tpl(
        SingleSelectQuestion(id="ss2", prompt="?", options=["A", "B", "C"],
                             follow_ups=[SelectFollowUp(
                                 when_option_selected="NOPE",
                                 questions=[FreeTextQuestion(id="sub", prompt="?")],
                             )]),
    ))
    r.check("validate_template: follow-up trigger for non-existent option rejected",
            not res.ok and any("not an option" in str(e) for e in res.errors))

    tpl_ok = _tpl(BooleanQuestion(id="b", prompt="?"))
    res = validate_answers(tpl_ok, {"b": FreeTextAnswer(value="oops")})
    r.check("validate_answers: type mismatch rejected",
            not res.ok and any("type mismatch" in str(e) for e in res.errors))

    tpl_orphan = _tpl(BooleanQuestion(
        id="b2", prompt="?",
        follow_ups=[BoolFollowUp(when_equals=True,
                                 questions=[FreeTextQuestion(id="sub2", prompt="?")])],
    ))
    res = validate_answers(tpl_orphan, {
        "b2": BooleanAnswer(value=False),
        "sub2": FreeTextAnswer(value="leftover"),
    })
    r.check("validate_answers: orphaned answer rejected",
            not res.ok and any("inactive" in str(e) for e in res.errors))

    res = validate_for_submission(tpl_ok, {})
    r.check("validate_for_submission: missing required answer fails",
            not res.ok and any("missing" in str(e) for e in res.errors))


# ---------------------------------------------------------------------------
# Section 9: Migration
# ---------------------------------------------------------------------------

def _check_migration(r: _Runner, db_dir: Path) -> None:
    from ..domain.types import BooleanQuestion, Database, Template
    from ..persistence.migrate import migrate_json_to_sql
    from ..persistence.sql_store import SqlStore
    from ..persistence.store import JsonStore

    json_path = db_dir / "legacy.json"
    sql_path = db_dir / "migrated.sqlite"
    JsonStore(json_path).save(Database(
        templates={
            "doc_legacy": Template(
                id="doc_legacy", title="Legacy",
                created_at="2026-01-01T00:00:00Z",
                questions=[BooleanQuestion(id="b", prompt="?")],
            ),
        },
    ))
    s = SqlStore(f"sqlite:///{sql_path}")
    res = migrate_json_to_sql(JsonStore(json_path), s)
    r.check("JSON→SQLite migration: 1 template migrated", res.templates_migrated == 1)
    r.check("migrated template readable from SQL store",
            s.get_template("doc_legacy") is not None)
    r.check("legacy JSON file preserved on disk", json_path.exists())


# ---------------------------------------------------------------------------
# Section 10: HTTP API
# ---------------------------------------------------------------------------

def _check_http_workflow(r: _Runner, db_dir: Path) -> None:
    port = _free_port()
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "questionnaire.api.app:app",
         "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"],
        cwd=str(db_dir.parent),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        if not _wait_port("127.0.0.1", port, timeout=10.0):
            r.check("API server boots", False, detail="port never opened")
            return
        r.check("API server boots", True)

        base = f"http://127.0.0.1:{port}"

        status, _ = _request("GET", f"{base}/docs")
        r.check("/docs → 200", status == 200)

        # --- Templates ---

        six_questions = [
            {"id": "dc_color", "type": "single_select", "prompt": "Color?",
             "options": ["red", "green", "blue"]},
            {"id": "dc_tags",  "type": "multi_select",  "prompt": "Tags?",
             "options": ["frontend", "backend", "devops"]},
            {"id": "dc_notes", "type": "free_text",     "prompt": "Notes?"},
            {"id": "dc_score", "type": "number",         "prompt": "Score?",
             "min": 0, "max": 10},
            {"id": "dc_date",  "type": "date",           "prompt": "Date?"},
            {"id": "dc_ok",    "type": "boolean",        "prompt": "OK?"},
        ]
        status, payload = _request("POST", f"{base}/templates",
                                   data={"title": "Doctor smoke",
                                         "questions": six_questions},
                                   headers={"X-Actor": "doctor"})
        r.check("POST /templates → 201", status == 201)
        tid = json.loads(payload)["id"]

        # invalid template (duplicate ids)
        status, _ = _request("POST", f"{base}/templates", data={
            "title": "Bad",
            "questions": [{"id": "dup", "type": "boolean", "prompt": "?"},
                          {"id": "dup", "type": "boolean", "prompt": "?"}],
        })
        r.check("POST /templates with duplicate ids → 422", status == 422)

        status, _ = _request("GET", f"{base}/templates/does-not-exist")
        r.check("GET /templates/nonexistent → 404", status == 404)

        # Version bump
        status, payload = _request("POST", f"{base}/templates",
                                   data={"id": tid, "title": "Doctor smoke v2",
                                         "questions": six_questions})
        r.check("POST /templates same id → 201 (version bump)", status == 201)
        r.check("POST /templates same id → version 2",
                json.loads(payload)["version"] == 2)

        status, payload = _request("GET", f"{base}/templates/{tid}/versions")
        r.check("GET /templates/{id}/versions → [1, 2]",
                status == 200 and json.loads(payload) == [1, 2])

        status, payload = _request("GET", f"{base}/templates/{tid}?version=1")
        r.check("GET /templates/{id}?version=1 → correct version",
                status == 200 and json.loads(payload)["version"] == 1)

        # --- Questionnaires ---

        status, payload = _request("POST", f"{base}/questionnaires",
                                   data={"template_id": tid,
                                         "respondent_id": "http_user"})
        r.check("POST /questionnaires → 201", status == 201)
        qid = json.loads(payload)["id"]

        status, _ = _request("GET", f"{base}/questionnaires/{qid}")
        r.check("GET /questionnaires/{id} → 200", status == 200)

        status, _ = _request("GET", f"{base}/questionnaires/no-such-id")
        r.check("GET /questionnaires/nonexistent → 404", status == 404)

        status, _ = _request("POST", f"{base}/questionnaires",
                              data={"template_id": "no-template"})
        r.check("POST /questionnaires with unknown template_id → 404", status == 404)

        # --- Answers (upsert, delete, re-add, all 6 types) ---

        status, _ = _request("PUT",
            f"{base}/questionnaires/{qid}/answers/dc_color",
            data={"answer": {"type": "single_select", "value": "red"}})
        r.check("PUT answer (single_select) → 200", status == 200)

        status, payload = _request("DELETE",
            f"{base}/questionnaires/{qid}/answers/dc_color")
        r.check("DELETE answer → 200", status == 200)
        r.check("DELETE answer: removed from response body",
                "dc_color" not in json.loads(payload).get("answers", {}))

        for qkey, ans in [
            ("dc_color", {"type": "single_select",  "value": "red"}),
            ("dc_tags",  {"type": "multi_select",   "value": ["backend", "devops"]}),
            ("dc_notes", {"type": "free_text",      "value": "all good"}),
            ("dc_score", {"type": "number",          "value": 7}),
            ("dc_date",  {"type": "date",            "value": "2026-05-08"}),
            ("dc_ok",    {"type": "boolean",         "value": True}),
        ]:
            status, _ = _request("PUT",
                f"{base}/questionnaires/{qid}/answers/{qkey}",
                data={"answer": ans})
            r.check(f"PUT answer ({qkey}) → 200", status == 200)

        # --- Submit ---

        status, payload = _request("POST",
            f"{base}/questionnaires/{qid}/submit", data={})
        r.check("POST /submit → 200 with submitted_at",
                status == 200 and json.loads(payload).get("submitted_at"))

        status, _ = _request("PUT",
            f"{base}/questionnaires/{qid}/answers/dc_color",
            data={"answer": {"type": "single_select", "value": "blue"}})
        r.check("PUT after submit → 409", status == 409)

        status, _ = _request("DELETE",
            f"{base}/questionnaires/{qid}/answers/dc_color")
        r.check("DELETE after submit → 409", status == 409)

        status, _ = _request("POST",
            f"{base}/questionnaires/{qid}/submit", data={})
        r.check("POST submit again → 409", status == 409)

        # --- Filtering ---

        status, payload = _request("GET",
            f"{base}/questionnaires?includes=dc_color%3Dred")
        r.check("GET ?includes=dc_color=red → 1 result",
                status == 200 and len(json.loads(payload)) == 1)

        status, payload = _request("GET",
            f"{base}/questionnaires?excludes=dc_color%3Dblue")
        r.check("GET ?excludes=dc_color=blue → 1 result",
                status == 200 and len(json.loads(payload)) == 1)

        # draft created, not submitted
        status, payload2 = _request("POST", f"{base}/questionnaires",
                                    data={"template_id": tid})
        qid_draft = json.loads(payload2)["id"]
        status, payload = _request("GET",
            f"{base}/questionnaires?include_drafts=true")
        r.check("GET ?include_drafts=true includes unsubmitted",
                qid_draft in [q["id"] for q in json.loads(payload)])

        status, _ = _request("GET",
            f"{base}/questionnaires?includes=dc_notes%3Dhi")
        r.check("GET filter on free-text question → 400", status == 400)

        # --- CSV export ---

        status, payload = _request("GET", f"{base}/questionnaires.csv")
        r.check("GET /questionnaires.csv → 200", status == 200)
        r.check("GET /questionnaires.csv has correct header",
                payload.decode(errors="replace").startswith("questionnaire_id,"))

        # --- Audit ---

        status, payload = _request("GET", f"{base}/audit")
        entries = json.loads(payload)
        r.check("GET /audit → entries present",
                status == 200 and len(entries) > 0)

        last_seq = entries[-1]["seq"]
        status, payload = _request("GET", f"{base}/audit?since={last_seq}")
        r.check("GET /audit?since=last_seq → empty (no newer entries)",
                status == 200 and json.loads(payload) == [])

        status, payload = _request("POST", f"{base}/audit/verify", data={})
        r.check("POST /audit/verify → ok=true",
                status == 200 and json.loads(payload).get("ok") is True)

        # --- GDPR ---

        status, payload = _request("GET",
            f"{base}/respondents/http_user/export")
        r.check("GET /respondents/{id}/export → 200 zip",
                status == 200 and len(payload) > 100)

        status, payload = _request("DELETE",
            f"{base}/respondents/http_user",
            headers={"X-Actor": "admin"})
        r.check("DELETE /respondents/{id} → deleted_questionnaires >= 1",
                status == 200
                and json.loads(payload).get("deleted_questionnaires", 0) >= 1)

    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


# ---------------------------------------------------------------------------
# Section 11: Analytics (optional)
# ---------------------------------------------------------------------------

def _check_analytics_optional(r: _Runner) -> None:
    try:
        from ..analytics.clustering import cluster_freetext
        from ..analytics.embeddings import embed_text
    except Exception as e:
        typer.echo(f"  ~ analytics extra not installed; skipping ({e})")
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
    r.check("analytics: clustering returns >= 1 cluster", len(clusters) >= 1)
    r.check("analytics: all cluster exemplars are non-empty strings",
            all(isinstance(c.exemplar_text, str) and c.exemplar_text
                for c in clusters))

    vec, dim = embed_text("test embedding")
    r.check("analytics: embed_text returns bytes + positive dimension",
            isinstance(vec, bytes) and dim > 0)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

@app.callback(invoke_without_command=True)
def doctor(
    ctx: typer.Context,
    keep: bool = typer.Option(
        False, "--keep",
        help="Keep the temp working directory after the run",
    ),
):
    """Run the full self-test (60+ checks). Exits 0 on PASS, 1 on FAIL."""
    if ctx.invoked_subcommand is not None:
        return

    typer.echo("# qst doctor: end-to-end self-test")
    typer.echo()

    work = Path(tempfile.mkdtemp(prefix="qst_doctor_"))
    data_dir = work / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    cwd_was = os.getcwd()
    os.chdir(work)
    try:
        r = _Runner()

        typer.echo("## 1. Core question types")
        _check_core_types(r, data_dir)
        typer.echo()

        typer.echo("## 2. Expression engine")
        _check_expression_engine(r)
        typer.echo()

        typer.echo("## 3. Filter combinators (AND / OR / NOT)")
        _check_filter_combinators(r, data_dir)
        typer.echo()

        typer.echo("## 4. Submission lifecycle")
        _check_submission_lifecycle(r, data_dir)
        typer.echo()

        typer.echo("## 5. Audit & security")
        _check_audit_and_security(r, data_dir)
        typer.echo()

        typer.echo("## 6. GDPR")
        _check_gdpr(r, data_dir)
        typer.echo()

        typer.echo("## 7. Template versioning")
        _check_template_versioning(r, data_dir)
        typer.echo()

        typer.echo("## 8. Validation errors")
        _check_validation_errors(r)
        typer.echo()

        typer.echo("## 9. Migration (JSON → SQLite)")
        _check_migration(r, data_dir)
        typer.echo()

        typer.echo("## 10. HTTP API (all endpoints)")
        _check_http_workflow(r, data_dir)
        typer.echo()

        typer.echo("## 11. Analytics (skipped if extra not installed)")
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
