"""Domain types.

Question and AnswerValue are discriminated unions on the `type` field. This lets
Pydantic round-trip the recursive question tree to/from JSON without custom
serialization code, and lets the type checker prove that follow-ups only exist
on the three branchable question types.
"""

from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field


# --- Follow-up rules -----------------------------------------------------

class BoolFollowUp(BaseModel):
    model_config = ConfigDict(extra="forbid")
    when_equals: bool
    questions: list["Question"]


class SelectFollowUp(BaseModel):
    """For single-select: triggers when the chosen option == when_option_selected.
    For multi-select: triggers when when_option_selected is among the chosen options."""
    model_config = ConfigDict(extra="forbid")
    when_option_selected: str
    questions: list["Question"]


# --- Questions -----------------------------------------------------------

class _BaseQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    prompt: str


class BooleanQuestion(_BaseQuestion):
    type: Literal["boolean"] = "boolean"
    follow_ups: list[BoolFollowUp] = Field(default_factory=list)


class SingleSelectQuestion(_BaseQuestion):
    type: Literal["single_select"] = "single_select"
    options: list[str]
    follow_ups: list[SelectFollowUp] = Field(default_factory=list)


class MultiSelectQuestion(_BaseQuestion):
    type: Literal["multi_select"] = "multi_select"
    options: list[str]
    follow_ups: list[SelectFollowUp] = Field(default_factory=list)


class DateQuestion(_BaseQuestion):
    type: Literal["date"] = "date"


class FreeTextQuestion(_BaseQuestion):
    type: Literal["free_text"] = "free_text"


Question = Annotated[
    Union[
        BooleanQuestion,
        SingleSelectQuestion,
        MultiSelectQuestion,
        DateQuestion,
        FreeTextQuestion,
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


AnswerValue = Annotated[
    Union[
        BooleanAnswer,
        SingleSelectAnswer,
        MultiSelectAnswer,
        DateAnswer,
        FreeTextAnswer,
    ],
    Field(discriminator="type"),
]


# --- Aggregates ----------------------------------------------------------

class Template(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    title: str
    questions: list[Question]
    created_at: str  # ISO 8601 UTC


class Questionnaire(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    template_id: str
    created_at: str
    submitted_at: str | None = None
    answers: dict[str, AnswerValue] = Field(default_factory=dict)

    @property
    def is_submitted(self) -> bool:
        return self.submitted_at is not None


class Database(BaseModel):
    model_config = ConfigDict(extra="forbid")
    templates: dict[str, Template] = Field(default_factory=dict)
    questionnaires: dict[str, Questionnaire] = Field(default_factory=dict)


# Resolve forward references in follow-up models.
BoolFollowUp.model_rebuild()
SelectFollowUp.model_rebuild()
