"""AC-W1-D1: First boot creates the new tables idempotently.

Also covers the new columns on `conversations` (agent_id FK,
hermes_session_id). The migration must work on a fresh DB AND on an
existing DB created by an older version of the schema (we simulate
that by creating the legacy schema by hand and then running init_db).
"""

import sqlite3
import uuid
from datetime import datetime, timezone
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


# ── AC-W3-A1: artifacts table ─────────────────────────────────────────────


def test_init_db_creates_artifacts_table(inited_db: Path):
    conn = sqlite3.connect(str(inited_db))
    try:
        cols = {c[1] for c in conn.execute("PRAGMA table_info(artifacts)").fetchall()}
    finally:
        conn.close()
    assert cols >= {
        "id", "conversation_id", "message_id", "name", "rel_path",
        "mime_type", "size_bytes", "content", "file_path", "created_at",
    }


def test_init_db_artifacts_table_is_idempotent(temp_db: Path):
    import database

    database.init_db()
    database.init_db()
    conn = sqlite3.connect(str(temp_db))
    try:
        count = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='artifacts'"
        ).fetchone()[0]
    finally:
        conn.close()
    assert count == 1


def test_init_db_artifacts_check_constraint_enforced(inited_db: Path):
    """Exactly one of content / file_path must be non-null."""
    conn = sqlite3.connect(str(inited_db))
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        artifact_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        # Both NULL → violates CHECK constraint
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO artifacts (id, name, rel_path, mime_type, size_bytes, created_at) "
                "VALUES (?, 'f.txt', 'f.txt', 'text/plain', 10, ?)",
                (artifact_id, now),
            )
    finally:
        conn.close()


# ── AC-W3-T1: tasks table ─────────────────────────────────────────────────


def test_init_db_creates_tasks_table(inited_db: Path):
    conn = sqlite3.connect(str(inited_db))
    try:
        cols = {c[1] for c in conn.execute("PRAGMA table_info(tasks)").fetchall()}
    finally:
        conn.close()
    assert cols >= {
        "id", "user_id", "conversation_id", "agent_id", "parent_task_id",
        "title", "description", "status", "created_at", "updated_at",
    }


def test_init_db_tasks_table_is_idempotent(temp_db: Path):
    database.init_db()
    database.init_db()
    conn = sqlite3.connect(str(temp_db))
    try:
        count = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='tasks'"
        ).fetchone()[0]
    finally:
        conn.close()
    assert count == 1


@pytest.fixture
def task_db(inited_db: Path):
    """inited_db with a seeded user 'u1' so task FK constraints are satisfied."""
    conn = sqlite3.connect(str(inited_db))
    try:
        conn.execute(
            "INSERT OR IGNORE INTO users (id, name, role, is_shared_space) "
            "VALUES ('u1', 'User One', 'tester', 0)"
        )
        conn.commit()
    finally:
        conn.close()
    return inited_db


def test_create_task_returns_pending_row(task_db: Path):
    row = database.create_task(user_id="u1", title="Test task")
    assert row["status"] == "pending"
    assert isinstance(row["id"], str) and len(row["id"]) == 36


def test_get_task_round_trip(task_db: Path):
    created = database.create_task(user_id="u1", title="Round-trip")
    fetched = database.get_task(created["id"])
    assert fetched is not None
    assert fetched["id"] == created["id"]
    assert fetched["title"] == "Round-trip"


def test_list_tasks_returns_user_tasks(task_db: Path):
    database.create_task(user_id="u1", title="Task A")
    database.create_task(user_id="u1", title="Task B")
    tasks = database.list_tasks("u1")
    assert len(tasks) == 2


def test_list_tasks_filter_by_conversation(task_db: Path):
    database.create_task(user_id="u1", title="Conv1 task", conversation_id=None)
    database.create_task(user_id="u1", title="Other task", conversation_id=None)
    task_with_conv = database.create_task(user_id="u1", title="Conv1 task specific")
    conn = sqlite3.connect(str(task_db))
    try:
        conv_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "INSERT INTO conversations (id, user_id, title, created_at, updated_at) "
            "VALUES (?, 'u1', 'C1', ?, ?)", (conv_id, now, now)
        )
        conn.execute(
            "UPDATE tasks SET conversation_id = ? WHERE id = ?",
            (conv_id, task_with_conv["id"])
        )
        conn.commit()
    finally:
        conn.close()
    c1_tasks = database.list_tasks("u1", conversation_id=conv_id)
    assert len(c1_tasks) == 1
    assert c1_tasks[0]["id"] == task_with_conv["id"]


def test_update_task_bumps_updated_at(task_db: Path):
    import time
    created = database.create_task(user_id="u1", title="Updatable")
    time.sleep(0.01)
    updated = database.update_task(created["id"], status="running")
    assert updated is not None
    assert updated["status"] == "running"
    assert updated["updated_at"] >= created["updated_at"]


def test_tasks_status_check_constraint(task_db: Path):
    conn = sqlite3.connect(str(task_db))
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        task_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO tasks (id, user_id, title, status, created_at, updated_at) "
                "VALUES (?, 'u1', 'Bad status', 'exploded', ?, ?)",
                (task_id, now, now),
            )
            conn.commit()
    finally:
        conn.close()


def test_tasks_conversation_on_delete_set_null(inited_db: Path):
    """conversation_id goes NULL when the conversation is deleted (not cascade)."""
    conn = sqlite3.connect(str(inited_db))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        conv_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "INSERT INTO users (id, name, role, is_shared_space) VALUES ('u1','User','tester',0)"
        )
        conn.execute(
            "INSERT INTO conversations (id, user_id, title, created_at, updated_at) "
            "VALUES (?, 'u1', 'Test conv', ?, ?)",
            (conv_id, now, now),
        )
        task_id = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO tasks (id, user_id, conversation_id, title, status, created_at, updated_at) "
            "VALUES (?, 'u1', ?, 'My task', 'pending', ?, ?)",
            (task_id, conv_id, now, now),
        )
        conn.commit()
        conn.execute("DELETE FROM conversations WHERE id = ?", (conv_id,))
        conn.commit()
        row = conn.execute("SELECT conversation_id FROM tasks WHERE id = ?", (task_id,)).fetchone()
        assert row["conversation_id"] is None
    finally:
        conn.close()
