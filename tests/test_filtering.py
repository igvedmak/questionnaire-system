"""Filtering tests: AND combination, includes/excludes semantics,
not-reached behavior, and parse-time rejection of invalid filters.
"""

from __future__ import annotations

import pytest

from questionnaire.domain.filtering import (
    ExcludesFilter,
    FilterError,
    IncludesFilter,
    TemplateFilter,
    apply_filters,
    parse_filters,
)
from questionnaire.domain.types import (
    BoolFollowUp,
    BooleanAnswer,
    BooleanQuestion,
    FreeTextAnswer,
    FreeTextQuestion,
    MultiSelectAnswer,
    MultiSelectQuestion,
    Questionnaire,
    SelectFollowUp,
    SingleSelectAnswer,
    SingleSelectQuestion,
    Template,
)


def _qn(qid: str, template_id: str, answers: dict, submitted: bool = True) -> Questionnaire:
    return Questionnaire(
        id=qid,
        template_id=template_id,
        created_at="2026-01-01T00:00:00Z",
        submitted_at="2026-01-02T00:00:00Z" if submitted else None,
        answers=answers,
    )


@pytest.fixture
def templates() -> dict[str, Template]:
    """Two templates: one with single/multi-select, one with a nested follow-up."""
    t1 = Template(
        id="t1",
        title="T1",
        created_at="2026-01-01T00:00:00Z",
        questions=[
            SingleSelectQuestion(id="color", prompt="?", options=["red", "green", "blue"]),
            MultiSelectQuestion(id="tags", prompt="?", options=["a", "b", "c", "d"]),
            FreeTextQuestion(id="notes", prompt="?"),
        ],
    )
    t2 = Template(
        id="t2",
        title="T2",
        created_at="2026-01-01T00:00:00Z",
        questions=[
            BooleanQuestion(
                id="has_pet",
                prompt="?",
                follow_ups=[BoolFollowUp(
                    when_equals=True,
                    questions=[SingleSelectQuestion(
                        id="pet_kind",
                        prompt="?",
                        options=["dog", "cat", "other"],
                    )],
                )],
            ),
        ],
    )
    return {"t1": t1, "t2": t2}


# --- apply_filters -------------------------------------------------------

def test_template_filter_only(templates):
    qns = [
        _qn("a", "t1", {}),
        _qn("b", "t2", {}),
        _qn("c", "t1", {}),
    ]
    out = apply_filters(qns, [TemplateFilter(template_id="t1")])
    assert sorted(q.id for q in out) == ["a", "c"]


def test_includes_single_select(templates):
    qns = [
        _qn("a", "t1", {"color": SingleSelectAnswer(value="red")}),
        _qn("b", "t1", {"color": SingleSelectAnswer(value="blue")}),
    ]
    out = apply_filters(qns, [IncludesFilter(question_id="color", value="red")])
    assert [q.id for q in out] == ["a"]


def test_includes_multi_select_matches_any_member(templates):
    qns = [
        _qn("a", "t1", {"tags": MultiSelectAnswer(value=["a", "b"])}),
        _qn("b", "t1", {"tags": MultiSelectAnswer(value=["c"])}),
        _qn("c", "t1", {"tags": MultiSelectAnswer(value=["a", "c"])}),
    ]
    out = apply_filters(qns, [IncludesFilter(question_id="tags", value="a")])
    assert sorted(q.id for q in out) == ["a", "c"]


def test_excludes_is_negation_of_includes(templates):
    qns = [
        _qn("a", "t1", {"color": SingleSelectAnswer(value="red")}),
        _qn("b", "t1", {"color": SingleSelectAnswer(value="blue")}),
    ]
    out = apply_filters(qns, [ExcludesFilter(question_id="color", value="red")])
    assert [q.id for q in out] == ["b"]


def test_filter_when_question_was_not_reached(templates):
    """has_pet=false → pet_kind never asked. includes returns False; excludes returns True."""
    not_reached = _qn("a", "t2", {"has_pet": BooleanAnswer(value=False)})
    reached_dog = _qn(
        "b",
        "t2",
        {"has_pet": BooleanAnswer(value=True), "pet_kind": SingleSelectAnswer(value="dog")},
    )

    inc = apply_filters(
        [not_reached, reached_dog],
        [IncludesFilter(question_id="pet_kind", value="dog")],
    )
    assert [q.id for q in inc] == ["b"]

    exc = apply_filters(
        [not_reached, reached_dog],
        [ExcludesFilter(question_id="pet_kind", value="dog")],
    )
    assert [q.id for q in exc] == ["a"]


def test_and_combination_of_three_filters(templates):
    qns = [
        _qn("a", "t1", {
            "color": SingleSelectAnswer(value="red"),
            "tags": MultiSelectAnswer(value=["a", "b"]),
        }),
        _qn("b", "t1", {
            "color": SingleSelectAnswer(value="red"),
            "tags": MultiSelectAnswer(value=["c", "d"]),
        }),
        _qn("c", "t1", {
            "color": SingleSelectAnswer(value="green"),
            "tags": MultiSelectAnswer(value=["a"]),
        }),
        _qn("d", "t2", {}),
    ]
    out = apply_filters(qns, [
        TemplateFilter(template_id="t1"),
        IncludesFilter(question_id="color", value="red"),
        ExcludesFilter(question_id="tags", value="d"),
    ])
    assert [q.id for q in out] == ["a"]


# --- parse_filters -------------------------------------------------------

def test_parse_filters_rejects_includes_on_non_select_question(templates):
    with pytest.raises(FilterError, match="single-select or multi-select"):
        parse_filters(None, ["notes=hi"], [], templates)


def test_parse_filters_rejects_unknown_question(templates):
    with pytest.raises(FilterError, match="not found"):
        parse_filters(None, ["nope=x"], [], templates)


def test_parse_filters_rejects_unknown_template(templates):
    with pytest.raises(FilterError, match="unknown template"):
        parse_filters("does_not_exist", [], [], templates)


def test_parse_filters_rejects_malformed_kv(templates):
    with pytest.raises(FilterError, match="expects"):
        parse_filters(None, ["no_equals_sign"], [], templates)


def test_parse_filters_finds_question_in_nested_followup(templates):
    """pet_kind lives inside a follow-up of has_pet — must still be findable."""
    fs = parse_filters(None, ["pet_kind=dog"], [], templates)
    assert fs == [IncludesFilter(question_id="pet_kind", value="dog")]


def test_parse_filters_accepts_multi_select(templates):
    fs = parse_filters(None, ["tags=a"], ["tags=b"], templates)
    assert fs == [
        IncludesFilter(question_id="tags", value="a"),
        ExcludesFilter(question_id="tags", value="b"),
    ]
