"""AC-W1-D1: First boot creates the new tables idempotently.

Also covers the new columns on `conversations` (agent_id FK,
hermes_session_id). The migration must work on a fresh DB AND on an
existing DB created by an older version of the schema (we simulate
that by creating the legacy schema by hand and then running init_db).
"""

import sqlite3
from pathlib import Path

import pytest

import database


# ── Fresh-DB tests ─────────────────────────────────────────────────────────

def test_init_db_creates_agent_instances_table(inited_db: Path):
    conn = sqlite3.connect(str(inited_db))
    try:
        cols = {c[1] for c in conn.execute("PRAGMA table_info(agent_instances)").fetchall()}
    finally:
        conn.close()
    assert cols >= {
        "id", "label", "type", "transport", "transport_config_json",
        "system_prompt_override", "enabled", "created_via",
        "created_at", "updated_at",
    }


def test_init_db_creates_host_tokens_table(inited_db: Path):
    conn = sqlite3.connect(str(inited_db))
    try:
        cols = {c[1] for c in conn.execute("PRAGMA table_info(host_tokens)").fetchall()}
    finally:
        conn.close()
    assert cols >= {"token", "label", "created_at", "last_used_at"}


def test_init_db_adds_agent_id_and_hermes_session_id_to_conversations(inited_db: Path):
    conn = sqlite3.connect(str(inited_db))
    try:
        cols = {c[1] for c in conn.execute("PRAGMA table_info(conversations)").fetchall()}
    finally:
        conn.close()
    assert "agent_id" in cols
    assert "hermes_session_id" in cols


def test_init_db_is_idempotent(temp_db: Path):
    # Run twice — second call must not raise or duplicate the table.
    database.init_db()
    database.init_db()
    conn = sqlite3.connect(str(temp_db))
    try:
        count = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='agent_instances'"
        ).fetchone()[0]
    finally:
        conn.close()
    assert count == 1


# ── Existing-DB migration tests ────────────────────────────────────────────

def test_init_db_migrates_legacy_conversations_table(temp_db: Path):
    # Simulate an older companion.db that has conversations without
    # agent_id / hermes_session_id columns yet.
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
            INSERT INTO conversations (id, user_id, title, created_at, updated_at)
            VALUES ('c1', 'u1', 'Pre-migration', '2026-01-01', '2026-01-01');
            """
        )
        conn.commit()
    finally:
        conn.close()

    database.init_db()

    conn = sqlite3.connect(str(temp_db))
    try:
        cols = {c[1] for c in conn.execute("PRAGMA table_info(conversations)").fetchall()}
        # Existing row survives + is_visible.
        row = conn.execute("SELECT id, agent_id, hermes_session_id FROM conversations").fetchone()
    finally:
        conn.close()
    assert "agent_id" in cols
    assert "hermes_session_id" in cols
    assert row[0] == "c1"
    # No agent_id has been assigned yet — that's Cycle 3 (AC-W1-D3).
    # Just confirm the columns are nullable and the legacy row didn't blow up.
    assert row[2] is None
