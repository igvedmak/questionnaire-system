"""SQLAlchemy 2.x ORM models.

Schema design notes:

- Templates are append-only and keyed by (id, version). Past questionnaires
  always reference the version they were created against, so editing a
  template never silently invalidates prior responses.
- ``template_current`` is a tiny pointer table for "what is the latest
  version of template X?" — updated on every template save.
- Answers are normalized into a row-per-(qn, question, option_index) shape
  so that single-select / multi-select filters can be pushed to SQL via a
  simple index on (question_id, value_text). Multi-select stores one row
  per chosen option, which is how the spec's "includes Y" check lights up
  as a trivial WHERE clause.
- ``value_blob`` exists for Fernet-encrypted PII answers; ``is_pii`` is the
  flag that tells the read-side to decrypt.
- The audit log is append-only with a SHA-256 hash chain; see
  ``questionnaire.domain.audit``.
"""

from __future__ import annotations

from sqlalchemy import (
    Boolean,
    Float,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class TemplateRow(Base):
    __tablename__ = "templates"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    body_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[str] = mapped_column(String, nullable=False)


class TemplateCurrentRow(Base):
    """Latest version per template id. Updated whenever a new version lands."""
    __tablename__ = "template_current"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(["id", "version"], ["templates.id", "templates.version"]),
    )


class QuestionnaireRow(Base):
    __tablename__ = "questionnaires"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    template_id: Mapped[str] = mapped_column(String, nullable=False)
    template_version: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    submitted_at: Mapped[str | None] = mapped_column(String, nullable=True)
    respondent_id: Mapped[str | None] = mapped_column(String, nullable=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["template_id", "template_version"],
            ["templates.id", "templates.version"],
        ),
        Index("idx_qn_template", "template_id"),
        Index("idx_qn_respondent", "respondent_id"),
        Index("idx_qn_submitted", "submitted_at"),
    )


class AnswerRow(Base):
    __tablename__ = "answers"

    questionnaire_id: Mapped[str] = mapped_column(String, primary_key=True)
    question_id: Mapped[str] = mapped_column(String, primary_key=True)
    # Multi-select stores one row per option; option_index distinguishes them.
    # All other types use option_index=0.
    option_index: Mapped[int] = mapped_column(Integer, primary_key=True, default=0)

    type: Mapped[str] = mapped_column(String, nullable=False)
    value_text: Mapped[str | None] = mapped_column(String, nullable=True)
    value_num: Mapped[float | None] = mapped_column(Float, nullable=True)
    value_bool: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    value_blob: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    is_pii: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    __table_args__ = (
        # The make-or-break index for fast filtering on select-type questions.
        Index("idx_answers_qid_value", "question_id", "value_text"),
        Index("idx_answers_qid", "question_id"),
        Index("idx_answers_qn", "questionnaire_id"),
    )


class EmbeddingRow(Base):
    """Free-text answer embeddings for semantic clustering."""
    __tablename__ = "embeddings"

    questionnaire_id: Mapped[str] = mapped_column(String, primary_key=True)
    question_id: Mapped[str] = mapped_column(String, primary_key=True)
    vector: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    dim: Mapped[int] = mapped_column(Integer, nullable=False)


class AuditLogRow(Base):
    __tablename__ = "audit_log"

    seq: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[str] = mapped_column(String, nullable=False)
    actor: Mapped[str | None] = mapped_column(String, nullable=True)
    action: Mapped[str] = mapped_column(String, nullable=False)
    target_type: Mapped[str | None] = mapped_column(String, nullable=True)
    target_id: Mapped[str | None] = mapped_column(String, nullable=True)
    payload_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    prev_hash: Mapped[str] = mapped_column(String, nullable=False)
    hash: Mapped[str] = mapped_column(String, nullable=False)
