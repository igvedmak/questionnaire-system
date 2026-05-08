"""Tests for resolve_active_questions and next_unanswered_question.

The tree-walking is the single most bug-prone piece of this codebase, so the
tests here cover: ordering, single-level triggers, nested triggers, the
multi-select multiple-trigger case, and the 'turn off a follow-up by changing
its parent answer' case.
"""

from __future__ import annotations

from questionnaire.domain.flow import next_unanswered_question, resolve_active_questions
from questionnaire.domain.types import (
    BoolFollowUp,
    BooleanAnswer,
    BooleanQuestion,
    FreeTextAnswer,
    FreeTextQuestion,
    MultiSelectAnswer,
    MultiSelectQuestion,
    SelectFollowUp,
    SingleSelectAnswer,
    SingleSelectQuestion,
)


def _free(qid: str, prompt: str = "") -> FreeTextQuestion:
    return FreeTextQuestion(id=qid, prompt=prompt or qid)


def test_top_level_only_no_follow_ups():
    qs = [_free("a"), _free("b"), _free("c")]
    active = resolve_active_questions(qs, {})
    assert [q.id for q in active] == ["a", "b", "c"]


def test_boolean_follow_up_triggered():
    qs = [
        BooleanQuestion(
            id="b1",
            prompt="?",
            follow_ups=[BoolFollowUp(when_equals=True, questions=[_free("b1_yes")])],
        ),
        _free("after"),
    ]
    answers = {"b1": BooleanAnswer(value=True)}
    active = resolve_active_questions(qs, answers)
    # The follow-up's nested questions must come BEFORE the next top-level
    # question, mirroring how they'd be presented to the user.
    assert [q.id for q in active] == ["b1", "b1_yes", "after"]


def test_boolean_follow_up_not_triggered():
    qs = [
        BooleanQuestion(
            id="b1",
            prompt="?",
            follow_ups=[BoolFollowUp(when_equals=True, questions=[_free("b1_yes")])],
        ),
        _free("after"),
    ]
    answers = {"b1": BooleanAnswer(value=False)}
    active = resolve_active_questions(qs, answers)
    assert [q.id for q in active] == ["b1", "after"]


def test_nested_follow_ups_depth_two():
    """A → B → C: only fully expanded when both triggers fire."""
    inner = BooleanQuestion(
        id="inner",
        prompt="?",
        follow_ups=[BoolFollowUp(when_equals=True, questions=[_free("inner_yes")])],
    )
    outer = BooleanQuestion(
        id="outer",
        prompt="?",
        follow_ups=[BoolFollowUp(when_equals=True, questions=[inner])],
    )
    qs = [outer]

    # Outer not answered → only outer is active.
    assert [q.id for q in resolve_active_questions(qs, {})] == ["outer"]

    # Outer answered True → inner now active, but inner has no answer yet.
    a = {"outer": BooleanAnswer(value=True)}
    assert [q.id for q in resolve_active_questions(qs, a)] == ["outer", "inner"]

    # Inner answered True → inner_yes active too.
    a["inner"] = BooleanAnswer(value=True)
    assert [q.id for q in resolve_active_questions(qs, a)] == [
        "outer", "inner", "inner_yes",
    ]

    # Outer flipped to False → entire subtree collapses.
    a = {"outer": BooleanAnswer(value=False), "inner": BooleanAnswer(value=True)}
    assert [q.id for q in resolve_active_questions(qs, a)] == ["outer"]


def test_single_select_follow_up_only_fires_for_chosen_option():
    qs = [
        SingleSelectQuestion(
            id="s1",
            prompt="?",
            options=["A", "B", "C"],
            follow_ups=[
                SelectFollowUp(when_option_selected="A", questions=[_free("s1_a")]),
                SelectFollowUp(when_option_selected="B", questions=[_free("s1_b")]),
            ],
        ),
    ]
    a = {"s1": SingleSelectAnswer(value="B")}
    assert [q.id for q in resolve_active_questions(qs, a)] == ["s1", "s1_b"]


def test_multi_select_multiple_follow_ups_fire():
    """When two of the chosen options each trigger a follow-up, both fire."""
    qs = [
        MultiSelectQuestion(
            id="m1",
            prompt="?",
            options=["A", "B", "C"],
            follow_ups=[
                SelectFollowUp(when_option_selected="A", questions=[_free("m1_a")]),
                SelectFollowUp(when_option_selected="B", questions=[_free("m1_b")]),
                SelectFollowUp(when_option_selected="C", questions=[_free("m1_c")]),
            ],
        ),
    ]
    a = {"m1": MultiSelectAnswer(value=["A", "C"])}
    # Order follows follow-up-declaration order, then descends.
    assert [q.id for q in resolve_active_questions(qs, a)] == ["m1", "m1_a", "m1_c"]


def test_next_unanswered_question_skips_answered_and_inactive():
    qs = [
        BooleanQuestion(
            id="b1",
            prompt="?",
            follow_ups=[BoolFollowUp(when_equals=True, questions=[_free("b1_yes")])],
        ),
        _free("end"),
    ]
    # b1 answered True (so b1_yes activates) but not yet answered.
    a = {"b1": BooleanAnswer(value=True)}
    nxt = next_unanswered_question(qs, a)
    assert nxt is not None and nxt.id == "b1_yes"

    # Answer b1_yes too → next is "end".
    a["b1_yes"] = FreeTextAnswer(value="hi")
    nxt = next_unanswered_question(qs, a)
    assert nxt is not None and nxt.id == "end"

    # Answer end → all done.
    a["end"] = FreeTextAnswer(value="done")
    assert next_unanswered_question(qs, a) is None
