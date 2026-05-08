"""Resolve which questions are 'active' (must be answered) given current
answers.

A follow-up's nested questions become active only when the parent
question has been answered AND the follow-up's trigger fires. Triggers
come in two shapes:

- The legacy ``BoolFollowUp`` / ``SelectFollowUp`` (simple equality on the
  parent's answer) — compiled to expressions internally.
- ``ExprFollowUp`` — an arbitrary expression evaluated against the full
  answer map, so a follow-up can depend on sibling answers, numeric
  comparisons, boolean combinations, etc.
"""

from __future__ import annotations

from .expression import (
    compile_bool_trigger,
    compile_select_trigger,
    evaluate,
)
from .types import (
    AnswerValue,
    BoolFollowUp,
    BooleanQuestion,
    ExprFollowUp,
    MultiSelectQuestion,
    NumberQuestion,
    Question,
    SelectFollowUp,
    SingleSelectQuestion,
)


def resolve_active_questions(
    questions: list[Question],
    answers: dict[str, AnswerValue],
) -> list[Question]:
    """Return the flat ordered list of questions that are active given ``answers``."""
    out: list[Question] = []
    for q in questions:
        out.append(q)
        for nested in _triggered_followup_questions(q, answers):
            out.extend(resolve_active_questions(nested, answers))
    return out


def next_unanswered_question(
    questions: list[Question],
    answers: dict[str, AnswerValue],
) -> Question | None:
    for q in resolve_active_questions(questions, answers):
        if q.id not in answers:
            return q
    return None


def _triggered_followup_questions(
    q: Question,
    answers: dict[str, AnswerValue],
) -> list[list[Question]]:
    follow_ups = getattr(q, "follow_ups", None) or []
    triggered: list[list[Question]] = []
    for fu in follow_ups:
        if _trigger_fires(q, fu, answers):
            triggered.append(fu.questions)
    return triggered


def _trigger_fires(q: Question, fu, answers: dict[str, AnswerValue]) -> bool:
    """Evaluate a follow-up's trigger.

    Legacy shapes are compiled to expressions so the evaluator only deals
    with one form. Compilation is cheap (a few node allocations) and not
    cached — if it ever shows up in profiles we'd cache on the Question.
    """
    if isinstance(fu, ExprFollowUp):
        return bool(evaluate(fu.condition, answers))

    if isinstance(fu, BoolFollowUp):
        if not isinstance(q, BooleanQuestion):
            return False
        if q.id not in answers:
            return False
        expr = compile_bool_trigger(q.id, fu.when_equals)
        return bool(evaluate(expr, answers))

    if isinstance(fu, SelectFollowUp):
        if not isinstance(q, (SingleSelectQuestion, MultiSelectQuestion)):
            return False
        if q.id not in answers:
            return False
        expr = compile_select_trigger(
            q.id,
            isinstance(q, MultiSelectQuestion),
            fu.when_option_selected,
        )
        return bool(evaluate(expr, answers))

    return False


__all__ = [
    "resolve_active_questions",
    "next_unanswered_question",
    # Re-exported so callers don't need to import questionnaire.domain.types
    # to know what types come back.
    "NumberQuestion",
]
