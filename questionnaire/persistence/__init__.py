"""Persistence layer.

``SqlStore`` is the active store. ``JsonStore`` is kept readable as the
migration source.
"""

from .sql_store import (
    SqlStore,
    StoreError,
    SubmissionLockedError,
    TemplateStats,
    WebhookConfig,
    default_db_url,
)
from .store import JsonStore, default_db_path

__all__ = [
    "SqlStore",
    "StoreError",
    "SubmissionLockedError",
    "TemplateStats",
    "WebhookConfig",
    "default_db_url",
    "JsonStore",
    "default_db_path",
]


def default_store() -> SqlStore:
    return SqlStore(default_db_url())
