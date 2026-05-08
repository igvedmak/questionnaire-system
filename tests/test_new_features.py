"""Tests for all new features added in the product upgrade.

Covers:
- RatingQuestion/RatingAnswer validation
- EmailQuestion/EmailAnswer validation
- required=False question skipping on submission
- hint field round-trip
- Template tags and description
- archive_questionnaire hides from default queries
- get_template_stats
- duplicate_template
- Webhook CRUD
- Pagination (query_questionnaires_page)
- Free-text max length validation
- validate_expiry for expired and archived questionnaires
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from questionnaire.domain import encryption
from questionnaire.domain.types import (
    BooleanAnswer,
    BooleanQuestion,
    EmailAnswer,
    EmailQuestion,
    FreeTextAnswer,
    FreeTextQuestion,
    NumberAnswer,
    NumberQuestion,
    Questionnaire,
    RatingAnswer,
    RatingQuestion,
    SingleSelectAnswer,
    SingleSelectQuestion,
    Template,
)
from questionnaire.domain.validation import (
    validate_answers,
    validate_expiry,
    validate_for_submission,
)
from questionnaire.persistence import WebhookConfig
from questionnaire.persistence.sql_store import SqlStore, SubmissionLockedError, StoreError


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def store(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("QST_PII_KEY", Fernet.generate_key().decode())
    encryption.reset_key_cache()
    return SqlStore(f"sqlite:///{tmp_path / 'test.sqlite'}")


def _tpl(*qs, id="t1", title="T") -> Template:
    return Template(id=id, title=title, created_at="2026-01-01T00:00:00Z", questions=list(qs))


def _qn(qid, tpl, answers=None, respondent_id=None) -> Questionnaire:
    return Questionnaire(
        id=qid,
        template_id=tpl.id,
        template_version=tpl.version if hasattr(tpl, "version") else 1,
        created_at="2026-01-01T00:00:00Z",
        answers=answers or {},
        respondent_id=respondent_id,
    )


# ---------------------------------------------------------------------------
# RatingQuestion / RatingAnswer validation
# ---------------------------------------------------------------------------

def test_rating_in_range():
    tpl = _tpl(RatingQuestion(id="r", prompt="Rate it", min_val=1, max_val=5))
    for v in (1, 3, 5):
        res = validate_answers(tpl, {"r": RatingAnswer(value=v)})
        assert res.ok, f"expected ok for value={v}, got: {res.errors}"


def test_rating_out_of_range_below():
    tpl = _tpl(RatingQuestion(id="r", prompt="Rate it", min_val=1, max_val=5))
    res = validate_answers(tpl, {"r": RatingAnswer(value=0)})
    assert not res.ok
    assert any("outside range" in str(e) for e in res.errors)


def test_rating_out_of_range_above():
    tpl = _tpl(RatingQuestion(id="r", prompt="Rate it", min_val=1, max_val=5))
    res = validate_answers(tpl, {"r": RatingAnswer(value=6)})
    assert not res.ok
    assert any("outside range" in str(e) for e in res.errors)


def test_rating_custom_range():
    tpl = _tpl(RatingQuestion(id="r", prompt="Rate it", min_val=0, max_val=10))
    res = validate_answers(tpl, {"r": RatingAnswer(value=7)})
    assert res.ok


# ---------------------------------------------------------------------------
# EmailQuestion / EmailAnswer validation
# ---------------------------------------------------------------------------

def test_email_valid():
    tpl = _tpl(EmailQuestion(id="e", prompt="Email?"))
    res = validate_answers(tpl, {"e": EmailAnswer(value="user@example.com")})
    assert res.ok


def test_email_invalid_no_at():
    tpl = _tpl(EmailQuestion(id="e", prompt="Email?"))
    res = validate_answers(tpl, {"e": EmailAnswer(value="notanemail")})
    assert not res.ok
    assert any("invalid email" in str(err) for err in res.errors)


def test_email_invalid_no_domain():
    tpl = _tpl(EmailQuestion(id="e", prompt="Email?"))
    res = validate_answers(tpl, {"e": EmailAnswer(value="user@")})
    assert not res.ok


def test_email_valid_subdomain():
    tpl = _tpl(EmailQuestion(id="e", prompt="Email?"))
    res = validate_answers(tpl, {"e": EmailAnswer(value="user@sub.example.co.uk")})
    assert res.ok


# ---------------------------------------------------------------------------
# required=False question skipped on submission
# ---------------------------------------------------------------------------

def test_required_false_skipped_on_submission():
    tpl = _tpl(
        BooleanQuestion(id="b", prompt="?"),
        FreeTextQuestion(id="opt", prompt="Optional", required=False),
    )
    # Only answer the required question — should still pass.
    res = validate_for_submission(tpl, {"b": BooleanAnswer(value=True)})
    assert res.ok, f"expected ok but got: {res.errors}"


def test_required_true_still_required():
    tpl = _tpl(
        BooleanQuestion(id="b", prompt="?"),
        FreeTextQuestion(id="req", prompt="Required", required=True),
    )
    res = validate_for_submission(tpl, {"b": BooleanAnswer(value=True)})
    assert not res.ok
    assert any("missing" in str(e) for e in res.errors)


# ---------------------------------------------------------------------------
# hint field preserved through store round-trip
# ---------------------------------------------------------------------------

def test_hint_field_round_trip(store):
    tpl = Template(
        id="tpl_hint",
        title="Hint test",
        created_at="2026-01-01T00:00:00Z",
        questions=[
            FreeTextQuestion(id="q1", prompt="Tell us", hint="Up to 200 characters"),
        ],
    )
    saved = store.save_template(tpl)
    loaded = store.get_template(saved.id)
    assert loaded is not None
    assert loaded.questions[0].hint == "Up to 200 characters"


# ---------------------------------------------------------------------------
# Template tags and description
# ---------------------------------------------------------------------------

def test_template_tags_and_description_round_trip(store):
    tpl = Template(
        id="tpl_tags",
        title="Tagged template",
        created_at="2026-01-01T00:00:00Z",
        questions=[BooleanQuestion(id="b", prompt="?")],
        description="A description",
        tags=["health", "intake"],
    )
    saved = store.save_template(tpl)
    loaded = store.get_template(saved.id)
    assert loaded is not None
    assert loaded.description == "A description"
    assert loaded.tags == ["health", "intake"]


# ---------------------------------------------------------------------------
# archive_questionnaire hides from default queries
# ---------------------------------------------------------------------------

def test_archive_hides_from_default_queries(store):
    tpl = _tpl(BooleanQuestion(id="b", prompt="?"))
    store.save_template(tpl)
    qn = _qn("q1", tpl, {"b": BooleanAnswer(value=True)})
    store.save_questionnaire(qn)
    store.submit_questionnaire("q1")

    # Verify it appears before archiving.
    results = store.query_questionnaires([])
    assert any(q.id == "q1" for q in results)

    store.archive_questionnaire("q1")

    # Should no longer appear in default queries.
    results_after = store.query_questionnaires([])
    assert not any(q.id == "q1" for q in results_after)


def test_archive_visible_with_include_archived(store):
    tpl = _tpl(BooleanQuestion(id="b", prompt="?"))
    store.save_template(tpl)
    qn = _qn("q2", tpl, {"b": BooleanAnswer(value=True)})
    store.save_questionnaire(qn)
    store.submit_questionnaire("q2")
    store.archive_questionnaire("q2")

    results = store.query_questionnaires([], include_archived=True)
    assert any(q.id == "q2" for q in results)


def test_archive_nonexistent_raises_store_error(store):
    with pytest.raises(StoreError):
        store.archive_questionnaire("does-not-exist")


# ---------------------------------------------------------------------------
# get_template_stats
# ---------------------------------------------------------------------------

def test_get_template_stats_counts(store):
    tpl = _tpl(
        BooleanQuestion(id="b", prompt="?"),
        FreeTextQuestion(id="t", prompt="?"),
        id="tpl_stats",
    )
    store.save_template(tpl)

    # Two submitted questionnaires.
    for i in range(2):
        qn = _qn(f"sub{i}", tpl, {"b": BooleanAnswer(value=True), "t": FreeTextAnswer(value="ok")})
        store.save_questionnaire(qn)
        store.submit_questionnaire(f"sub{i}")

    # One draft.
    qn_draft = _qn("draft1", tpl, {"b": BooleanAnswer(value=False)})
    store.save_questionnaire(qn_draft)

    stats = store.get_template_stats("tpl_stats")
    assert stats is not None
    assert stats.template_id == "tpl_stats"
    assert stats.total_submissions == 2
    assert stats.total_drafts == 1
    # Both submitted questionnaires answered "b" and "t".
    assert stats.answer_counts.get("b", 0) >= 2


def test_get_template_stats_none_for_unknown(store):
    assert store.get_template_stats("nonexistent") is None


# ---------------------------------------------------------------------------
# duplicate_template
# ---------------------------------------------------------------------------

def test_duplicate_template_creates_copy(store):
    tpl = _tpl(BooleanQuestion(id="b", prompt="?"), id="orig")
    store.save_template(tpl)

    copy = store.duplicate_template("orig", new_id="copy1")
    assert copy.id == "copy1"
    assert copy.version == 1
    assert copy.questions[0].id == "b"


def test_duplicate_template_autogenerates_id(store):
    tpl = _tpl(BooleanQuestion(id="b", prompt="?"), id="orig2")
    store.save_template(tpl)

    copy = store.duplicate_template("orig2")
    assert copy.id != "orig2"
    assert len(copy.id) > 0


def test_duplicate_template_original_unaffected(store):
    tpl = _tpl(BooleanQuestion(id="b", prompt="?"), id="src")
    store.save_template(tpl)
    store.duplicate_template("src", new_id="dst")

    original = store.get_template("src")
    assert original is not None
    assert original.id == "src"


def test_duplicate_template_nonexistent_raises(store):
    with pytest.raises(StoreError):
        store.duplicate_template("does-not-exist")


# ---------------------------------------------------------------------------
# Webhook CRUD
# ---------------------------------------------------------------------------

def test_save_and_list_webhook(store):
    wh = WebhookConfig(
        id="wh1",
        url="https://example.com/hook",
        events=["questionnaire.submit"],
        secret=None,
        created_at="2026-01-01T00:00:00Z",
        active=True,
    )
    store.save_webhook(wh)
    hooks = store.list_webhooks()
    assert any(h.id == "wh1" for h in hooks)


def test_delete_webhook(store):
    wh = WebhookConfig(
        id="wh2",
        url="https://example.com/hook2",
        events=["gdpr.delete"],
        secret="s",
        created_at="2026-01-01T00:00:00Z",
        active=True,
    )
    store.save_webhook(wh)
    store.delete_webhook("wh2")
    hooks = store.list_webhooks()
    assert not any(h.id == "wh2" for h in hooks)


def test_delete_nonexistent_webhook_raises(store):
    with pytest.raises(StoreError):
        store.delete_webhook("does-not-exist")


def test_list_webhooks_empty(store):
    assert store.list_webhooks() == []


# ---------------------------------------------------------------------------
# Pagination: query_questionnaires_page
# ---------------------------------------------------------------------------

def _seed_many(store, n=10):
    tpl = _tpl(
        SingleSelectQuestion(id="color", prompt="?", options=["red", "green", "blue"]),
        id="tpl_page",
    )
    store.save_template(tpl)
    for i in range(n):
        color = ["red", "green", "blue"][i % 3]
        qn = _qn(f"pq{i}", tpl, {"color": SingleSelectAnswer(value=color)})
        store.save_questionnaire(qn)
        store.submit_questionnaire(f"pq{i}")
    return tpl


def test_query_questionnaires_page_returns_total(store):
    _seed_many(store, n=10)
    items, total = store.query_questionnaires_page([], page=1, page_size=5)
    assert total == 10
    assert len(items) == 5


def test_query_questionnaires_page_second_page(store):
    _seed_many(store, n=10)
    items1, _ = store.query_questionnaires_page([], page=1, page_size=4)
    items2, _ = store.query_questionnaires_page([], page=2, page_size=4)
    ids1 = {q.id for q in items1}
    ids2 = {q.id for q in items2}
    assert ids1.isdisjoint(ids2), "pages must not overlap"


def test_query_questionnaires_page_beyond_end_returns_empty(store):
    _seed_many(store, n=5)
    items, total = store.query_questionnaires_page([], page=100, page_size=5)
    assert total == 5
    assert items == []


def test_query_questionnaires_page_respects_filters(store):
    tpl = _seed_many(store, n=6)
    from questionnaire.domain.filtering import IncludesFilter
    items, total = store.query_questionnaires_page(
        [IncludesFilter(question_id="color", value="red")],
        page=1, page_size=50,
    )
    assert total == 2  # 6 items, indices 0,3 are red
    assert all(q.answers["color"].value == "red" for q in items)


# ---------------------------------------------------------------------------
# Free-text max length validation
# ---------------------------------------------------------------------------

def test_freetext_within_max_length(monkeypatch):
    monkeypatch.setattr(
        "questionnaire.domain.validation.settings",
        type("S", (), {"max_free_text_length": 100})(),
    )
    tpl = _tpl(FreeTextQuestion(id="t", prompt="?"))
    res = validate_answers(tpl, {"t": FreeTextAnswer(value="a" * 100)})
    assert res.ok


def test_freetext_exceeds_max_length(monkeypatch):
    monkeypatch.setattr(
        "questionnaire.domain.validation.settings",
        type("S", (), {"max_free_text_length": 10})(),
    )
    tpl = _tpl(FreeTextQuestion(id="t", prompt="?"))
    res = validate_answers(tpl, {"t": FreeTextAnswer(value="a" * 11)})
    assert not res.ok
    assert any("max length" in str(e) for e in res.errors)


# ---------------------------------------------------------------------------
# validate_expiry for expired and archived questionnaires
# ---------------------------------------------------------------------------

def test_validate_expiry_active_questionnaire():
    future = (datetime.now(timezone.utc) + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    qn = Questionnaire(
        id="qe1", template_id="t", template_version=1,
        created_at="2026-01-01T00:00:00Z",
        expires_at=future,
    )
    result = validate_expiry(qn)
    assert result.ok


def test_validate_expiry_expired_questionnaire():
    past = "2020-01-01T00:00:00Z"
    qn = Questionnaire(
        id="qe2", template_id="t", template_version=1,
        created_at="2019-01-01T00:00:00Z",
        expires_at=past,
    )
    result = validate_expiry(qn)
    assert not result.ok
    assert any("expired" in str(e) for e in result.errors)


def test_validate_expiry_archived_questionnaire():
    qn = Questionnaire(
        id="qe3", template_id="t", template_version=1,
        created_at="2026-01-01T00:00:00Z",
        archived_at="2026-02-01T00:00:00Z",
    )
    result = validate_expiry(qn)
    assert not result.ok
    assert any("archived" in str(e) for e in result.errors)


def test_validate_expiry_both_expired_and_archived():
    past = "2020-01-01T00:00:00Z"
    qn = Questionnaire(
        id="qe4", template_id="t", template_version=1,
        created_at="2019-01-01T00:00:00Z",
        expires_at=past,
        archived_at="2020-06-01T00:00:00Z",
    )
    result = validate_expiry(qn)
    assert not result.ok
    assert len(result.errors) == 2


def test_validate_expiry_no_expiry_no_archive():
    qn = Questionnaire(
        id="qe5", template_id="t", template_version=1,
        created_at="2026-01-01T00:00:00Z",
    )
    result = validate_expiry(qn)
    assert result.ok


# ---------------------------------------------------------------------------
# Store-level expiry / archive enforcement in upsert_answer
# ---------------------------------------------------------------------------

def test_upsert_answer_blocked_on_archived(store):
    tpl = _tpl(BooleanQuestion(id="b", prompt="?"))
    store.save_template(tpl)
    qn = _qn("arc1", tpl)
    store.save_questionnaire(qn)
    store.archive_questionnaire("arc1")

    with pytest.raises(SubmissionLockedError):
        store.upsert_answer("arc1", "b", BooleanAnswer(value=True))


def test_upsert_answer_blocked_on_expired(store):
    tpl = _tpl(BooleanQuestion(id="b", prompt="?"))
    store.save_template(tpl)
    qn = Questionnaire(
        id="exp1", template_id=tpl.id, template_version=1,
        created_at="2019-01-01T00:00:00Z",
        expires_at="2020-01-01T00:00:00Z",
    )
    store.save_questionnaire(qn)

    with pytest.raises(SubmissionLockedError):
        store.upsert_answer("exp1", "b", BooleanAnswer(value=True))


# ---------------------------------------------------------------------------
# Rating/Email round-trip through store
# ---------------------------------------------------------------------------

def test_rating_answer_store_round_trip(store):
    tpl = Template(
        id="tpl_rating", title="Rating test",
        created_at="2026-01-01T00:00:00Z",
        questions=[RatingQuestion(id="r", prompt="Rate it", min_val=1, max_val=5)],
    )
    store.save_template(tpl)
    qn = Questionnaire(
        id="q_rating", template_id="tpl_rating", template_version=1,
        created_at="2026-01-01T00:00:00Z",
        answers={"r": RatingAnswer(value=4)},
    )
    store.save_questionnaire(qn)
    loaded = store.get_questionnaire("q_rating")
    assert loaded is not None
    assert isinstance(loaded.answers["r"], RatingAnswer)
    assert loaded.answers["r"].value == 4


def test_email_answer_store_round_trip(store):
    tpl = Template(
        id="tpl_email", title="Email test",
        created_at="2026-01-01T00:00:00Z",
        questions=[EmailQuestion(id="e", prompt="Email?")],
    )
    store.save_template(tpl)
    qn = Questionnaire(
        id="q_email", template_id="tpl_email", template_version=1,
        created_at="2026-01-01T00:00:00Z",
        answers={"e": EmailAnswer(value="test@example.com")},
    )
    store.save_questionnaire(qn)
    loaded = store.get_questionnaire("q_email")
    assert loaded is not None
    assert isinstance(loaded.answers["e"], EmailAnswer)
    assert loaded.answers["e"].value == "test@example.com"
