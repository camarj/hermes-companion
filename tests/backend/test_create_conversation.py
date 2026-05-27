"""AC-W1-D3 (data layer): create_conversation honours agent_id FK.

- Defaults to the first enabled agent when omitted.
- Rejects unknown agent ids.
- Auto-binds pre-Fase-2 conversations (NULL agent_id) on migration.
"""

import sqlite3
from pathlib import Path

import pytest

import database


def _seed(monkeypatch, agents: list[dict], users: list[dict] | None = None):
    monkeypatch.setattr(database, "configured_team", lambda: users or [
        {"id": "u1", "name": "U", "role": "", "shared_space": False},
    ])
    monkeypatch.setattr(database, "configured_agents", lambda: agents)


def test_create_conversation_uses_default_agent_when_not_specified(
    temp_db: Path, monkeypatch
):
    _seed(monkeypatch, [{
        "id": "default",
        "label": "Default",
        "type": "hermes",
        "transport": "local-acp",
        "transport_config": {},
        "system_prompt_override": None,
        "enabled": True,
        "created_via": "config",
    }])
    database.init_db()

    conv = database.create_conversation(user_id="u1")

    assert conv["agent_id"] == "default"


def test_create_conversation_accepts_explicit_agent_id(
    temp_db: Path, monkeypatch
):
    _seed(monkeypatch, [
        {"id": "a", "label": "A", "type": "hermes", "transport": "local-acp",
         "transport_config": {}, "system_prompt_override": None,
         "enabled": True, "created_via": "config"},
        {"id": "b", "label": "B", "type": "hermes", "transport": "remote-acp",
         "transport_config": {"url": "wss://b"}, "system_prompt_override": None,
         "enabled": True, "created_via": "config"},
    ])
    database.init_db()

    conv = database.create_conversation(user_id="u1", agent_id="b")

    assert conv["agent_id"] == "b"


def test_create_conversation_rejects_unknown_agent_id(
    temp_db: Path, monkeypatch
):
    _seed(monkeypatch, [{
        "id": "default", "label": "D", "type": "hermes",
        "transport": "local-acp", "transport_config": {},
        "system_prompt_override": None, "enabled": True, "created_via": "config",
    }])
    database.init_db()

    with pytest.raises(ValueError, match="agent_id"):
        database.create_conversation(user_id="u1", agent_id="nonexistent")


def test_create_conversation_skips_disabled_agents_when_picking_default(
    temp_db: Path, monkeypatch
):
    _seed(monkeypatch, [
        {"id": "off", "label": "Off", "type": "hermes", "transport": "local-acp",
         "transport_config": {}, "system_prompt_override": None,
         "enabled": False, "created_via": "config"},
        {"id": "on", "label": "On", "type": "hermes", "transport": "local-acp",
         "transport_config": {}, "system_prompt_override": None,
         "enabled": True, "created_via": "config"},
    ])
    database.init_db()

    conv = database.create_conversation(user_id="u1")

    assert conv["agent_id"] == "on"


def test_legacy_conversations_are_back_filled_on_migration(
    temp_db: Path, monkeypatch
):
    """A row created by an older schema (no agent_id column at all) gets
    auto-bound to the default agent when init_db runs the migration."""
    # Bootstrap a pre-Fase-2 DB by hand.
    conn = sqlite3.connect(str(temp_db))
    try:
        conn.executescript(
            """
            CREATE TABLE conversations (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                title TEXT NOT NULL DEFAULT 'New conversation',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            INSERT INTO conversations VALUES ('legacy-1', 'u1', 'old', '2026-01-01', '2026-01-01');
            """
        )
        conn.commit()
    finally:
        conn.close()

    _seed(monkeypatch, [{
        "id": "default", "label": "Default", "type": "hermes",
        "transport": "local-acp", "transport_config": {},
        "system_prompt_override": None, "enabled": True, "created_via": "config",
    }])
    database.init_db()

    conn = sqlite3.connect(str(temp_db))
    try:
        row = conn.execute(
            "SELECT agent_id FROM conversations WHERE id='legacy-1'"
        ).fetchone()
    finally:
        conn.close()
    assert row[0] == "default"
