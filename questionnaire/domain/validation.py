"""Validation of templates and answers.

Two distinct validations:

- ``validate_template``: structural correctness of a template (option counts,
  follow-up triggers reference real options, unique question IDs, etc.).
  Run when a template is loaded / created; a failure means the template is
  malformed and unusable.

- ``validate_answers`` / ``validate_for_submission``: correctness of the
  answers in a questionnaire against its template. Run on every save and
  before submission.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from .flow import resolve_active_questions
from .types import (
    AnswerValue,
    BooleanAnswer,
    BooleanQuestion,
    DateAnswer,
    DateQuestion,
    FreeTextAnswer,
    FreeTextQuestion,
    MultiSelectAnswer,
    MultiSelectQuestion,
    Question,
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
    """Walk the template tree and check structural invariants.

    - single-select questions need > 2 options (per spec wording "more than 2")
    - multi-select questions need >= 1 option
    - follow-up triggers must reference a real option
    - question IDs must be unique across the entire (recursive) tree
    - no follow-ups on date / free-text questions (already enforced by types,
      but defended here in case of hand-edited JSON)
    """
    result = ValidationResult()
    seen_ids: set[str] = set()

    def walk(questions: list[Question]) -> None:
        for q in questions:
            if q.id in seen_ids:
                result.add(f"duplicate question id '{q.id}'", q.id)
            seen_ids.add(q.id)

            if isinstance(q, SingleSelectQuestion):
                if len(q.options) <= 2:
                    result.add(
                        f"single-select must have more than 2 options (has {len(q.options)})",
                        q.id,
                    )
                if len(set(q.options)) != len(q.options):
                    result.add("single-select options must be unique", q.id)
                for fu in q.follow_ups:
                    if fu.when_option_selected not in q.options:
                        result.add(
                            f"follow-up trigger '{fu.when_option_selected}' is not an option",
                            q.id,
                        )
                    walk(fu.questions)

            elif isinstance(q, MultiSelectQuestion):
                if len(q.options) < 1:
                    result.add("multi-select must have at least one option", q.id)
                if len(set(q.options)) != len(q.options):
                    result.add("multi-select options must be unique", q.id)
                for fu in q.follow_ups:
                    if fu.when_option_selected not in q.options:
                        result.add(
                            f"follow-up trigger '{fu.when_option_selected}' is not an option",
                            q.id,
                        )
                    walk(fu.questions)

            elif isinstance(q, BooleanQuestion):
                # Multiple follow-ups for the same value are allowed; the runtime
                # concatenates their questions in order.
                for fu in q.follow_ups:
                    walk(fu.questions)

            # date / free_text: no follow-ups by construction; nothing to check.

    walk(template.questions)
    return result


# --- Answer validation ---------------------------------------------------

def validate_answers(
    template: Template,
    answers: dict[str, AnswerValue],
) -> ValidationResult:
    """Validate present answers against the template (structural correctness only).

    Does NOT require all active questions to be answered — that's
    `validate_for_submission`'s job. This is intended to be called on every
    save so partial drafts can be persisted.
    """
    result = ValidationResult()
    active = resolve_active_questions(template.questions, answers)
    active_by_id = {q.id: q for q in active}

    for ans_id, ans in answers.items():
        q = active_by_id.get(ans_id)
        if q is None:
            # Either the answer is to a question that never existed, or to one
            # whose follow-up trigger is no longer satisfied. Either way it's
            # stale and should be flagged.
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
    """Same as validate_answers, plus 'every active question must be answered'."""
    result = validate_answers(template, answers)
    active = resolve_active_questions(template.questions, answers)
    for q in active:
        if q.id not in answers:
            result.add("missing answer for active question", q.id)
    return result


def _check_answer(q: Question, ans: AnswerValue) -> str | None:
    if q.type != ans.type:
        return f"type mismatch: question is {q.type}, answer is {ans.type}"

    if isinstance(q, BooleanQuestion) and isinstance(ans, BooleanAnswer):
        return None  # bool is bool, Pydantic already enforced it

    if isinstance(q, SingleSelectQuestion) and isinstance(ans, SingleSelectAnswer):
        if ans.value not in q.options:
            return f"value '{ans.value}' is not one of the options {q.options}"
        return None

    if isinstance(q, MultiSelectQuestion) and isinstance(ans, MultiSelectAnswer):
        if len(ans.value) == 0:
            return "multi-select requires at least one selection"
        if len(set(ans.value)) != len(ans.value):
            return "multi-select has duplicate selections"
        invalid = [v for v in ans.value if v not in q.options]
        if invalid:
            return f"selections {invalid} are not in the options {q.options}"
        return None

    if isinstance(q, DateQuestion) and isinstance(ans, DateAnswer):
        try:
            datetime.strptime(ans.value, "%Y-%m-%d")
        except ValueError:
            return f"invalid date '{ans.value}', expected YYYY-MM-DD"
        return None

    if isinstance(q, FreeTextQuestion) and isinstance(ans, FreeTextAnswer):
        # Pydantic enforces str; empty strings are allowed (the spec says "any text").
        return None

    # Should be unreachable given the type-mismatch check above.
    return f"unhandled question/answer combination: {q.type}/{ans.type}"
