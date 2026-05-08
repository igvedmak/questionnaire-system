"""Validation of templates and answers.

- ``validate_template``: structural correctness (option counts, follow-up
  triggers reference real options or real question ids, unique question
  ids, etc.). Run when a template is loaded / created.
- ``validate_answers`` / ``validate_for_submission``: correctness of the
  answers in a questionnaire against its template. Run on every save and
  before submission.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from datetime import datetime

from .expression import collect_var_references
from .flow import resolve_active_questions
from .types import (
    AnswerValue,
    BoolFollowUp,
    BooleanQuestion,
    DateAnswer,
    ExprFollowUp,
    MultiSelectAnswer,
    MultiSelectQuestion,
    NumberAnswer,
    NumberQuestion,
    Question,
    SelectFollowUp,
    SingleSelectAnswer,
    SingleSelectQuestion,
    Template,
)


@dataclass
class ValidationError:
    message: str
    question_id: str | None = None

    def __str__(self) -> str:
        return f"[{self.question_id}] {self.message}" if self.question_id else self.message


@dataclass
class ValidationResult:
    errors: list[ValidationError] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def add(self, message: str, question_id: str | None = None) -> None:
        self.errors.append(ValidationError(message=message, question_id=question_id))


# --- Template validation -------------------------------------------------

def validate_template(template: Template) -> ValidationResult:
    """Walk the template tree and check structural invariants."""
    result = ValidationResult()
    seen_ids: set[str] = set()
    # Question ids that are visible at the time their follow-up's expression
    # is evaluated. We accumulate them in DFS order — an expression in a
    # nested follow-up can reference any ancestor question id (all earlier
    # questions on the path that gates it).
    available_ids: set[str] = set()

    def check_expr_refs(refs: set[str], context_qid: str | None) -> None:
        for ref in refs:
            # An expression can refer to any question id in the template,
            # because the resolver holds the whole answers map. We require
            # the ref to be a real id in the tree — we'll learn that fully
            # only after the second pass. For now, defer: collect refs and
            # check at the end against the final id set.
            unresolved_refs.add((ref, context_qid))

    unresolved_refs: set[tuple[str, str | None]] = set()

    def walk(questions: list[Question]) -> None:
        for q in questions:
            if q.id in seen_ids:
                result.add(f"duplicate question id '{q.id}'", q.id)
            seen_ids.add(q.id)
            available_ids.add(q.id)

            if isinstance(q, SingleSelectQuestion):
                if len(q.options) <= 2:
                    result.add(
                        f"single-select must have more than 2 options (has {len(q.options)})",
                        q.id,
                    )
                if len(set(q.options)) != len(q.options):
                    result.add("single-select options must be unique", q.id)
                for fu in q.follow_ups:
                    _check_follow_up(fu, q, result, check_expr_refs)
                    walk(fu.questions)

            elif isinstance(q, MultiSelectQuestion):
                if len(q.options) < 1:
                    result.add("multi-select must have at least one option", q.id)
                if len(set(q.options)) != len(q.options):
                    result.add("multi-select options must be unique", q.id)
                for fu in q.follow_ups:
                    _check_follow_up(fu, q, result, check_expr_refs)
                    walk(fu.questions)

            elif isinstance(q, BooleanQuestion):
                for fu in q.follow_ups:
                    _check_follow_up(fu, q, result, check_expr_refs)
                    walk(fu.questions)

            elif isinstance(q, NumberQuestion):
                if q.min is not None and q.max is not None and q.min > q.max:
                    result.add(f"number bounds reversed: min={q.min} max={q.max}", q.id)
                for fu in q.follow_ups:
                    refs = collect_var_references(fu.condition)
                    check_expr_refs(refs, q.id)
                    walk(fu.questions)

            # date / free_text: no follow-ups by construction.

    walk(template.questions)

    # All refs must resolve to known ids in the tree.
    for ref, ctx in unresolved_refs:
        if ref not in seen_ids:
            result.add(
                f"expression references unknown question id '{ref}'",
                ctx,
            )

    return result


def _check_follow_up(fu, parent_q, result, check_expr_refs) -> None:
    if isinstance(fu, BoolFollowUp):
        if not isinstance(parent_q, BooleanQuestion):
            result.add("BoolFollowUp on non-boolean question", parent_q.id)
        return
    if isinstance(fu, SelectFollowUp):
        if not isinstance(parent_q, (SingleSelectQuestion, MultiSelectQuestion)):
            result.add("SelectFollowUp on non-select question", parent_q.id)
            return
        if fu.when_option_selected not in parent_q.options:
            result.add(
                f"follow-up trigger '{fu.when_option_selected}' is not an option",
                parent_q.id,
            )
        return
    if isinstance(fu, ExprFollowUp):
        refs = collect_var_references(fu.condition)
        check_expr_refs(refs, parent_q.id)
        return


# --- Answer validation ---------------------------------------------------

def validate_answers(
    template: Template,
    answers: dict[str, AnswerValue],
) -> ValidationResult:
    """Validate present answers against the template (structural correctness only)."""
    result = ValidationResult()
    active = resolve_active_questions(template.questions, answers)
    active_by_id = {q.id: q for q in active}

    for ans_id, ans in answers.items():
        q = active_by_id.get(ans_id)
        if q is None:
            result.add("answer for inactive or unknown question", ans_id)
            continue
        msg = _check_answer(q, ans)
        if msg:
            result.add(msg, ans_id)

    return result


def validate_for_submission(
    template: Template,
    answers: dict[str, AnswerValue],
) -> ValidationResult:
    result = validate_answers(template, answers)
    active = resolve_active_questions(template.questions, answers)
    for q in active:
        if q.id not in answers:
            result.add("missing answer for active question", q.id)
    return result


# --- Validator strategy --------------------------------------------------

class AnswerValidator(abc.ABC):
    """Per-type answer validation strategy.

    Adding a new question type means adding a new subclass and registering
    it in ``_VALIDATORS`` — existing validators are untouched.
    """

    @abc.abstractmethod
    def check(self, q: Question, ans: AnswerValue) -> str | None:
        ...


class _BooleanValidator(AnswerValidator):
    def check(self, q: Question, ans: AnswerValue) -> str | None:
        del q, ans
        return None


class _SingleSelectValidator(AnswerValidator):
    def check(self, q: Question, ans: AnswerValue) -> str | None:
        assert isinstance(q, SingleSelectQuestion) and isinstance(ans, SingleSelectAnswer)
        if ans.value not in q.options:
            return f"value '{ans.value}' is not one of the options {q.options}"
        return None


class _MultiSelectValidator(AnswerValidator):
    def check(self, q: Question, ans: AnswerValue) -> str | None:
        assert isinstance(q, MultiSelectQuestion) and isinstance(ans, MultiSelectAnswer)
        if len(ans.value) == 0:
            return "multi-select requires at least one selection"
        if len(set(ans.value)) != len(ans.value):
            return "multi-select has duplicate selections"
        invalid = [v for v in ans.value if v not in q.options]
        if invalid:
            return f"selections {invalid} are not in the options {q.options}"
        return None


class _DateValidator(AnswerValidator):
    def check(self, _q: Question, ans: AnswerValue) -> str | None:
        assert isinstance(ans, DateAnswer)
        try:
            datetime.strptime(ans.value, "%Y-%m-%d")
        except ValueError:
            return f"invalid date '{ans.value}', expected YYYY-MM-DD"
        return None


class _FreeTextValidator(AnswerValidator):
    def check(self, q: Question, ans: AnswerValue) -> str | None:
        del q, ans
        return None


class _NumberValidator(AnswerValidator):
    def check(self, q: Question, ans: AnswerValue) -> str | None:
        assert isinstance(q, NumberQuestion) and isinstance(ans, NumberAnswer)
        if q.integer and not float(ans.value).is_integer():
            return f"value {ans.value} is not an integer"
        if q.min is not None and ans.value < q.min:
            return f"value {ans.value} is below min {q.min}"
        if q.max is not None and ans.value > q.max:
            return f"value {ans.value} is above max {q.max}"
        return None


_VALIDATORS: dict[str, AnswerValidator] = {
    "boolean": _BooleanValidator(),
    "single_select": _SingleSelectValidator(),
    "multi_select": _MultiSelectValidator(),
    "date": _DateValidator(),
    "free_text": _FreeTextValidator(),
    "number": _NumberValidator(),
}


def _check_answer(q: Question, ans: AnswerValue) -> str | None:
    if q.type != ans.type:
        return f"type mismatch: question is {q.type}, answer is {ans.type}"
    validator = _VALIDATORS.get(q.type)
    if validator is None:
        return f"unhandled question/answer combination: {q.type}/{ans.type}"
    return validator.check(q, ans)
