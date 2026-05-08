"""Persistence tests: round-trip and missing-file handling."""

from __future__ import annotations

from pathlib import Path

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
from questionnaire.persistence.store import Store


def test_load_returns_empty_db_when_file_missing(tmp_path: Path):
    store = Store(tmp_path / "does_not_exist.json")
    db = store.load()
    assert db.templates == {}
    assert db.questionnaires == {}


def test_round_trip_preserves_full_database(tmp_path: Path):
    tpl = Template(
        id="t1",
        title="T",
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
    qn = Questionnaire(
        id="q1",
        template_id="t1",
        created_at="2026-01-02T00:00:00Z",
        submitted_at="2026-01-02T01:00:00Z",
        answers={
            "b": BooleanAnswer(value=True),
            "b_yes": FreeTextAnswer(value="hello"),
        },
    )
    db = Database(templates={tpl.id: tpl}, questionnaires={qn.id: qn})

    store = Store(tmp_path / "db.json")
    store.save(db)
    loaded = store.load()

    assert loaded == db


def test_save_is_atomic_no_tmp_left_behind(tmp_path: Path):
    path = tmp_path / "db.json"
    store = Store(path)
    store.save(Database())
    siblings = list(tmp_path.iterdir())
    assert path in siblings
    assert all(not s.name.endswith(".tmp") for s in siblings)


def test_load_handles_blank_file(tmp_path: Path):
    path = tmp_path / "db.json"
    path.write_text("")
    db = Store(path).load()
    assert db.templates == {}
    assert db.questionnaires == {}
