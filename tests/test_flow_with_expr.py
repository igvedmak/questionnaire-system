"""Tests for the resolver's interaction with expression-based follow-ups
and number questions."""

from __future__ import annotations

from questionnaire.domain.expression import EqExpr, GtExpr, LitExpr, VarExpr
from questionnaire.domain.flow import resolve_active_questions
from questionnaire.domain.types import (
    BoolFollowUp,
    BooleanQuestion,
    ExprFollowUp,
    FreeTextAnswer,
    FreeTextQuestion,
    NumberAnswer,
    NumberQuestion,
    SingleSelectAnswer,
    SingleSelectQuestion,
)


def test_expr_follow_up_with_cross_question_reference():
    """A follow-up that activates only when both age >= 18 AND country == 'US'."""
    questions = [
        NumberQuestion(id="age", prompt="?", min=0, max=130, integer=True),
        SingleSelectQuestion(id="country", prompt="?", options=["US", "UK", "DE"]),
        FreeTextQuestion(
            id="us_adult_only",
            prompt="?",
            # We attach this to a parent via a follow-up; here we test the
            # condition wiring by giving 'country' the follow-up.
        ),
    ]

    questions = [
        NumberQuestion(id="age", prompt="?", min=0, max=130, integer=True),
        SingleSelectQuestion(
            id="country",
            prompt="?",
            options=["US", "UK", "DE"],
            follow_ups=[ExprFollowUp(
                condition=EqExpr(
                    left=VarExpr(question_id="country"),
                    right=LitExpr(value="US"),
                ),
                questions=[FreeTextQuestion(id="us_only", prompt="US-specific")],
            )],
        ),
    ]

    # country=US → us_only active.
    a = {"country": SingleSelectAnswer(value="US")}
    assert [q.id for q in resolve_active_questions(questions, a)] == ["age", "country", "us_only"]

    # country=UK → us_only not active.
    a = {"country": SingleSelectAnswer(value="UK")}
    assert [q.id for q in resolve_active_questions(questions, a)] == ["age", "country"]


def test_expr_follow_up_on_number_with_gt():
    """Number question with an expression follow-up gated on a numeric threshold."""
    questions = [
        NumberQuestion(
            id="age",
            prompt="?",
            min=0, max=130,
            follow_ups=[ExprFollowUp(
                condition=GtExpr(
                    left=VarExpr(question_id="age"),
                    right=LitExpr(value=18),
                ),
                questions=[FreeTextQuestion(id="adult_question", prompt="?")],
            )],
        ),
    ]
    assert [q.id for q in resolve_active_questions(questions, {"age": NumberAnswer(value=15)})] == ["age"]
    assert [q.id for q in resolve_active_questions(questions, {"age": NumberAnswer(value=25)})] == ["age", "adult_question"]


def test_legacy_and_expr_followups_coexist():
    """A boolean question with both a legacy BoolFollowUp and an ExprFollowUp."""
    questions = [
        BooleanQuestion(
            id="b",
            prompt="?",
            follow_ups=[
                BoolFollowUp(
                    when_equals=True,
                    questions=[FreeTextQuestion(id="legacy_yes", prompt="?")],
                ),
                ExprFollowUp(
                    condition=EqExpr(
                        left=VarExpr(question_id="b"),
                        right=LitExpr(value=False),
                    ),
                    questions=[FreeTextQuestion(id="expr_no", prompt="?")],
                ),
            ],
        ),
    ]
    from questionnaire.domain.types import BooleanAnswer

    a = {"b": BooleanAnswer(value=True)}
    assert [q.id for q in resolve_active_questions(questions, a)] == ["b", "legacy_yes"]

    a = {"b": BooleanAnswer(value=False)}
    assert [q.id for q in resolve_active_questions(questions, a)] == ["b", "expr_no"]
