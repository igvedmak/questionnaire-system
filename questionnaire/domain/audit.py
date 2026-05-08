"""Tamper-evident audit log entries.

Every state-changing operation appends a row whose hash chains the
previous row's hash with the canonical JSON of the event payload:

    hash_n = SHA-256(prev_hash || canonical_json(payload_n))

Verification (``verify_chain``) recomputes each hash and confirms the
chain end-to-end. Any altered or missing row breaks the chain.

This is *not* an alternative to access control or encryption — it's an
"is the log intact?" check that an auditor can run independently.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable

GENESIS_HASH = "0" * 64


@dataclass(frozen=True)
class AuditEvent:
    """The payload portion of an audit row (everything that gets hashed)."""
    ts: str
    actor: str | None
    action: str
    target_type: str | None
    target_id: str | None
    payload: dict[str, Any]


@dataclass(frozen=True)
class AuditRecord:
    """An audit row as persisted: payload + the chained hashes."""
    seq: int
    event: AuditEvent
    prev_hash: str
    hash: str


def _canonical_json(obj: Any) -> str:
    """Stable JSON: sorted keys, no extraneous whitespace, default UTF-8."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def compute_hash(prev_hash: str, event: AuditEvent) -> str:
    """SHA-256 over the previous hash bytes followed by the canonical JSON."""
    payload = {
        "ts": event.ts,
        "actor": event.actor,
        "action": event.action,
        "target_type": event.target_type,
        "target_id": event.target_id,
        "payload": event.payload,
    }
    h = hashlib.sha256()
    h.update(bytes.fromhex(prev_hash) if all(c in "0123456789abcdef" for c in prev_hash) and len(prev_hash) == 64 else prev_hash.encode())
    h.update(b"\n")
    h.update(_canonical_json(payload).encode("utf-8"))
    return h.hexdigest()


def verify_chain(records: Iterable[AuditRecord]) -> tuple[bool, str | None]:
    """Walk the chain and confirm every hash. Returns (ok, error_message)."""
    expected_prev = GENESIS_HASH
    for rec in sorted(records, key=lambda r: r.seq):
        if rec.prev_hash != expected_prev:
            return False, f"row seq={rec.seq}: prev_hash mismatch"
        expected_hash = compute_hash(rec.prev_hash, rec.event)
        if rec.hash != expected_hash:
            return False, f"row seq={rec.seq}: hash mismatch (tampered payload?)"
        expected_prev = rec.hash
    return True, None
