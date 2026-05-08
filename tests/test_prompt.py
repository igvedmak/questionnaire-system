"""prompt_for_answer must dispatch every question type — adding a new type
without wiring its prompt was the regression that motivated this test."""

from __future__ import annotations

import pytest

from questionnaire.cli import prompt as prompt_mod
from questionnaire.domain.types import (
    BooleanAnswer,
    BooleanQuestion,
    DateAnswer,
    DateQuestion,
    FreeTextAnswer,
    FreeTextQuestion,
    MultiSelectAnswer,
    MultiSelectQuestion,
    NumberAnswer,
    NumberQuestion,
    SingleSelectAnswer,
    SingleSelectQuestion,
)


class _FakeAsk:
    """Imitate questionary's chained .ask() pattern."""
    def __init__(self, value):
        self._value = value
    def ask(self):
        return self._value


@pytest.fixture
def fake_questionary(monkeypatch):
    """Stub every questionary primitive to return canned values."""
    canned = {"confirm": True, "select": None, "checkbox": None, "text": None}

    def make(name):
        def _factory(*args, **kwargs):
            return _FakeAsk(canned[name])
        return _factory

    monkeypatch.setattr(prompt_mod.questionary, "confirm", make("confirm"))
    monkeypatch.setattr(prompt_mod.questionary, "select", make("select"))
    monkeypatch.setattr(prompt_mod.questionary, "checkbox", make("checkbox"))
    monkeypatch.setattr(prompt_mod.questionary, "text", make("text"))
    return canned


def test_prompt_dispatches_boolean(fake_questionary):
    fake_questionary["confirm"] = True
    out = prompt_mod.prompt_for_answer(BooleanQuestion(id="b", prompt="?"))
    assert isinstance(out, BooleanAnswer) and out.value is True


def test_prompt_dispatches_single_select(fake_questionary):
    fake_questionary["select"] = "B"
    out = prompt_mod.prompt_for_answer(
        SingleSelectQuestion(id="s", prompt="?", options=["A", "B", "C"]),
    )
    assert isinstance(out, SingleSelectAnswer) and out.value == "B"


def test_prompt_dispatches_multi_select(fake_questionary):
    fake_questionary["checkbox"] = ["A", "C"]
    out = prompt_mod.prompt_for_answer(
        MultiSelectQuestion(id="m", prompt="?", options=["A", "B", "C"]),
    )
    assert isinstance(out, MultiSelectAnswer) and out.value == ["A", "C"]


def test_prompt_dispatches_date(fake_questionary):
    fake_questionary["text"] = "2026-05-08"
    out = prompt_mod.prompt_for_answer(DateQuestion(id="d", prompt="?"))
    assert isinstance(out, DateAnswer) and out.value == "2026-05-08"


def test_prompt_dispatches_free_text(fake_questionary):
    fake_questionary["text"] = "hello"
    out = prompt_mod.prompt_for_answer(FreeTextQuestion(id="t", prompt="?"))
    assert isinstance(out, FreeTextAnswer) and out.value == "hello"


def test_prompt_dispatches_number(fake_questionary):
    """The bug this test would have caught: NumberQuestion not wired into dispatch."""
    fake_questionary["text"] = "42"
    out = prompt_mod.prompt_for_answer(
        NumberQuestion(id="n", prompt="?", min=0, max=100, integer=True),
    )
    assert isinstance(out, NumberAnswer) and out.value == 42.0


def test_prompt_number_rejects_below_min_then_accepts(monkeypatch):
    """Re-prompts when input fails bounds, accepts on next valid try."""
    queue = ["-1", "5"]
    monkeypatch.setattr(
        prompt_mod.questionary, "text",
        lambda *a, **kw: _FakeAsk(queue.pop(0)),
    )
    out = prompt_mod.prompt_for_answer(
        NumberQuestion(id="n", prompt="?", min=0, max=100),
    )
    assert out.value == 5.0
    assert queue == []  # both inputs consumed


def test_prompt_number_rejects_non_integer_when_required(monkeypatch):
    queue = ["3.5", "4"]
    monkeypatch.setattr(
        prompt_mod.questionary, "text",
        lambda *a, **kw: _FakeAsk(queue.pop(0)),
    )
    out = prompt_mod.prompt_for_answer(
        NumberQuestion(id="n", prompt="?", integer=True),
    )
    assert out.value == 4.0
