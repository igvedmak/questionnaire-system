"""Tests for the non-interactive `qst answer fill` helpers."""

from __future__ import annotations

import pytest

from questionnaire.cli.answer_cmd import _coerce_answer, _index_questions_by_id
from questionnaire.domain.types import (
    BoolFollowUp,
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
    SelectFollowUp,
    SingleSelectAnswer,
    SingleSelectQuestion,
)


def test_coerce_boolean():
    q = BooleanQuestion(id="b", prompt="?")
    out = _coerce_answer(q, True)
    assert isinstance(out, BooleanAnswer) and out.value is True


def test_coerce_single_select():
    q = SingleSelectQuestion(id="s", prompt="?", options=["a", "b", "c"])
    out = _coerce_answer(q, "a")
    assert isinstance(out, SingleSelectAnswer) and out.value == "a"


def test_coerce_multi_select():
    q = MultiSelectQuestion(id="m", prompt="?", options=["a", "b", "c"])
    out = _coerce_answer(q, ["a", "c"])
    assert isinstance(out, MultiSelectAnswer) and out.value == ["a", "c"]


def test_coerce_date():
    q = DateQuestion(id="d", prompt="?")
    out = _coerce_answer(q, "2026-05-08")
    assert isinstance(out, DateAnswer) and out.value == "2026-05-08"


def test_coerce_free_text():
    q = FreeTextQuestion(id="t", prompt="?")
    out = _coerce_answer(q, "hello")
    assert isinstance(out, FreeTextAnswer) and out.value == "hello"


def test_coerce_number_int_and_float():
    q = NumberQuestion(id="n", prompt="?")
    assert _coerce_answer(q, 33).value == 33.0
    assert _coerce_answer(q, 3.5).value == 3.5


def test_coerce_number_rejects_bool():
    """bool is a subclass of int in Python; we explicitly reject it for clarity."""
    q = NumberQuestion(id="n", prompt="?")
    with pytest.raises(ValueError):
        _coerce_answer(q, True)


def test_coerce_type_mismatch_raises():
    q = SingleSelectQuestion(id="s", prompt="?", options=["a", "b", "c"])
    with pytest.raises(ValueError):
        _coerce_answer(q, 42)


def test_index_questions_finds_nested():
    """Question ids deep inside follow-ups must be findable by `fill`."""
    questions = [
        BooleanQuestion(
            id="b",
            prompt="?",
            follow_ups=[BoolFollowUp(
                when_equals=True,
                questions=[
                    SingleSelectQuestion(
                        id="inner_s",
                        prompt="?",
                        options=["a", "b", "c"],
                        follow_ups=[SelectFollowUp(
                            when_option_selected="a",
                            questions=[FreeTextQuestion(id="deep_t", prompt="?")],
                        )],
                    ),
                ],
            )],
        ),
    ]
    idx = _index_questions_by_id(questions)
    assert set(idx) == {"b", "inner_s", "deep_t"}
