"""Shared fixtures for backend tests.

The production code reads `database.DB_PATH` at every connection, so we
can swap it per-test with `monkeypatch`. The `temp_db` fixture also
neutralises the YAML-driven seeds so tests start from a known empty
state — individual tests opt into seeding what they need.
"""

from pathlib import Path

import pytest


@pytest.fixture
def temp_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Patch `database.DB_PATH` to a fresh tempfile; neutralise seeders."""
    import database

    db_file = tmp_path / "test_companion.db"
    monkeypatch.setattr(database, "DB_PATH", db_file)

    # Default seeds: empty. Tests that need users/agents seeded patch these.
    monkeypatch.setattr(database, "configured_team", lambda: [])
    if hasattr(database, "configured_agents"):
        monkeypatch.setattr(database, "configured_agents", lambda: [])
    return db_file


@pytest.fixture
def inited_db(temp_db: Path) -> Path:
    """temp_db + `init_db()` already called, so schema is in place."""
    import database

    database.init_db()
    return temp_db


@pytest.fixture
def seeded_db(temp_db: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """temp_db with one default user `u1` and one default agent `default`.

    Useful for HTTP tests that need an authenticated request against a
    backend with the minimum seeded data.
    """
    import database

    monkeypatch.setattr(database, "configured_team", lambda: [
        {"id": "u1", "name": "User One", "role": "tester", "shared_space": False},
    ])
    monkeypatch.setattr(database, "configured_agents", lambda: [
        {
            "id": "default",
            "label": "Default Hermes",
            "type": "hermes",
            "transport": "local-acp",
            "transport_config": {},
            "system_prompt_override": None,
            "enabled": True,
            "created_via": "config",
        },
    ])
    database.init_db()
    return temp_db


@pytest.fixture
def client(seeded_db):
    """FastAPI TestClient authenticated as `u1` against a fresh tempfile DB."""
    from fastapi.testclient import TestClient

    import main

    test_client = TestClient(main.app)
    test_client.cookies.set("companion_user", "u1")
    return test_client
