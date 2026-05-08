"""JSON → SQLite migration: data-fidelity round-trip + submitted-state preserved."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from questionnaire.domain import encryption
from questionnaire.domain.types import (
    BoolFollowUp,
    BooleanAnswer,
    BooleanQuestion,
    Database,
    FreeTextAnswer,
    FreeTextQuestion,
    Questionnaire,
    Template,
)
from questionnaire.persistence.migrate import migrate_json_to_sql
from questionnaire.persistence.sql_store import SqlStore
from questionnaire.persistence.store import JsonStore


@pytest.fixture(autouse=True)
def fresh_key(monkeypatch):
    monkeypatch.setenv("QST_PII_KEY", Fernet.generate_key().decode())
    encryption.reset_key_cache()
    yield


def _build_legacy_db() -> Database:
    tpl = Template(
        id="tpl1",
        title="legacy",
        created_at="2026-01-01T00:00:00Z",
        questions=[
            BooleanQuestion(
                id="b",
                prompt="?",
                follow_ups=[BoolFollowUp(
                    when_equals=True,
                    questions=[FreeTextQuestion(id="b_yes", prompt="?")],
                )],
            ),
        ],
    )
    qn1 = Questionnaire(  # submitted
        id="qn_submitted",
        template_id="tpl1",
        created_at="2026-01-02T00:00:00Z",
        submitted_at="2026-01-02T01:00:00Z",
        answers={
            "b": BooleanAnswer(value=True),
            "b_yes": FreeTextAnswer(value="hello"),
        },
    )
    qn2 = Questionnaire(  # draft
        id="qn_draft",
        template_id="tpl1",
        created_at="2026-01-03T00:00:00Z",
        answers={"b": BooleanAnswer(value=False)},
    )
    return Database(templates={tpl.id: tpl}, questionnaires={qn1.id: qn1, qn2.id: qn2})


def test_migration_preserves_template_questionnaires_and_submission_state(tmp_path: Path):
    json_path = tmp_path / "legacy.json"
    js = JsonStore(json_path)
    js.save(_build_legacy_db())

    sql = SqlStore(f"sqlite:///{tmp_path / 'new.sqlite'}")
    result = migrate_json_to_sql(js, sql)

    assert result.templates_migrated == 1
    assert result.questionnaires_migrated == 2
    assert result.questionnaires_submitted == 1

    # Templates moved.
    cur = sql.get_template("tpl1")
    assert cur is not None and cur.title == "legacy"

    # Submitted questionnaire still submitted.
    qn1 = sql.get_questionnaire("qn_submitted")
    assert qn1 is not None and qn1.is_submitted
    assert qn1.answers["b"].value is True
    assert qn1.answers["b_yes"].value == "hello"

    # Draft still draft.
    qn2 = sql.get_questionnaire("qn_draft")
    assert qn2 is not None and not qn2.is_submitted

    # Original JSON file is intact.
    assert json_path.exists()
