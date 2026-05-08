"""JSON-file-backed legacy store.

Kept as the *source* for ``qst migrate``. No new code should write to JSON;
``SqlStore`` is the active store. Existing JSON files remain readable
indefinitely so that previously-shipped data can be ingested.
"""

from __future__ import annotations

import os
from pathlib import Path

from ..domain.types import Database


class JsonStore:
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


# Backwards-compatible alias for older imports.
Store = JsonStore


def default_db_path() -> Path:
    return Path("data") / "db.json"
