"""Audit log: hash chain integrity and tamper detection."""

from __future__ import annotations

from questionnaire.domain.audit import (
    GENESIS_HASH,
    AuditEvent,
    AuditRecord,
    compute_hash,
    verify_chain,
)


def _ev(action: str, payload: dict | None = None) -> AuditEvent:
    return AuditEvent(
        ts="2026-01-01T00:00:00Z",
        actor="alice",
        action=action,
        target_type="thing",
        target_id="x",
        payload=payload or {},
    )


def _build_chain(events: list[AuditEvent]) -> list[AuditRecord]:
    records: list[AuditRecord] = []
    prev = GENESIS_HASH
    for i, ev in enumerate(events, start=1):
        h = compute_hash(prev, ev)
        records.append(AuditRecord(seq=i, event=ev, prev_hash=prev, hash=h))
        prev = h
    return records


def test_well_formed_chain_verifies():
    chain = _build_chain([_ev("create"), _ev("update"), _ev("delete")])
    ok, err = verify_chain(chain)
    assert ok and err is None


def test_tampered_payload_breaks_chain():
    chain = _build_chain([_ev("create"), _ev("update", {"key": "value"})])
    # Tamper with the second record's payload but leave its hash unchanged.
    tampered = chain[1]
    chain[1] = AuditRecord(
        seq=tampered.seq,
        event=AuditEvent(**{**tampered.event.__dict__, "payload": {"key": "EVIL"}}),
        prev_hash=tampered.prev_hash,
        hash=tampered.hash,
    )
    ok, err = verify_chain(chain)
    assert not ok
    assert "hash mismatch" in err


def test_missing_link_breaks_chain():
    chain = _build_chain([_ev("a"), _ev("b"), _ev("c")])
    # Drop the middle record. Now the third record's prev_hash references
    # a non-existent predecessor.
    chain.pop(1)
    ok, err = verify_chain(chain)
    assert not ok
    assert "prev_hash mismatch" in err


def test_first_record_chains_from_genesis():
    chain = _build_chain([_ev("first")])
    assert chain[0].prev_hash == GENESIS_HASH


def test_canonical_payload_means_key_order_does_not_matter():
    a = compute_hash(GENESIS_HASH, _ev("x", {"a": 1, "b": 2}))
    b = compute_hash(GENESIS_HASH, _ev("x", {"b": 2, "a": 1}))
    assert a == b
