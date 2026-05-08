"""Resolve which questions are 'active' (must be answered) given current answers.

The template's question tree is walked in order. A follow-up's nested questions
become active only when the parent question has been answered AND the follow-up's
trigger condition matches that answer. Follow-ups can themselves contain
questions with follow-ups — recursion handles arbitrary depth.

This single function drives the CLI flow (what to ask next), validation
(what must be present), and rendering (what to display).
"""

from __future__ import annotations

from .types import (
    AnswerValue,
    BooleanAnswer,
    BooleanQuestion,
    MultiSelectAnswer,
    MultiSelectQuestion,
    Question,
    SingleSelectAnswer,
    SingleSelectQuestion,
)


def resolve_active_questions(
    questions: list[Question],
    answers: dict[str, AnswerValue],
) -> list[Question]:
    """Return the flat ordered list of questions that are active given `answers`.

    A question is active if it sits at the top level of the template, OR if it
    sits under a follow-up whose trigger condition is satisfied by the current
    answers (recursively).
    """
    out: list[Question] = []
    for q in questions:
        out.append(q)
        ans = answers.get(q.id)
        if ans is None:
            continue
        for fu_questions in _triggered_followup_questions(q, ans):
            out.extend(resolve_active_questions(fu_questions, answers))
    return out


def next_unanswered_question(
    questions: list[Question],
    answers: dict[str, AnswerValue],
) -> Question | None:
    """Return the first active question without an answer, or None if all answered."""
    for q in resolve_active_questions(questions, answers):
        if q.id not in answers:
            return q
    return None


def _triggered_followup_questions(
    q: Question,
    ans: AnswerValue,
) -> list[list[Question]]:
    """Return the nested question lists of every follow-up triggered by `ans`."""
    triggered: list[list[Question]] = []
    if isinstance(q, BooleanQuestion) and isinstance(ans, BooleanAnswer):
        for fu in q.follow_ups:
            if fu.when_equals == ans.value:
                triggered.append(fu.questions)
    elif isinstance(q, SingleSelectQuestion) and isinstance(ans, SingleSelectAnswer):
        for fu in q.follow_ups:
            if fu.when_option_selected == ans.value:
                triggered.append(fu.questions)
    elif isinstance(q, MultiSelectQuestion) and isinstance(ans, MultiSelectAnswer):
        for fu in q.follow_ups:
            if fu.when_option_selected in ans.value:
                triggered.append(fu.questions)
    return triggered
