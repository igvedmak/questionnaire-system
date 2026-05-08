"""Tiny expression language for follow-up conditions.

The AST is JSON-serializable, lives inside the question tree, and is
evaluated against the current answers map. There is **no `eval`**; only the
operators below are recognized. Variables must resolve to a defined
question id — anything else is treated as missing (None), and comparisons
against missing values yield False (SQL NULL semantics).

JSON shape:

    {"op": "lit",      "value": true}
    {"op": "var",      "question_id": "age"}
    {"op": "eq" | "ne" | "gt" | "lt" | "ge" | "le", "left": <expr>, "right": <expr>}
    {"op": "in",       "left": <expr>, "right": <expr>}     # left ∈ right (right must eval to list)
    {"op": "contains", "haystack": <expr>, "needle": <expr>} # multi-select answer ∋ needle
    {"op": "and" | "or", "operands": [<expr>, ...]}
    {"op": "not",      "operand": <expr>}

The compiler (``compile_legacy_trigger``) turns the old ``BoolFollowUp`` /
``SelectFollowUp`` shapes into expressions internally so the resolver only
ever has to deal with one form.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field


class _Op(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LitExpr(_Op):
    op: Literal["lit"] = "lit"
    value: bool | int | float | str | list[str]


class VarExpr(_Op):
    op: Literal["var"] = "var"
    question_id: str


class EqExpr(_Op):
    op: Literal["eq"] = "eq"
    left: "Expression"
    right: "Expression"


class NeExpr(_Op):
    op: Literal["ne"] = "ne"
    left: "Expression"
    right: "Expression"


class GtExpr(_Op):
    op: Literal["gt"] = "gt"
    left: "Expression"
    right: "Expression"


class LtExpr(_Op):
    op: Literal["lt"] = "lt"
    left: "Expression"
    right: "Expression"


class GeExpr(_Op):
    op: Literal["ge"] = "ge"
    left: "Expression"
    right: "Expression"


class LeExpr(_Op):
    op: Literal["le"] = "le"
    left: "Expression"
    right: "Expression"


class InExpr(_Op):
    op: Literal["in"] = "in"
    left: "Expression"
    right: "Expression"  # must evaluate to a list


class ContainsExpr(_Op):
    op: Literal["contains"] = "contains"
    haystack: "Expression"
    needle: "Expression"


class AndExpr(_Op):
    op: Literal["and"] = "and"
    operands: list["Expression"]


class OrExpr(_Op):
    op: Literal["or"] = "or"
    operands: list["Expression"]


class NotExpr(_Op):
    op: Literal["not"] = "not"
    operand: "Expression"


Expression = Annotated[
    Union[
        LitExpr, VarExpr,
        EqExpr, NeExpr, GtExpr, LtExpr, GeExpr, LeExpr,
        InExpr, ContainsExpr,
        AndExpr, OrExpr, NotExpr,
    ],
    Field(discriminator="op"),
]


# Resolve forward refs.
for _cls in (
    EqExpr, NeExpr, GtExpr, LtExpr, GeExpr, LeExpr,
    InExpr, ContainsExpr, AndExpr, OrExpr, NotExpr,
):
    _cls.model_rebuild()


_MISSING = object()  # sentinel for "no answer present"


def evaluate(expr: Any, answers: dict[str, Any]) -> Any:
    """Evaluate ``expr`` against the answer map.

    ``answers`` maps question_id → AnswerValue. The ``.value`` is read for
    VarExpr; if the question isn't answered, ``_MISSING`` is returned and
    propagates: comparisons against missing return False, boolean ops treat
    missing as falsy, ``not missing`` is True.
    """
    if isinstance(expr, LitExpr):
        return expr.value

    if isinstance(expr, VarExpr):
        ans = answers.get(expr.question_id)
        return _MISSING if ans is None else ans.value

    if isinstance(expr, AndExpr):
        for sub in expr.operands:
            v = evaluate(sub, answers)
            if v is _MISSING or not v:
                return False
        return True

    if isinstance(expr, OrExpr):
        for sub in expr.operands:
            v = evaluate(sub, answers)
            if v is not _MISSING and v:
                return True
        return False

    if isinstance(expr, NotExpr):
        v = evaluate(expr.operand, answers)
        if v is _MISSING:
            return True
        return not v

    # Binary comparisons
    if isinstance(expr, (EqExpr, NeExpr, GtExpr, LtExpr, GeExpr, LeExpr)):
        l = evaluate(expr.left, answers)
        r = evaluate(expr.right, answers)
        if l is _MISSING or r is _MISSING:
            # ne against missing is False too (vacuous); avoids spurious activations.
            return False
        try:
            if isinstance(expr, EqExpr): return l == r
            if isinstance(expr, NeExpr): return l != r
            if isinstance(expr, GtExpr): return l > r
            if isinstance(expr, LtExpr): return l < r
            if isinstance(expr, GeExpr): return l >= r
            if isinstance(expr, LeExpr): return l <= r
        except TypeError:
            return False  # type-mismatched compare: don't crash, just don't fire
        return False

    if isinstance(expr, InExpr):
        l = evaluate(expr.left, answers)
        r = evaluate(expr.right, answers)
        if l is _MISSING or r is _MISSING or not isinstance(r, (list, tuple, set)):
            return False
        return l in r

    if isinstance(expr, ContainsExpr):
        h = evaluate(expr.haystack, answers)
        n = evaluate(expr.needle, answers)
        if h is _MISSING or n is _MISSING or not isinstance(h, (list, tuple, set)):
            return False
        return n in h

    raise RuntimeError(f"unhandled expression node: {type(expr).__name__}")


# --- Compilation of legacy triggers --------------------------------------

def compile_bool_trigger(parent_question_id: str, when_equals: bool) -> "Expression":
    """Old shape: ``BoolFollowUp(when_equals=True)`` →
    ``Eq(Var(parent), Lit(True))``."""
    return EqExpr(
        left=VarExpr(question_id=parent_question_id),
        right=LitExpr(value=when_equals),
    )


def compile_select_trigger(
    parent_question_id: str,
    parent_is_multi: bool,
    when_option_selected: str,
) -> "Expression":
    """Old shape: ``SelectFollowUp(when_option_selected="X")``.

    For single-select: ``Eq(Var(parent), Lit("X"))``.
    For multi-select:  ``Contains(Var(parent), Lit("X"))``.
    """
    if parent_is_multi:
        return ContainsExpr(
            haystack=VarExpr(question_id=parent_question_id),
            needle=LitExpr(value=when_option_selected),
        )
    return EqExpr(
        left=VarExpr(question_id=parent_question_id),
        right=LitExpr(value=when_option_selected),
    )


def collect_var_references(expr: Any) -> set[str]:
    """Return the set of question_ids referenced by ``expr`` (recursive)."""
    out: set[str] = set()

    def walk(e: Any) -> None:
        if isinstance(e, VarExpr):
            out.add(e.question_id)
            return
        if isinstance(e, LitExpr):
            return
        if isinstance(e, (AndExpr, OrExpr)):
            for s in e.operands:
                walk(s)
            return
        if isinstance(e, NotExpr):
            walk(e.operand)
            return
        if isinstance(e, (EqExpr, NeExpr, GtExpr, LtExpr, GeExpr, LeExpr, InExpr)):
            walk(e.left)
            walk(e.right)
            return
        if isinstance(e, ContainsExpr):
            walk(e.haystack)
            walk(e.needle)
            return

    walk(expr)
    return out
