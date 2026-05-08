"""End-to-end HTTP API tests using FastAPI's TestClient.

Exercises the full happy path: create template → start questionnaire →
upsert answers → submit → list/filter → audit → GDPR.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from questionnaire.api.app import create_app
from questionnaire.domain import encryption
from questionnaire.persistence.sql_store import SqlStore


@pytest.fixture
def client(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("QST_PII_KEY", Fernet.generate_key().decode())
    encryption.reset_key_cache()
    store = SqlStore(f"sqlite:///{tmp_path / 'api.sqlite'}")
    app = create_app(store=store)
    return TestClient(app), store


def test_full_flow(client):
    c, store = client
    # 1) Create a template
    body = {
        "title": "Smoke",
        "questions": [
            {"id": "color", "type": "single_select",
             "prompt": "?", "options": ["red", "green", "blue"]},
            {"id": "notes", "type": "free_text", "prompt": "?"},
        ],
    }
    r = c.post("/templates", json=body, headers={"X-Actor": "alice"})
    assert r.status_code == 201, r.text
    tpl = r.json()
    assert tpl["version"] == 1

    # 2) Start a questionnaire
    r = c.post("/questionnaires", json={"template_id": tpl["id"], "respondent_id": "user42"})
    assert r.status_code == 201
    qn_id = r.json()["id"]

    # 3) Upsert answers
    r = c.put(
        f"/questionnaires/{qn_id}/answers/color",
        json={"answer": {"type": "single_select", "value": "red"}},
    )
    assert r.status_code == 200
    r = c.put(
        f"/questionnaires/{qn_id}/answers/notes",
        json={"answer": {"type": "free_text", "value": "hi"}},
    )
    assert r.status_code == 200

    # 4) Submit
    r = c.post(f"/questionnaires/{qn_id}/submit")
    assert r.status_code == 200
    assert r.json()["submitted_at"] is not None

    # 5) Editing after submit returns 409
    r = c.put(
        f"/questionnaires/{qn_id}/answers/color",
        json={"answer": {"type": "single_select", "value": "blue"}},
    )
    assert r.status_code == 409

    # 6) List with filters
    r = c.get("/questionnaires", params={"includes": ["color=red"]})
    assert r.status_code == 200
    assert any(q["id"] == qn_id for q in r.json())

    # 7) Audit log + verify
    r = c.get("/audit")
    assert r.status_code == 200
    assert any(e["action"] == "questionnaire.submit" for e in r.json())
    r = c.post("/audit/verify")
    assert r.status_code == 200 and r.json()["ok"] is True

    # 8) GDPR export then delete
    r = c.get("/respondents/user42/export")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/zip"
    assert len(r.content) > 0

    r = c.delete("/respondents/user42")
    assert r.status_code == 200
    assert r.json()["deleted_questionnaires"] >= 1


def test_invalid_filter_returns_400(client):
    c, store = client
    body = {
        "title": "X",
        "questions": [
            {"id": "txt", "type": "free_text", "prompt": "?"},
        ],
    }
    c.post("/templates", json=body)
    # Filtering on a free-text question should be rejected.
    r = c.get("/questionnaires", params={"includes": ["txt=hi"]})
    assert r.status_code == 400


def test_missing_template_returns_404(client):
    c, _ = client
    r = c.get("/templates/does-not-exist")
    assert r.status_code == 404


def test_template_versioning_via_api(client):
    c, store = client
    body = {
        "title": "V",
        "questions": [
            {"id": "b", "type": "boolean", "prompt": "v1"},
        ],
    }
    r = c.post("/templates", json=body)
    tid = r.json()["id"]

    # Re-post with the same id → new version.
    body2 = {
        "id": tid,
        "title": "V",
        "questions": [
            {"id": "b", "type": "boolean", "prompt": "v2"},
        ],
    }
    r = c.post("/templates", json=body2)
    assert r.status_code == 201
    assert r.json()["version"] == 2

    r = c.get(f"/templates/{tid}/versions")
    assert r.json() == [1, 2]

    r = c.get(f"/templates/{tid}", params={"version": 1})
    assert r.json()["questions"][0]["prompt"] == "v1"
