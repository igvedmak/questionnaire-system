"""Querying and filtering of submitted questionnaires.

Filters AND-combine. Three kinds:

- ``TemplateFilter``: questionnaire is an instance of the given template.
- ``IncludesFilter``: questionnaire's answer to question X equals (single-select)
  or contains (multi-select) the value Y.
- ``ExcludesFilter``: the negation of IncludesFilter.

Includes/Excludes are only valid against single-select and multi-select
questions; ``parse_filters`` enforces this by looking up the question across
all known templates and rejecting non-select targets.

Decision: when a questionnaire never reached the targeted question (the
follow-up was not triggered), ``IncludesFilter`` returns False and
``ExcludesFilter`` returns True — i.e., a missing answer is treated as "this
questionnaire does not include the value", which is the natural reading of
both filters.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Union

from .types import (
    MultiSelectAnswer,
    MultiSelectQuestion,
    Question,
    Questionnaire,
    SingleSelectAnswer,
    SingleSelectQuestion,
    Template,
)


@dataclass(frozen=True)
class TemplateFilter:
    template_id: str


@dataclass(frozen=True)
class IncludesFilter:
    question_id: str
    value: str


@dataclass(frozen=True)
class ExcludesFilter:
    question_id: str
    value: str


Filter = Union[TemplateFilter, IncludesFilter, ExcludesFilter]


class FilterError(Exception):
    """Raised when filter arguments don't make sense (unknown question, wrong type, etc.)."""


def apply_filters(
    questionnaires: Iterable[Questionnaire],
    filters: list[Filter],
) -> list[Questionnaire]:
    return [q for q in questionnaires if all(_match(q, f) for f in filters)]


def _match(q: Questionnaire, f: Filter) -> bool:
    if isinstance(f, TemplateFilter):
        return q.template_id == f.template_id

    if isinstance(f, IncludesFilter):
        ans = q.answers.get(f.question_id)
        if ans is None:
            return False
        if isinstance(ans, SingleSelectAnswer):
            return ans.value == f.value
        if isinstance(ans, MultiSelectAnswer):
            return f.value in ans.value
        # Includes/Excludes filters should never target a non-select question
        # (parse_filters rejects that), but if a hand-built filter slips through
        # we treat it as "no match".
        return False

    if isinstance(f, ExcludesFilter):
        ans = q.answers.get(f.question_id)
        if ans is None:
            return True
        if isinstance(ans, SingleSelectAnswer):
            return ans.value != f.value
        if isinstance(ans, MultiSelectAnswer):
            return f.value not in ans.value
        return True

    raise FilterError(f"unknown filter type: {type(f).__name__}")


# --- Parsing CLI-style filter strings ------------------------------------

def parse_filters(
    template_id: str | None,
    includes: list[str],
    excludes: list[str],
    templates: dict[str, Template],
) -> list[Filter]:
    """Parse CLI args into Filter objects.

    `includes` / `excludes` items are of the form "<questionId>=<value>".
    The question must exist in some known template and be of single-select
    or multi-select type; otherwise FilterError is raised.
    """
    filters: list[Filter] = []

    if template_id is not None:
        if template_id not in templates:
            raise FilterError(f"unknown template id: {template_id}")
        filters.append(TemplateFilter(template_id=template_id))

    for raw in includes:
        qid, value = _split_kv(raw, "--includes")
        _ensure_select_question(qid, templates)
        filters.append(IncludesFilter(question_id=qid, value=value))

    for raw in excludes:
        qid, value = _split_kv(raw, "--excludes")
        _ensure_select_question(qid, templates)
        filters.append(ExcludesFilter(question_id=qid, value=value))

    return filters


def _split_kv(raw: str, flag: str) -> tuple[str, str]:
    if "=" not in raw:
        raise FilterError(f"{flag} expects '<questionId>=<value>', got: {raw!r}")
    qid, value = raw.split("=", 1)
    if not qid or not value:
        raise FilterError(f"{flag} expects '<questionId>=<value>', got: {raw!r}")
    return qid, value


def _ensure_select_question(question_id: str, templates: dict[str, Template]) -> None:
    found = _find_question(question_id, templates)
    if found is None:
        raise FilterError(f"question id '{question_id}' not found in any template")
    if not isinstance(found, (SingleSelectQuestion, MultiSelectQuestion)):
        raise FilterError(
            f"includes/excludes filters only apply to single-select or "
            f"multi-select questions; '{question_id}' is {found.type}"
        )


def _find_question(question_id: str, templates: dict[str, Template]) -> Question | None:
    for tpl in templates.values():
        found = _walk_for_id(question_id, tpl.questions)
        if found is not None:
            return found
    return None


def _walk_for_id(question_id: str, questions: list[Question]) -> Question | None:
    for q in questions:
        if q.id == question_id:
            return q
        if isinstance(q, (SingleSelectQuestion, MultiSelectQuestion)):
            for fu in q.follow_ups:
                hit = _walk_for_id(question_id, fu.questions)
                if hit is not None:
                    return hit
        elif hasattr(q, "follow_ups"):
            # boolean
            for fu in q.follow_ups:  # type: ignore[attr-defined]
                hit = _walk_for_id(question_id, fu.questions)
                if hit is not None:
                    return hit
    return None
