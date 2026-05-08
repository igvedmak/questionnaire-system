"""Migrate the legacy JSON database into SQLite.

The original ``data/db.json`` is read with the legacy ``JsonStore``, then
each template and questionnaire is replayed into the new ``SqlStore``.
The JSON file is **not** deleted — it remains as a backup.
"""

from __future__ import annotations

from dataclasses import dataclass

from .sql_store import SqlStore
from .store import JsonStore


@dataclass
class MigrationResult:
    templates_migrated: int
    questionnaires_migrated: int
    questionnaires_submitted: int


def migrate_json_to_sql(json_store: JsonStore, sql_store: SqlStore) -> MigrationResult:
    db = json_store.load()
    n_templates = 0
    n_questionnaires = 0
    n_submitted = 0

    # Templates first so questionnaires can reference them.
    for tpl in db.templates.values():
        sql_store.save_template(tpl, actor="migrate")
        n_templates += 1

    for qn in db.questionnaires.values():
        # Submitted state is restored after the save (save refuses to write
        # to a submitted questionnaire — so we strip it, save, then submit).
        was_submitted = qn.is_submitted
        snap = qn.model_copy(update={"submitted_at": None})
        sql_store.save_questionnaire(snap, actor="migrate")
        if was_submitted:
            sql_store.submit_questionnaire(qn.id, actor="migrate")
            n_submitted += 1
        n_questionnaires += 1

    return MigrationResult(
        templates_migrated=n_templates,
        questionnaires_migrated=n_questionnaires,
        questionnaires_submitted=n_submitted,
    )
