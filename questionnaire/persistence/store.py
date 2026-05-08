"""JSON-file-backed store for the entire database.

A single file holds all templates and questionnaires. Writes are atomic
(write to a sibling tmp file, then rename) so a crash mid-write can't
corrupt the DB.

Concurrency: this is a single-process CLI; no locking. If the file is
modified externally between load and save, the in-memory snapshot wins.
For an assignment-scoped task this is fine; a real system would use a DB.
"""

from __future__ import annotations

import os
from pathlib import Path

from ..domain.types import Database


class Store:
    def __init__(self, path: Path | str):
        self.path = Path(path)

    def load(self) -> Database:
        if not self.path.exists():
            return Database()
        text = self.path.read_text(encoding="utf-8")
        if not text.strip():
            return Database()
        return Database.model_validate_json(text)

    def save(self, db: Database) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(db.model_dump_json(indent=2), encoding="utf-8")
        os.replace(tmp, self.path)


def default_db_path() -> Path:
    """Default DB location: ./data/db.json relative to current working directory."""
    return Path("data") / "db.json"
