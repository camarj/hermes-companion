"""AC-W1-R2 (auth side): host_tokens config + DB seed + verify helper.

The WS endpoint at /api/host/acp uses these to gate connections from
remote `RemoteAcpBackend` clients. Seeding mirrors the agent / team
pattern: config.yaml declares tokens, DB stores them, user edits via
UI (Fase 5) survive restarts.
"""

from pathlib import Path

import config
import database


# ── config.host_tokens() ───────────────────────────────────────────────────

def test_host_tokens_returns_empty_when_unset(monkeypatch):
    monkeypatch.setattr(config, "CONFIG", {})
    assert config.host_tokens() == []


def test_host_tokens_normalises_entries(monkeypatch):
    monkeypatch.setattr(config, "CONFIG", {
        "host_tokens": [
            {"token": "t1", "label": "vps-prod"},
            {"token": "t2", "label": "dev"},
        ],
    })
    out = config.host_tokens()
    assert out == [
        {"token": "t1", "label": "vps-prod"},
        {"token": "t2", "label": "dev"},
    ]


def test_host_tokens_skips_entries_without_token(monkeypatch):
    monkeypatch.setattr(config, "CONFIG", {
        "host_tokens": [
            {"token": "valid", "label": "ok"},
            {"label": "missing token"},  # silently dropped
            {"token": "", "label": "empty token"},  # silently dropped
        ],
    })
    assert [t["token"] for t in config.host_tokens()] == ["valid"]


# ── DB seed + verify ───────────────────────────────────────────────────────

def test_init_db_seeds_configured_host_tokens(temp_db: Path, monkeypatch):
    monkeypatch.setattr(database, "configured_host_tokens", lambda: [
        {"token": "t1", "label": "vps-prod"},
    ])
    database.init_db()

    import sqlite3
    conn = sqlite3.connect(str(temp_db))
    try:
        row = conn.execute(
            "SELECT token, label, last_used_at FROM host_tokens"
        ).fetchone()
    finally:
        conn.close()
    assert row[0] == "t1"
    assert row[1] == "vps-prod"
    assert row[2] is None  # not used yet


def test_seed_host_tokens_is_idempotent(temp_db: Path, monkeypatch):
    monkeypatch.setattr(database, "configured_host_tokens", lambda: [
        {"token": "t1", "label": "vps"},
    ])
    database.init_db()
    database.init_db()
    assert len(database.list_host_tokens()) == 1


def test_verify_host_token_accepts_known(temp_db: Path, monkeypatch):
    monkeypatch.setattr(database, "configured_host_tokens", lambda: [
        {"token": "good", "label": "ok"},
    ])
    database.init_db()

    assert database.verify_host_token("good") is True


def test_verify_host_token_rejects_unknown(temp_db: Path, monkeypatch):
    monkeypatch.setattr(database, "configured_host_tokens", lambda: [
        {"token": "good", "label": "ok"},
    ])
    database.init_db()

    assert database.verify_host_token("nope") is False
    assert database.verify_host_token("") is False


def test_verify_host_token_updates_last_used_at(temp_db: Path, monkeypatch):
    monkeypatch.setattr(database, "configured_host_tokens", lambda: [
        {"token": "good", "label": "ok"},
    ])
    database.init_db()
    assert database.verify_host_token("good") is True

    import sqlite3
    conn = sqlite3.connect(str(temp_db))
    try:
        last_used = conn.execute(
            "SELECT last_used_at FROM host_tokens WHERE token = 'good'"
        ).fetchone()[0]
    finally:
        conn.close()
    assert last_used is not None
