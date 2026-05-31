"""
SQLite store for users, conversations, messages, and (optionally) enrolled
faces. Schema is created on first boot and the team table is seeded from
`config.yaml`.
"""

import json
import mimetypes
import os
import shutil
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from config import agents as configured_agents
from config import data_dir as _data_dir
from config import host_tokens as configured_host_tokens
from config import team as configured_team

ARTIFACT_INLINE_MAX_BYTES = 1 * 1024 * 1024  # 1 MB; <= inline BLOB, > stored on disk

DB_PATH = Path(__file__).parent / "companion.db"


def get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    conn = get_db()
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                role TEXT NOT NULL,
                is_shared_space INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                title TEXT NOT NULL DEFAULT 'New conversation',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS messages (
                id TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('user', 'assistant', 'system')),
                content TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_conversations_user ON conversations(user_id, updated_at DESC);
            CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(conversation_id, created_at ASC);

            CREATE TABLE IF NOT EXISTS known_faces (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                owner_id TEXT NOT NULL,
                name TEXT NOT NULL,
                embedding BLOB NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (owner_id) REFERENCES users(id)
            );
            CREATE INDEX IF NOT EXISTS idx_known_faces_name ON known_faces(name);

            -- Wave 1 (Fase 2): polymorphic agent registry.
            CREATE TABLE IF NOT EXISTS agent_instances (
                id                      TEXT PRIMARY KEY,
                label                   TEXT NOT NULL,
                type                    TEXT NOT NULL,
                transport               TEXT NOT NULL,
                transport_config_json   TEXT NOT NULL,
                system_prompt_override  TEXT,
                enabled                 INTEGER NOT NULL DEFAULT 1,
                created_via             TEXT NOT NULL,
                created_at              TEXT NOT NULL,
                updated_at              TEXT NOT NULL
            );

            -- Wave 1 (Fase 3): bearer tokens for host-mode sidecar auth.
            -- Created early so the DB migration is one-shot.
            CREATE TABLE IF NOT EXISTS host_tokens (
                token         TEXT PRIMARY KEY,
                label         TEXT NOT NULL,
                created_at    TEXT NOT NULL,
                last_used_at  TEXT
            );

            -- Wave 3 (A1): agent-produced file artifacts.
            CREATE TABLE IF NOT EXISTS artifacts (
                id                  TEXT PRIMARY KEY,
                conversation_id     TEXT,
                message_id          TEXT,
                -- task_id has NO FK to tasks(id): the artifacts table predates tasks
                -- (A1 shipped first) and SQLite cannot ADD CONSTRAINT retroactively
                -- without a full table rebuild. The link is enforced in application
                -- code when task-scoped artifacts land (T2). Intentional omission.
                task_id             TEXT,
                name                TEXT NOT NULL,
                rel_path            TEXT NOT NULL,
                mime_type           TEXT NOT NULL,
                size_bytes          INTEGER NOT NULL,
                content             BLOB,
                file_path           TEXT,
                created_by_agent_id TEXT,
                created_at          TEXT NOT NULL,
                FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE,
                FOREIGN KEY (message_id)      REFERENCES messages(id)      ON DELETE CASCADE,
                FOREIGN KEY (created_by_agent_id) REFERENCES agent_instances(id),
                CHECK ((content IS NOT NULL) <> (file_path IS NOT NULL))
            );
            CREATE INDEX IF NOT EXISTS idx_artifacts_conv ON artifacts(conversation_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_artifacts_msg  ON artifacts(message_id);

            -- Wave 3 (T1): tasks as a first-class entity.
            -- conversation_id uses ON DELETE SET NULL — a task outlives a deleted
            -- conversation, unlike artifacts which cascade. Deliberate lifecycle choice.
            CREATE TABLE IF NOT EXISTS tasks (
                id               TEXT PRIMARY KEY,
                user_id          TEXT NOT NULL,
                conversation_id  TEXT,
                agent_id         TEXT,
                parent_task_id   TEXT,
                title            TEXT NOT NULL,
                description      TEXT,
                status           TEXT NOT NULL DEFAULT 'pending'
                                   CHECK (status IN ('pending','running','done','failed','cancelled')),
                created_at       TEXT NOT NULL,
                updated_at       TEXT NOT NULL,
                FOREIGN KEY (user_id)         REFERENCES users(id),
                FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE SET NULL,
                FOREIGN KEY (agent_id)        REFERENCES agent_instances(id),
                FOREIGN KEY (parent_task_id)  REFERENCES tasks(id) ON DELETE SET NULL
            );
            CREATE INDEX IF NOT EXISTS idx_tasks_user ON tasks(user_id, updated_at DESC);
            CREATE INDEX IF NOT EXISTS idx_tasks_conv ON tasks(conversation_id, created_at DESC);
        """)

        # ALTER existing conversations table for upgrades from pre-Fase-2 DBs.
        _add_column_if_missing(
            conn, "conversations",
            "agent_id TEXT REFERENCES agent_instances(id)",
        )
        _add_column_if_missing(
            conn, "conversations",
            "hermes_session_id TEXT",
        )

        _seed_users(conn)
        _seed_agents(conn)
        _seed_host_tokens(conn)
        _backfill_legacy_conversations(conn)
        conn.commit()
    finally:
        conn.close()


def _seed_host_tokens(conn) -> None:
    """Insert configured host_tokens that aren't in the DB yet (idempotent)."""
    for entry in configured_host_tokens():
        token = entry.get("token")
        if not token:
            continue
        existing = conn.execute(
            "SELECT token FROM host_tokens WHERE token = ?", (token,),
        ).fetchone()
        if existing:
            continue
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "INSERT INTO host_tokens (token, label, created_at, last_used_at) "
            "VALUES (?, ?, ?, NULL)",
            (token, entry.get("label") or token, now),
        )


def _backfill_legacy_conversations(conn) -> None:
    """Bind pre-Fase-2 conversations (agent_id IS NULL) to the default agent.

    No-op when there are no legacy rows or no agent is configured.
    """
    default = _resolve_default_agent_id(conn)
    if not default:
        return
    conn.execute(
        "UPDATE conversations SET agent_id = ? WHERE agent_id IS NULL",
        (default,),
    )


def _seed_agents(conn) -> None:
    """Insert configured agent instances that aren't in the DB yet.

    Existing rows are preserved verbatim so user edits via the UI
    (Fase 4) survive a server restart.
    """
    for entry in configured_agents():
        if not entry.get("id"):
            continue
        existing = conn.execute(
            "SELECT id FROM agent_instances WHERE id = ?", (entry["id"],),
        ).fetchone()
        if existing:
            continue
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            """
            INSERT INTO agent_instances
                (id, label, type, transport, transport_config_json,
                 system_prompt_override, enabled, created_via, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                entry["id"],
                entry["label"],
                entry["type"],
                entry["transport"],
                json.dumps(entry.get("transport_config") or {}),
                entry.get("system_prompt_override"),
                int(bool(entry.get("enabled", True))),
                entry.get("created_via", "config"),
                now,
                now,
            ),
        )


def _add_column_if_missing(conn, table: str, column_def: str) -> None:
    """Idempotent ADD COLUMN. SQLite's ALTER doesn't have IF NOT EXISTS."""
    col_name = column_def.split()[0]
    existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if col_name not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column_def}")


def _seed_users(conn):
    """Insert any team members from config.yaml that don't exist yet.

    Existing users are not modified — edit them directly or delete the DB
    file (`companion.db`) to re-seed from scratch.
    """
    for member in configured_team():
        existing = conn.execute(
            "SELECT id FROM users WHERE id = ?", (member["id"],),
        ).fetchone()
        if existing:
            continue
        conn.execute(
            "INSERT INTO users (id, name, role, is_shared_space) VALUES (?, ?, ?, ?)",
            (member["id"], member["name"], member["role"], int(member["shared_space"])),
        )


# ── User operations ────────────────────────────────────────────────────────

def get_user(user_id: str) -> Optional[dict]:
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return _user_row(row) if row else None
    finally:
        conn.close()


def list_users() -> list[dict]:
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT * FROM users ORDER BY is_shared_space, name"
        ).fetchall()
        return [_user_row(r) for r in rows]
    finally:
        conn.close()


def _user_row(row) -> dict:
    """Normalize a user row. Keeps `is_shared_space` as the canonical key but
    also exposes `is_reunion` as a back-compat alias used in older frontend
    code paths (kept until the frontend is fully migrated)."""
    d = dict(row)
    d["is_shared_space"] = bool(d.get("is_shared_space", 0))
    d["is_reunion"] = d["is_shared_space"]
    return d


# ── Conversation operations ────────────────────────────────────────────────

def create_conversation(
    user_id: str,
    title: str = "New conversation",
    agent_id: Optional[str] = None,
) -> dict:
    conn = get_db()
    try:
        if agent_id is None:
            agent_id = _resolve_default_agent_id(conn)
        else:
            exists = conn.execute(
                "SELECT 1 FROM agent_instances WHERE id = ?", (agent_id,),
            ).fetchone()
            if not exists:
                raise ValueError(f"unknown agent_id: {agent_id!r}")

        conv_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "INSERT INTO conversations (id, user_id, title, agent_id, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (conv_id, user_id, title, agent_id, now, now),
        )
        conn.commit()
        return {
            "id": conv_id, "user_id": user_id, "title": title,
            "agent_id": agent_id,
            "created_at": now, "updated_at": now,
        }
    finally:
        conn.close()


def _resolve_default_agent_id(conn) -> Optional[str]:
    """First enabled agent by `created_at` ASC, or None if registry is empty."""
    row = conn.execute(
        "SELECT id FROM agent_instances WHERE enabled = 1 "
        "ORDER BY created_at ASC LIMIT 1"
    ).fetchone()
    return row[0] if row else None


def get_conversation(conv_id: str) -> Optional[dict]:
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM conversations WHERE id = ?", (conv_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def list_conversations(user_id: str) -> list[dict]:
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT * FROM conversations WHERE user_id = ? ORDER BY updated_at DESC",
            (user_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def update_conversation_title(conv_id: str, title: str) -> bool:
    conn = get_db()
    try:
        now = datetime.now(timezone.utc).isoformat()
        cursor = conn.execute(
            "UPDATE conversations SET title = ?, updated_at = ? WHERE id = ?",
            (title, now, conv_id),
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def touch_conversation(conv_id: str):
    conn = get_db()
    try:
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "UPDATE conversations SET updated_at = ? WHERE id = ?",
            (now, conv_id),
        )
        conn.commit()
    finally:
        conn.close()


def get_conversation_session_id(conv_id: str) -> Optional[str]:
    """AC-W1-D4: return the agent's native session id for resume, or None."""
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT hermes_session_id FROM conversations WHERE id = ?",
            (conv_id,),
        ).fetchone()
    finally:
        conn.close()
    return row[0] if row else None


def update_conversation_session_id(conv_id: str, session_id: str) -> bool:
    """AC-W1-D4: persist the session id the agent reported on first turn."""
    conn = get_db()
    try:
        cursor = conn.execute(
            "UPDATE conversations SET hermes_session_id = ? WHERE id = ?",
            (session_id, conv_id),
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def delete_conversation(conv_id: str) -> bool:
    from config import workdir_for_conversation as _workdir_for_conversation
    conn = get_db()
    try:
        file_paths = [
            row[0] for row in conn.execute(
                "SELECT file_path FROM artifacts WHERE conversation_id = ? AND file_path IS NOT NULL",
                (conv_id,),
            ).fetchall()
        ]
        cursor = conn.execute("DELETE FROM conversations WHERE id = ?", (conv_id,))
        conn.commit()
        for fp in file_paths:
            try:
                os.unlink(fp)
            except OSError:
                pass
        # FIX 1: also remove the per-conversation managed workdir if it exists.
        workdir = _data_dir() / "workdirs" / conv_id
        if workdir.is_dir():
            shutil.rmtree(workdir, ignore_errors=True)
        return cursor.rowcount > 0
    finally:
        conn.close()


# ── Message operations ─────────────────────────────────────────────────────

def add_message(conversation_id: str, role: str, content: str) -> dict:
    conn = get_db()
    try:
        msg_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "INSERT INTO messages (id, conversation_id, role, content, created_at) VALUES (?, ?, ?, ?, ?)",
            (msg_id, conversation_id, role, content, now),
        )
        conn.commit()
        if role == "user":
            conv = conn.execute(
                "SELECT title FROM conversations WHERE id = ?", (conversation_id,),
            ).fetchone()
            if conv and conv["title"] == "New conversation":
                title = content[:60].strip()
                if len(content) > 60:
                    title += "..."
                conn.execute(
                    "UPDATE conversations SET title = ? WHERE id = ?",
                    (title, conversation_id),
                )
                conn.commit()
        return {"id": msg_id, "conversation_id": conversation_id, "role": role, "content": content, "created_at": now}
    finally:
        conn.close()


def get_messages(conversation_id: str) -> list[dict]:
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT * FROM messages WHERE conversation_id = ? ORDER BY created_at ASC",
            (conversation_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_conversation_context(conversation_id: str, max_messages: int = 20) -> list[dict]:
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT * FROM messages WHERE conversation_id = ? ORDER BY created_at DESC LIMIT ?",
            (conversation_id, max_messages),
        ).fetchall()
        return [dict(r) for r in reversed(rows)]
    finally:
        conn.close()


# ── Agent instances (Wave 1, Fase 2) ───────────────────────────────────────

def _agent_row(row) -> dict:
    d = dict(row)
    d["enabled"] = bool(d.get("enabled", 1))
    d["transport_config"] = json.loads(d.pop("transport_config_json") or "{}")
    return d


def list_agent_instances() -> list[dict]:
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT * FROM agent_instances ORDER BY created_at ASC"
        ).fetchall()
        return [_agent_row(r) for r in rows]
    finally:
        conn.close()


def get_agent_instance(agent_id: str) -> Optional[dict]:
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT * FROM agent_instances WHERE id = ?", (agent_id,),
        ).fetchone()
        return _agent_row(row) if row else None
    finally:
        conn.close()


def create_agent_instance(
    *,
    id: str,
    label: str,
    type: str = "hermes",
    transport: str = "local-acp",
    transport_config: Optional[dict] = None,
    system_prompt_override: Optional[str] = None,
    enabled: bool = True,
    created_via: str = "user",
) -> dict:
    conn = get_db()
    try:
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            """
            INSERT INTO agent_instances
                (id, label, type, transport, transport_config_json,
                 system_prompt_override, enabled, created_via, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                id, label, type, transport,
                json.dumps(transport_config or {}),
                system_prompt_override,
                int(enabled), created_via, now, now,
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return get_agent_instance(id)  # type: ignore[return-value]


def update_agent_instance(
    agent_id: str,
    *,
    label: Optional[str] = None,
    transport_config: Optional[dict] = None,
    system_prompt_override: Optional[str] = None,
    enabled: Optional[bool] = None,
) -> Optional[dict]:
    sets: list[str] = []
    args: list = []
    if label is not None:
        sets.append("label = ?")
        args.append(label)
    if transport_config is not None:
        sets.append("transport_config_json = ?")
        args.append(json.dumps(transport_config))
    if system_prompt_override is not None:
        sets.append("system_prompt_override = ?")
        args.append(system_prompt_override)
    if enabled is not None:
        sets.append("enabled = ?")
        args.append(int(enabled))
    if not sets:
        return get_agent_instance(agent_id)

    sets.append("updated_at = ?")
    args.append(datetime.now(timezone.utc).isoformat())
    args.append(agent_id)

    conn = get_db()
    try:
        cursor = conn.execute(
            f"UPDATE agent_instances SET {', '.join(sets)} WHERE id = ?",
            args,
        )
        conn.commit()
        if cursor.rowcount == 0:
            return None
    finally:
        conn.close()
    return get_agent_instance(agent_id)


def delete_agent_instance(agent_id: str) -> bool:
    conn = get_db()
    try:
        cursor = conn.execute("DELETE FROM agent_instances WHERE id = ?", (agent_id,))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def count_conversations_for_agent(agent_id: str) -> int:
    conn = get_db()
    try:
        return conn.execute(
            "SELECT COUNT(*) FROM conversations WHERE agent_id = ?",
            (agent_id,),
        ).fetchone()[0]
    finally:
        conn.close()


# ── Host tokens (Wave 1, Fase 3) ───────────────────────────────────────────

def list_host_tokens() -> list[dict]:
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT token, label, created_at, last_used_at FROM host_tokens "
            "ORDER BY created_at ASC"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def verify_host_token(token: str) -> bool:
    """Return True if `token` is registered; record the access timestamp.

    Empty / falsy tokens are rejected without touching the DB.
    """
    if not token:
        return False
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT token FROM host_tokens WHERE token = ?", (token,),
        ).fetchone()
        if not row:
            return False
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "UPDATE host_tokens SET last_used_at = ? WHERE token = ?",
            (now, token),
        )
        conn.commit()
        return True
    finally:
        conn.close()


# ── Known faces (vision recognition) ───────────────────────────────────────

def add_known_face(owner_id: str, name: str, embedding_bytes: bytes) -> dict:
    conn = get_db()
    try:
        now = datetime.now(timezone.utc).isoformat()
        cursor = conn.execute(
            "INSERT INTO known_faces (owner_id, name, embedding, created_at) VALUES (?, ?, ?, ?)",
            (owner_id, name, embedding_bytes, now),
        )
        conn.commit()
        return {"id": cursor.lastrowid, "owner_id": owner_id, "name": name, "created_at": now}
    finally:
        conn.close()


def list_known_faces(include_embeddings: bool = False) -> list[dict]:
    conn = get_db()
    try:
        cols = "id, owner_id, name, created_at" + (", embedding" if include_embeddings else "")
        rows = conn.execute(
            f"SELECT {cols} FROM known_faces ORDER BY name, created_at"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def delete_known_face(face_id: int) -> bool:
    conn = get_db()
    try:
        cursor = conn.execute("DELETE FROM known_faces WHERE id = ?", (face_id,))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def delete_known_faces_by_name(name: str) -> int:
    conn = get_db()
    try:
        cursor = conn.execute("DELETE FROM known_faces WHERE name = ?", (name,))
        conn.commit()
        return cursor.rowcount
    finally:
        conn.close()


# ── Artifacts (Wave 3, A1) ─────────────────────────────────────────────────

def create_artifact(
    *,
    name: str,
    rel_path: str,
    content_bytes: bytes,
    conversation_id: Optional[str] = None,
    message_id: Optional[str] = None,
    created_by_agent_id: Optional[str] = None,
) -> dict:
    """Persist a captured artifact.

    Files <= ARTIFACT_INLINE_MAX_BYTES are stored as BLOB; larger files are
    copied into DATA_DIR/<conversation_id>/<artifact_id>/<name> and their
    path is stored instead.
    """
    artifact_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    size_bytes = len(content_bytes)

    mime_type, _ = mimetypes.guess_type(name)
    mime_type = mime_type or "application/octet-stream"

    if size_bytes <= ARTIFACT_INLINE_MAX_BYTES:
        content = content_bytes
        file_path: Optional[str] = None
    else:
        bucket = _data_dir() / "artifacts" / (conversation_id or "orphan") / artifact_id
        bucket.mkdir(parents=True, exist_ok=True)
        dest = bucket / name
        dest.write_bytes(content_bytes)
        content = None
        file_path = str(dest)

    conn = get_db()
    try:
        conn.execute(
            """
            INSERT INTO artifacts
                (id, conversation_id, message_id, task_id, name, rel_path,
                 mime_type, size_bytes, content, file_path, created_by_agent_id, created_at)
            VALUES (?, ?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                artifact_id, conversation_id, message_id, name, rel_path,
                mime_type, size_bytes, content, file_path, created_by_agent_id, now,
            ),
        )
        conn.commit()
        return {
            "id": artifact_id,
            "conversation_id": conversation_id,
            "message_id": message_id,
            "name": name,
            "rel_path": rel_path,
            "mime_type": mime_type,
            "size_bytes": size_bytes,
            "content": content,
            "file_path": file_path,
            "created_by_agent_id": created_by_agent_id,
            "created_at": now,
        }
    finally:
        conn.close()


def list_artifacts_for_message(message_id: str) -> list[dict]:
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT id, conversation_id, message_id, name, rel_path, mime_type, "
            "size_bytes, file_path, created_at "
            "FROM artifacts WHERE message_id = ? ORDER BY created_at ASC",
            (message_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def list_artifacts_for_conversation(conv_id: str) -> list[dict]:
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT id, conversation_id, message_id, name, rel_path, mime_type, "
            "size_bytes, file_path, created_at "
            "FROM artifacts WHERE conversation_id = ? ORDER BY created_at ASC",
            (conv_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_artifact(artifact_id: str) -> Optional[dict]:
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT * FROM artifacts WHERE id = ?", (artifact_id,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def attach_artifacts_to_message(artifact_ids: list[str], message_id: str) -> int:
    """Set message_id on a batch of artifact rows. Returns number of rows updated."""
    if not artifact_ids:
        return 0
    conn = get_db()
    try:
        placeholders = ",".join("?" * len(artifact_ids))
        cursor = conn.execute(
            f"UPDATE artifacts SET message_id = ? WHERE id IN ({placeholders})",
            [message_id, *artifact_ids],
        )
        conn.commit()
        return cursor.rowcount
    finally:
        conn.close()


# ── Tasks (Wave 3, T1) ─────────────────────────────────────────────────────

TASK_STATUSES = ("pending", "running", "done", "failed", "cancelled")


def create_task(
    *,
    user_id: str,
    title: str,
    description: Optional[str] = None,
    conversation_id: Optional[str] = None,
    agent_id: Optional[str] = None,
    parent_task_id: Optional[str] = None,
) -> dict:
    """Insert a task with status='pending'. Returns the full row dict."""
    task_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    conn = get_db()
    try:
        conn.execute(
            """
            INSERT INTO tasks
                (id, user_id, conversation_id, agent_id, parent_task_id,
                 title, description, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)
            """,
            (task_id, user_id, conversation_id, agent_id, parent_task_id,
             title, description, now, now),
        )
        conn.commit()
    finally:
        conn.close()
    return get_task(task_id)  # type: ignore[return-value]


def get_task(task_id: str) -> Optional[dict]:
    """Single task by id, or None."""
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def list_tasks(user_id: str, conversation_id: Optional[str] = None) -> list[dict]:
    """All tasks for a user, ORDER BY updated_at DESC. Optionally filter by conversation."""
    conn = get_db()
    try:
        if conversation_id is not None:
            rows = conn.execute(
                "SELECT * FROM tasks WHERE user_id = ? AND conversation_id = ? "
                "ORDER BY updated_at DESC",
                (user_id, conversation_id),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM tasks WHERE user_id = ? ORDER BY updated_at DESC",
                (user_id,),
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def update_task(
    task_id: str,
    *,
    status: Optional[str] = None,
    title: Optional[str] = None,
    description: Optional[str] = None,
) -> Optional[dict]:
    """Partial update; bumps updated_at on any change. Returns updated row or None.

    Caller validates status enum before calling — an invalid value must not reach
    the DB CHECK (the app-level check gives the user a clean 400, not an IntegrityError).
    Mirrors the dynamic SET-builder style of update_agent_instance().
    """
    sets: list[str] = []
    args: list = []
    if status is not None:
        sets.append("status = ?")
        args.append(status)
    if title is not None:
        sets.append("title = ?")
        args.append(title)
    if description is not None:
        sets.append("description = ?")
        args.append(description)
    if not sets:
        return get_task(task_id)

    sets.append("updated_at = ?")
    args.append(datetime.now(timezone.utc).isoformat())
    args.append(task_id)

    conn = get_db()
    try:
        cursor = conn.execute(
            f"UPDATE tasks SET {', '.join(sets)} WHERE id = ?",
            args,
        )
        conn.commit()
        if cursor.rowcount == 0:
            return None
    finally:
        conn.close()
    return get_task(task_id)
