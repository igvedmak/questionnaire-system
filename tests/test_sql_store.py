"""SQLite store: CRUD round-trip, versioning, immutability after submit,
push-down filtering, audit log integration, GDPR delete/export."""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from questionnaire.domain import encryption
from questionnaire.domain.filtering import (
    ExcludesFilter,
    IncludesFilter,
    TemplateFilter,
)
from questionnaire.domain.types import (
    BoolFollowUp,
    BooleanAnswer,
    BooleanQuestion,
    FreeTextAnswer,
    FreeTextQuestion,
    MultiSelectAnswer,
    MultiSelectQuestion,
    NumberAnswer,
    NumberQuestion,
    Questionnaire,
    SingleSelectAnswer,
    SingleSelectQuestion,
    Template,
)
from questionnaire.persistence.sql_store import SqlStore, SubmissionLockedError


@pytest.fixture
def store(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("QST_PII_KEY", Fernet.generate_key().decode())
    encryption.reset_key_cache()
    return SqlStore(f"sqlite:///{tmp_path / 'db.sqlite'}")


def _tpl(*qs, id="t1", title="T") -> Template:
    return Template(id=id, title=title, created_at="2026-01-01T00:00:00Z", questions=list(qs))


# --- Templates ----------------------------------------------------------

def test_save_template_starts_at_v1(store):
    t = _tpl(BooleanQuestion(id="b", prompt="?"))
    saved = store.save_template(t)
    assert saved.version == 1


def test_resaving_same_id_bumps_version(store):
    t = _tpl(BooleanQuestion(id="b", prompt="?"))
    store.save_template(t)
    saved2 = store.save_template(t)
    assert saved2.version == 2
    assert store.list_template_versions(t.id) == [1, 2]


def test_get_template_returns_current_version_by_default(store):
    t = _tpl(BooleanQuestion(id="b", prompt="?"))
    store.save_template(t)
    store.save_template(_tpl(BooleanQuestion(id="b", prompt="updated"), id=t.id))
    cur = store.get_template(t.id)
    assert cur is not None and cur.version == 2
    assert cur.questions[0].prompt == "updated"


def test_get_template_specific_version(store):
    t = _tpl(BooleanQuestion(id="b", prompt="v1"))
    store.save_template(t)
    store.save_template(_tpl(BooleanQuestion(id="b", prompt="v2"), id=t.id))
    v1 = store.get_template(t.id, version=1)
    assert v1 is not None and v1.questions[0].prompt == "v1"


# --- Questionnaires & answers ------------------------------------------

def test_full_round_trip(store):
    t = _tpl(
        BooleanQuestion(
            id="b",
            prompt="?",
            follow_ups=[BoolFollowUp(
                when_equals=True,
                questions=[FreeTextQuestion(id="b_yes", prompt="?")],
            )],
        ),
        SingleSelectQuestion(id="s", prompt="?", options=["a", "b", "c"]),
        MultiSelectQuestion(id="m", prompt="?", options=["x", "y", "z"]),
        NumberQuestion(id="n", prompt="?", min=0, max=100),
    )
    store.save_template(t)
    qn = Questionnaire(
        id="q1", template_id=t.id, template_version=1,
        created_at="2026-01-02T00:00:00Z",
        answers={
            "b": BooleanAnswer(value=True),
            "b_yes": FreeTextAnswer(value="hi"),
            "s": SingleSelectAnswer(value="b"),
            "m": MultiSelectAnswer(value=["x", "z"]),
            "n": NumberAnswer(value=42.5),
        },
    )
    store.save_questionnaire(qn)
    loaded = store.get_questionnaire("q1")
    assert loaded == qn


def test_pii_freetext_is_encrypted_at_rest(store):
    t = _tpl(FreeTextQuestion(id="ssn", prompt="SSN", pii=True))
    store.save_template(t)
    qn = Questionnaire(
        id="q1", template_id=t.id, template_version=1,
        created_at="2026-01-02T00:00:00Z",
        answers={"ssn": FreeTextAnswer(value="123-45-6789")},
    )
    store.save_questionnaire(qn)

    # Read via the store: decrypted transparently.
    loaded = store.get_questionnaire("q1")
    assert loaded.answers["ssn"].value == "123-45-6789"

    # Bypass: read raw via SQLAlchemy. The plaintext must NOT be in value_text.
    from sqlalchemy import select

    from questionnaire.persistence.models import AnswerRow

    with store.session() as s:
        row = s.execute(select(AnswerRow).where(AnswerRow.question_id == "ssn")).scalar_one()
        assert row.value_text is None
        assert row.is_pii is True
        assert row.value_blob is not None
        assert b"123-45-6789" not in row.value_blob  # ciphertext


def test_submission_immutability(store):
    t = _tpl(BooleanQuestion(id="b", prompt="?"))
    store.save_template(t)
    qn = Questionnaire(
        id="q1", template_id=t.id, template_version=1,
        created_at="2026-01-02T00:00:00Z",
        answers={"b": BooleanAnswer(value=True)},
    )
    store.save_questionnaire(qn)
    store.submit_questionnaire("q1")

    with pytest.raises(SubmissionLockedError):
        store.upsert_answer("q1", "b", BooleanAnswer(value=False))
    with pytest.raises(SubmissionLockedError):
        store.delete_answer("q1", "b")
    with pytest.raises(SubmissionLockedError):
        store.submit_questionnaire("q1")


# --- Filter pushdown -----------------------------------------------------

def _seed_filter_data(store: SqlStore) -> None:
    t1 = _tpl(
        SingleSelectQuestion(id="color", prompt="?", options=["red", "green", "blue"]),
        MultiSelectQuestion(id="tags", prompt="?", options=["a", "b", "c", "d"]),
        FreeTextQuestion(id="notes", prompt="?"),
        id="t1", title="T1",
    )
    store.save_template(t1)
    samples = [
        ("a", "t1", {"color": SingleSelectAnswer(value="red"),
                      "tags": MultiSelectAnswer(value=["a", "b"])}),
        ("b", "t1", {"color": SingleSelectAnswer(value="red"),
                      "tags": MultiSelectAnswer(value=["c", "d"])}),
        ("c", "t1", {"color": SingleSelectAnswer(value="green"),
                      "tags": MultiSelectAnswer(value=["a"])}),
    ]
    for qid, tid, ans in samples:
        store.save_questionnaire(Questionnaire(
            id=qid, template_id=tid, template_version=1,
            created_at="2026-01-02T00:00:00Z",
            answers=ans,
        ))
        store.submit_questionnaire(qid)


def test_template_filter(store):
    _seed_filter_data(store)
    out = store.query_questionnaires([TemplateFilter(template_id="t1")])
    assert sorted(q.id for q in out) == ["a", "b", "c"]


def test_includes_single_select(store):
    _seed_filter_data(store)
    out = store.query_questionnaires([IncludesFilter(question_id="color", value="red")])
    assert sorted(q.id for q in out) == ["a", "b"]


def test_includes_multi_select_picks_any_member(store):
    _seed_filter_data(store)
    out = store.query_questionnaires([IncludesFilter(question_id="tags", value="a")])
    assert sorted(q.id for q in out) == ["a", "c"]


def test_excludes_negates(store):
    _seed_filter_data(store)
    out = store.query_questionnaires([ExcludesFilter(question_id="color", value="red")])
    assert [q.id for q in out] == ["c"]


def test_and_combination(store):
    _seed_filter_data(store)
    out = store.query_questionnaires([
        TemplateFilter(template_id="t1"),
        IncludesFilter(question_id="color", value="red"),
        ExcludesFilter(question_id="tags", value="d"),
    ])
    assert [q.id for q in out] == ["a"]


def test_drafts_excluded_by_default(store):
    _seed_filter_data(store)
    # Add an unsubmitted one.
    store.save_questionnaire(Questionnaire(
        id="draft1", template_id="t1", template_version=1,
        created_at="2026-01-02T00:00:00Z",
        answers={"color": SingleSelectAnswer(value="red")},
    ))
    out_default = store.query_questionnaires([])
    out_with_drafts = store.query_questionnaires([], include_drafts=True)
    assert "draft1" not in {q.id for q in out_default}
    assert "draft1" in {q.id for q in out_with_drafts}


# --- Audit log integration ----------------------------------------------

def test_each_state_change_emits_an_audit_row(store):
    t = _tpl(BooleanQuestion(id="b", prompt="?"))
    store.save_template(t)
    qn = Questionnaire(
        id="q1", template_id=t.id, template_version=1,
        created_at="2026-01-02T00:00:00Z",
    )
    store.save_questionnaire(qn)
    store.upsert_answer("q1", "b", BooleanAnswer(value=True))
    store.submit_questionnaire("q1")

    rows = store.list_audit()
    actions = [r.event.action for r in rows]
    assert "template.save" in actions
    assert "questionnaire.save" in actions
    assert "answer.upsert" in actions
    assert "questionnaire.submit" in actions

    ok, err = store.verify_audit()
    assert ok, err


# --- GDPR ----------------------------------------------------------------

def test_respondent_export_zip_contains_all_their_questionnaires(store):
    t = _tpl(BooleanQuestion(id="b", prompt="?"))
    store.save_template(t)
    for i in range(3):
        store.save_questionnaire(Questionnaire(
            id=f"q{i}", template_id=t.id, template_version=1,
            created_at="2026-01-02T00:00:00Z",
            respondent_id="alice",
            answers={"b": BooleanAnswer(value=bool(i % 2))},
        ))
    blob = store.respondent_export("alice")
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        names = sorted(zf.namelist())
        assert "manifest.json" in names
        assert sum(1 for n in names if n.startswith("questionnaires/")) == 3
        manifest = json.loads(zf.read("manifest.json"))
        assert manifest["respondent_id"] == "alice"
        assert len(manifest["questionnaires"]) == 3


def test_respondent_delete_removes_all_their_data(store):
    t = _tpl(BooleanQuestion(id="b", prompt="?"))
    store.save_template(t)
    for i in range(2):
        store.save_questionnaire(Questionnaire(
            id=f"q{i}", template_id=t.id, template_version=1,
            created_at="2026-01-02T00:00:00Z",
            respondent_id="bob",
            answers={"b": BooleanAnswer(value=True)},
        ))
    n = store.respondent_delete("bob")
    assert n == 2
    # Audit log records the deletion.
    last = store.list_audit()[-1]
    assert last.event.action == "gdpr.delete"
    assert last.event.payload["deleted_questionnaire_count"] == 2
    # No questionnaires for bob remain.
    assert store.get_questionnaire("q0") is None
