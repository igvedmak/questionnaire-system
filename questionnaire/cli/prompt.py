"""Interactive prompt helpers, one per question type.

Each helper validates the user's input by re-running the domain validator,
so the user sees the same error message regardless of where they entered
the answer (CLI vs. hand-edited JSON).
"""

from __future__ import annotations

from datetime import datetime

import questionary

from ..domain.types import (
    AnswerValue,
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
    Question,
    SingleSelectAnswer,
    SingleSelectQuestion,
)


def prompt_for_answer(q: Question) -> AnswerValue:
    """Dispatch on question type. Re-prompts on invalid input where it makes sense."""
    if isinstance(q, BooleanQuestion):
        return _prompt_boolean(q)
    if isinstance(q, SingleSelectQuestion):
        return _prompt_single_select(q)
    if isinstance(q, MultiSelectQuestion):
        return _prompt_multi_select(q)
    if isinstance(q, DateQuestion):
        return _prompt_date(q)
    if isinstance(q, FreeTextQuestion):
        return _prompt_free_text(q)
    if isinstance(q, NumberQuestion):
        return _prompt_number(q)
    raise RuntimeError(f"unhandled question type: {q.type}")


def _prompt_boolean(q: BooleanQuestion) -> BooleanAnswer:
    answer = questionary.confirm(q.prompt, default=False).ask()
    if answer is None:
        raise KeyboardInterrupt
    return BooleanAnswer(value=answer)


def _prompt_single_select(q: SingleSelectQuestion) -> SingleSelectAnswer:
    answer = questionary.select(q.prompt, choices=q.options).ask()
    if answer is None:
        raise KeyboardInterrupt
    return SingleSelectAnswer(value=answer)


def _prompt_multi_select(q: MultiSelectQuestion) -> MultiSelectAnswer:
    while True:
        answer = questionary.checkbox(
            q.prompt + "  (space to toggle, enter to confirm)",
            choices=q.options,
        ).ask()
        if answer is None:
            raise KeyboardInterrupt
        if not answer:
            print("  ! select at least one option")
            continue
        return MultiSelectAnswer(value=answer)


def _prompt_date(q: DateQuestion) -> DateAnswer:
    while True:
        answer = questionary.text(
            q.prompt + "  (YYYY-MM-DD)",
        ).ask()
        if answer is None:
            raise KeyboardInterrupt
        answer = answer.strip()
        try:
            datetime.strptime(answer, "%Y-%m-%d")
        except ValueError:
            print("  ! invalid date, expected YYYY-MM-DD")
            continue
        return DateAnswer(value=answer)


def _prompt_free_text(q: FreeTextQuestion) -> FreeTextAnswer:
    answer = questionary.text(q.prompt).ask()
    if answer is None:
        raise KeyboardInterrupt
    return FreeTextAnswer(value=answer)


def _prompt_number(q: NumberQuestion) -> NumberAnswer:
    bounds = []
    if q.min is not None:
        bounds.append(f"min={q.min:g}")
    if q.max is not None:
        bounds.append(f"max={q.max:g}")
    if q.integer:
        bounds.append("integer")
    suffix = f"  ({', '.join(bounds)})" if bounds else ""

    while True:
        raw = questionary.text(q.prompt + suffix).ask()
        if raw is None:
            raise KeyboardInterrupt
        raw = raw.strip()
        try:
            value = float(raw)
        except ValueError:
            print("  ! not a number")
            continue
        if q.integer and not value.is_integer():
            print(f"  ! must be an integer (got {raw})")
            continue
        if q.min is not None and value < q.min:
            print(f"  ! below min {q.min}")
            continue
        if q.max is not None and value > q.max:
            print(f"  ! above max {q.max}")
            continue
        return NumberAnswer(value=value)
