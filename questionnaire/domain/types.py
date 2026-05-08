"""Domain types.

Question and AnswerValue are discriminated unions on the `type` field. This
lets Pydantic round-trip the recursive question tree to/from JSON without
custom serialization code, and lets the type checker prove that follow-ups
only exist on the branchable question types.

Follow-ups support two shapes for backward compatibility:
- The original ``BoolFollowUp`` / ``SelectFollowUp`` (equality-based triggers)
- The richer ``ExprFollowUp`` whose ``condition`` is an arbitrary
  :mod:`questionnaire.domain.expression` AST.

Pydantic v2 smart-mode unions discriminate them by field shape; both forms
are accepted at parse time and the resolver compiles the legacy shapes to
expressions internally.
"""

from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field

from .expression import Expression


# --- Follow-up shapes ----------------------------------------------------

class BoolFollowUp(BaseModel):
    """Legacy shape — kept for backward compatibility."""
    model_config = ConfigDict(extra="forbid")
    when_equals: bool
    questions: list["Question"]


class SelectFollowUp(BaseModel):
    """Legacy shape — kept for backward compatibility.

    For single-select: triggers when chosen option == when_option_selected.
    For multi-select:  triggers when when_option_selected is among the
    chosen options.
    """
    model_config = ConfigDict(extra="forbid")
    when_option_selected: str
    questions: list["Question"]


class ExprFollowUp(BaseModel):
    """General-purpose follow-up: triggers when ``condition`` evaluates true."""
    model_config = ConfigDict(extra="forbid")
    condition: Expression
    questions: list["Question"]


BoolOrExprFollowUp = Union[BoolFollowUp, ExprFollowUp]
SelectOrExprFollowUp = Union[SelectFollowUp, ExprFollowUp]


# --- Questions -----------------------------------------------------------

class _BaseQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    prompt: str
    # PII flag — when true, the answer is encrypted at rest. Only meaningful
    # for free-text answers in this round; reserved on other types for
    # forward compatibility.
    pii: bool = False


class BooleanQuestion(_BaseQuestion):
    type: Literal["boolean"] = "boolean"
    follow_ups: list[BoolOrExprFollowUp] = Field(default_factory=list)


class SingleSelectQuestion(_BaseQuestion):
    type: Literal["single_select"] = "single_select"
    options: list[str]
    follow_ups: list[SelectOrExprFollowUp] = Field(default_factory=list)


class MultiSelectQuestion(_BaseQuestion):
    type: Literal["multi_select"] = "multi_select"
    options: list[str]
    follow_ups: list[SelectOrExprFollowUp] = Field(default_factory=list)


class DateQuestion(_BaseQuestion):
    type: Literal["date"] = "date"


class FreeTextQuestion(_BaseQuestion):
    type: Literal["free_text"] = "free_text"


class NumberQuestion(_BaseQuestion):
    """Numeric answer with optional bounds and integer constraint."""
    type: Literal["number"] = "number"
    min: float | None = None
    max: float | None = None
    integer: bool = False
    # Number questions can carry expression-based follow-ups (e.g., age >= 18).
    follow_ups: list[ExprFollowUp] = Field(default_factory=list)


Question = Annotated[
    Union[
        BooleanQuestion,
        SingleSelectQuestion,
        MultiSelectQuestion,
        DateQuestion,
        FreeTextQuestion,
        NumberQuestion,
    ],
    Field(discriminator="type"),
]


# --- Answer values -------------------------------------------------------

class BooleanAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["boolean"] = "boolean"
    value: bool


class SingleSelectAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["single_select"] = "single_select"
    value: str


class MultiSelectAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["multi_select"] = "multi_select"
    value: list[str]


class DateAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["date"] = "date"
    value: str  # ISO YYYY-MM-DD


class FreeTextAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["free_text"] = "free_text"
    value: str


class NumberAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["number"] = "number"
    value: float


AnswerValue = Annotated[
    Union[
        BooleanAnswer,
        SingleSelectAnswer,
        MultiSelectAnswer,
        DateAnswer,
        FreeTextAnswer,
        NumberAnswer,
    ],
    Field(discriminator="type"),
]


# --- Aggregates ----------------------------------------------------------

class Template(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    title: str
    questions: list[Question]
    created_at: str
    # Versioning. New templates start at version 1; subsequent edits append.
    version: int = 1


class Questionnaire(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    template_id: str
    template_version: int = 1
    created_at: str
    submitted_at: str | None = None
    # Optional respondent identifier for GDPR export/delete.
    respondent_id: str | None = None
    answers: dict[str, AnswerValue] = Field(default_factory=dict)

    @property
    def is_submitted(self) -> bool:
        return self.submitted_at is not None


class Database(BaseModel):
    """Used only by the legacy JSON store (and the migration source)."""
    model_config = ConfigDict(extra="forbid")
    templates: dict[str, Template] = Field(default_factory=dict)
    questionnaires: dict[str, Questionnaire] = Field(default_factory=dict)


# Resolve forward references in follow-up models.
BoolFollowUp.model_rebuild()
SelectFollowUp.model_rebuild()
ExprFollowUp.model_rebuild()
