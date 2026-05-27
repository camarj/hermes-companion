"""AC-W1-D2 (DB side): `init_db` seeds agent_instances from configured_agents.

Idempotent: re-running init_db doesn't duplicate or modify existing rows.
"""

from pathlib import Path

import pytest

import database


def _seed_one(monkeypatch, **overrides):
    base = {
        "id": "local-default",
        "label": "Hermes",
        "type": "hermes",
        "transport": "local-acp",
        "transport_config": {},
        "system_prompt_override": None,
        "enabled": True,
        "created_via": "config",
    }
    base.update(overrides)
    monkeypatch.setattr(database, "configured_agents", lambda: [base])
    return base


def test_init_db_seeds_configured_agent(temp_db: Path, monkeypatch):
    _seed_one(monkeypatch)

    database.init_db()

    rows = database.list_agent_instances()
    assert len(rows) == 1
    assert rows[0]["id"] == "local-default"
    assert rows[0]["transport"] == "local-acp"
    assert rows[0]["created_via"] == "config"
    assert rows[0]["enabled"] is True


def test_init_db_seeding_is_idempotent(temp_db: Path, monkeypatch):
    _seed_one(monkeypatch)
    database.init_db()
    database.init_db()

    rows = database.list_agent_instances()
    assert len(rows) == 1


def test_init_db_preserves_user_modifications(temp_db: Path, monkeypatch):
    """If an existing row has a user-edited label, re-seeding does NOT
    revert it to the config value. (Mirrors how `_seed_users` behaves.)"""
    _seed_one(monkeypatch, label="Original from config")
    database.init_db()

    # User edits the label via the future UI.
    database.update_agent_instance("local-default", label="User-edited")

    # Re-seed: must not clobber the user's edit.
    database.init_db()

    row = database.get_agent_instance("local-default")
    assert row["label"] == "User-edited"


def test_init_db_seeds_multiple_agents(temp_db: Path, monkeypatch):
    monkeypatch.setattr(database, "configured_agents", lambda: [
        {
            "id": "local",
            "label": "Local",
            "type": "hermes",
            "transport": "local-acp",
            "transport_config": {},
            "system_prompt_override": None,
            "enabled": True,
            "created_via": "config",
        },
        {
            "id": "vps",
            "label": "VPS",
            "type": "hermes",
            "transport": "remote-acp",
            "transport_config": {"url": "wss://vps/api/host/acp", "token": "env:T"},
            "system_prompt_override": None,
            "enabled": True,
            "created_via": "config",
        },
    ])

    database.init_db()

    rows = database.list_agent_instances()
    ids = {r["id"] for r in rows}
    assert ids == {"local", "vps"}
