"""Tests for the expression engine: evaluation, missing-value semantics,
boolean precedence, and JSON round-trip."""

from __future__ import annotations

from pydantic import TypeAdapter

from questionnaire.domain.expression import (
    AndExpr,
    ContainsExpr,
    EqExpr,
    Expression,
    GtExpr,
    InExpr,
    LitExpr,
    NotExpr,
    OrExpr,
    VarExpr,
    collect_var_references,
    evaluate,
)
from questionnaire.domain.types import (
    BooleanAnswer,
    MultiSelectAnswer,
    NumberAnswer,
    SingleSelectAnswer,
)


def test_literal_evaluates_to_itself():
    assert evaluate(LitExpr(value=True), {}) is True
    assert evaluate(LitExpr(value=42), {}) == 42
    assert evaluate(LitExpr(value="x"), {}) == "x"


def test_var_returns_answer_value():
    expr = VarExpr(question_id="age")
    assert evaluate(expr, {"age": NumberAnswer(value=21)}) == 21


def test_eq_against_missing_returns_false():
    """Comparisons against a missing answer must not silently pass."""
    expr = EqExpr(left=VarExpr(question_id="age"), right=LitExpr(value=21))
    assert evaluate(expr, {}) is False


def test_gt_works_with_number_answer():
    expr = GtExpr(left=VarExpr(question_id="age"), right=LitExpr(value=18))
    assert evaluate(expr, {"age": NumberAnswer(value=21)}) is True
    assert evaluate(expr, {"age": NumberAnswer(value=15)}) is False


def test_and_short_circuits_on_missing():
    """If any operand evaluates to missing, AND is False (no spurious activation)."""
    expr = AndExpr(operands=[
        EqExpr(left=VarExpr(question_id="age"), right=LitExpr(value=21)),
        EqExpr(left=VarExpr(question_id="country"), right=LitExpr(value="US")),
    ])
    # age present, country missing → False
    assert evaluate(expr, {"age": NumberAnswer(value=21)}) is False


def test_or_with_one_true_is_true():
    expr = OrExpr(operands=[
        EqExpr(left=VarExpr(question_id="x"), right=LitExpr(value="a")),
        EqExpr(left=VarExpr(question_id="y"), right=LitExpr(value="b")),
    ])
    assert evaluate(expr, {"x": SingleSelectAnswer(value="a"), "y": SingleSelectAnswer(value="z")}) is True


def test_not_of_missing_is_true():
    """If a question hasn't been answered, NOT of any predicate over it is True
    by SQL semantics. Documented behavior — useful for "if not chose X" follow-ups."""
    expr = NotExpr(operand=EqExpr(left=VarExpr(question_id="x"), right=LitExpr(value="a")))
    assert evaluate(expr, {}) is True


def test_in_membership():
    expr = InExpr(
        left=VarExpr(question_id="role"),
        right=LitExpr(value=["admin", "owner"]),
    )
    assert evaluate(expr, {"role": SingleSelectAnswer(value="admin")}) is True
    assert evaluate(expr, {"role": SingleSelectAnswer(value="user")}) is False


def test_contains_for_multi_select():
    expr = ContainsExpr(
        haystack=VarExpr(question_id="symptoms"),
        needle=LitExpr(value="Fever"),
    )
    assert evaluate(expr, {"symptoms": MultiSelectAnswer(value=["Fever", "Cough"])}) is True
    assert evaluate(expr, {"symptoms": MultiSelectAnswer(value=["Cough"])}) is False


def test_type_mismatch_does_not_crash():
    """Comparing string > int shouldn't blow up; returns False."""
    expr = GtExpr(left=VarExpr(question_id="x"), right=LitExpr(value=5))
    assert evaluate(expr, {"x": SingleSelectAnswer(value="hello")}) is False


def test_var_references_are_collected_recursively():
    expr = AndExpr(operands=[
        EqExpr(left=VarExpr(question_id="a"), right=LitExpr(value=1)),
        OrExpr(operands=[
            GtExpr(left=VarExpr(question_id="b"), right=LitExpr(value=2)),
            ContainsExpr(haystack=VarExpr(question_id="c"), needle=LitExpr(value="x")),
        ]),
    ])
    assert collect_var_references(expr) == {"a", "b", "c"}


def test_expression_round_trips_through_json():
    expr = AndExpr(operands=[
        GtExpr(left=VarExpr(question_id="age"), right=LitExpr(value=18)),
        EqExpr(left=VarExpr(question_id="country"), right=LitExpr(value="US")),
    ])
    adapter = TypeAdapter(Expression)
    data = adapter.dump_python(expr)
    parsed = adapter.validate_python(data)
    answers = {
        "age": NumberAnswer(value=21),
        "country": SingleSelectAnswer(value="US"),
    }
    assert evaluate(parsed, answers) is True


def test_complex_boolean_logic_precedence():
    # (a AND b) OR (NOT c)
    expr = OrExpr(operands=[
        AndExpr(operands=[
            EqExpr(left=VarExpr(question_id="a"), right=LitExpr(value=True)),
            EqExpr(left=VarExpr(question_id="b"), right=LitExpr(value=True)),
        ]),
        NotExpr(operand=EqExpr(left=VarExpr(question_id="c"), right=LitExpr(value=True))),
    ])
    assert evaluate(expr, {
        "a": BooleanAnswer(value=True),
        "b": BooleanAnswer(value=True),
        "c": BooleanAnswer(value=True),
    }) is True
    assert evaluate(expr, {
        "a": BooleanAnswer(value=True),
        "b": BooleanAnswer(value=False),
        "c": BooleanAnswer(value=True),
    }) is False  # AND fails AND NOT(true) is false → OR is false
    assert evaluate(expr, {
        "a": BooleanAnswer(value=False),
        "b": BooleanAnswer(value=False),
        "c": BooleanAnswer(value=False),
    }) is True  # AND fails but NOT(false) is true → OR is true
