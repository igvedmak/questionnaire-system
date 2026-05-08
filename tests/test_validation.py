"""Validation tests: template structural rules, per-type answer rules, and
the orphaned-answer case (follow-up was deactivated but its answer remains).
"""

from __future__ import annotations

import pytest

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
    SelectFollowUp,
    SingleSelectAnswer,
    SingleSelectQuestion,
    Template,
)
from questionnaire.domain.validation import (
    validate_answers,
    validate_for_submission,
    validate_template,
)


def _tpl(*questions) -> Template:
    return Template(
        id="t1",
        title="t",
        created_at="2026-01-01T00:00:00Z",
        questions=list(questions),
    )


# --- validate_template ---------------------------------------------------

def test_template_rejects_single_select_with_two_or_fewer_options():
    tpl = _tpl(SingleSelectQuestion(id="q", prompt="?", options=["A", "B"]))
    res = validate_template(tpl)
    assert not res.ok
    assert any("more than 2 options" in str(e) for e in res.errors)


def test_template_accepts_single_select_with_three_options():
    tpl = _tpl(SingleSelectQuestion(id="q", prompt="?", options=["A", "B", "C"]))
    assert validate_template(tpl).ok


def test_template_rejects_duplicate_question_ids_across_tree():
    tpl = _tpl(
        BooleanQuestion(
            id="dup",
            prompt="?",
            follow_ups=[BoolFollowUp(
                when_equals=True,
                questions=[FreeTextQuestion(id="dup", prompt="?")],
            )],
        ),
    )
    res = validate_template(tpl)
    assert not res.ok
    assert any("duplicate" in str(e) for e in res.errors)


def test_template_rejects_follow_up_trigger_for_non_existent_option():
    tpl = _tpl(
        SingleSelectQuestion(
            id="q",
            prompt="?",
            options=["A", "B", "C"],
            follow_ups=[SelectFollowUp(
                when_option_selected="Z",
                questions=[FreeTextQuestion(id="q_z", prompt="?")],
            )],
        ),
    )
    res = validate_template(tpl)
    assert not res.ok
    assert any("'Z'" in str(e) and "not an option" in str(e) for e in res.errors)


def test_template_rejects_duplicate_options():
    tpl = _tpl(SingleSelectQuestion(id="q", prompt="?", options=["A", "A", "B"]))
    res = validate_template(tpl)
    assert not res.ok


# --- validate_answers ----------------------------------------------------

def test_answer_type_must_match_question_type():
    tpl = _tpl(BooleanQuestion(id="b", prompt="?"))
    a = {"b": FreeTextAnswer(value="oops")}
    res = validate_answers(tpl, a)
    assert not res.ok
    assert any("type mismatch" in str(e) for e in res.errors)


def test_single_select_answer_must_be_in_options():
    tpl = _tpl(SingleSelectQuestion(id="s", prompt="?", options=["A", "B", "C"]))
    res = validate_answers(tpl, {"s": SingleSelectAnswer(value="Z")})
    assert not res.ok


def test_multi_select_rejects_empty_selection():
    tpl = _tpl(MultiSelectQuestion(id="m", prompt="?", options=["A", "B"]))
    res = validate_answers(tpl, {"m": MultiSelectAnswer(value=[])})
    assert not res.ok
    assert any("at least one" in str(e) for e in res.errors)


def test_multi_select_rejects_duplicates():
    tpl = _tpl(MultiSelectQuestion(id="m", prompt="?", options=["A", "B"]))
    res = validate_answers(tpl, {"m": MultiSelectAnswer(value=["A", "A"])})
    assert not res.ok
    assert any("duplicate" in str(e) for e in res.errors)


def test_multi_select_rejects_invalid_options():
    tpl = _tpl(MultiSelectQuestion(id="m", prompt="?", options=["A", "B"]))
    res = validate_answers(tpl, {"m": MultiSelectAnswer(value=["A", "Z"])})
    assert not res.ok


@pytest.mark.parametrize("date_str", ["2024-02-30", "2025-13-01", "not-a-date", "2025/01/01"])
def test_date_rejects_invalid_strings(date_str):
    tpl = _tpl(DateQuestion(id="d", prompt="?"))
    res = validate_answers(tpl, {"d": DateAnswer(value=date_str)})
    assert not res.ok


@pytest.mark.parametrize("date_str", ["2024-02-29", "2025-01-01", "2025-12-31"])
def test_date_accepts_valid_strings(date_str):
    tpl = _tpl(DateQuestion(id="d", prompt="?"))
    res = validate_answers(tpl, {"d": DateAnswer(value=date_str)})
    assert res.ok


def test_orphaned_answer_after_follow_up_deactivation():
    """User answers Q1=true → Q1_yes activates → user answers Q1_yes →
    user changes Q1 to false → Q1_yes is now inactive but its answer remains.
    """
    tpl = _tpl(
        BooleanQuestion(
            id="b1",
            prompt="?",
            follow_ups=[BoolFollowUp(
                when_equals=True,
                questions=[FreeTextQuestion(id="b1_yes", prompt="?")],
            )],
        ),
    )
    answers = {
        "b1": BooleanAnswer(value=False),  # parent flipped
        "b1_yes": FreeTextAnswer(value="leftover"),  # stranded follow-up answer
    }
    res = validate_answers(tpl, answers)
    assert not res.ok
    assert any("inactive" in str(e) for e in res.errors)


def test_validate_for_submission_requires_all_active_questions_answered():
    tpl = _tpl(
        BooleanQuestion(id="b", prompt="?"),
        FreeTextQuestion(id="t", prompt="?"),
    )
    res = validate_for_submission(tpl, {"b": BooleanAnswer(value=True)})
    assert not res.ok
    assert any("missing" in str(e) for e in res.errors)


def test_validate_for_submission_passes_when_complete():
    tpl = _tpl(
        BooleanQuestion(
            id="b",
            prompt="?",
            follow_ups=[BoolFollowUp(
                when_equals=True,
                questions=[FreeTextQuestion(id="b_yes", prompt="?")],
            )],
        ),
    )
    res = validate_for_submission(
        tpl,
        {
            "b": BooleanAnswer(value=True),
            "b_yes": FreeTextAnswer(value="ok"),
        },
    )
    assert res.ok


def test_validate_for_submission_does_not_require_inactive_follow_ups():
    """When the follow-up trigger is not satisfied, the nested question must
    NOT be required for submission."""
    tpl = _tpl(
        BooleanQuestion(
            id="b",
            prompt="?",
            follow_ups=[BoolFollowUp(
                when_equals=True,
                questions=[FreeTextQuestion(id="b_yes", prompt="?")],
            )],
        ),
    )
    res = validate_for_submission(tpl, {"b": BooleanAnswer(value=False)})
    assert res.ok
