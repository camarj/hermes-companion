"""
SQLite store for users, conversations, messages, and (optionally) enrolled
faces. Schema is created on first boot and the team table is seeded from
`config.yaml`.
"""

import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from config import team as configured_team

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
        """)

        _seed_users(conn)
        conn.commit()
    finally:
        conn.close()


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

def create_conversation(user_id: str, title: str = "New conversation") -> dict:
    conn = get_db()
    try:
        conv_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "INSERT INTO conversations (id, user_id, title, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            (conv_id, user_id, title, now, now),
        )
        conn.commit()
        return {"id": conv_id, "user_id": user_id, "title": title, "created_at": now, "updated_at": now}
    finally:
        conn.close()


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


def delete_conversation(conv_id: str) -> bool:
    conn = get_db()
    try:
        cursor = conn.execute("DELETE FROM conversations WHERE id = ?", (conv_id,))
        conn.commit()
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
