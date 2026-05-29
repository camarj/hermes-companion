"""AC-W3-A1 storage routing tests (WU-F + WU-H).

Scenarios covered:
  3 — Small file stored inline (BLOB path)
  4 — Large file stored to DATA_DIR (file-path path)
  13 — Name collision within same conversation produces distinct rows
  H-1 — delete_conversation removes on-disk artifact files
"""

import os
import sqlite3
import uuid
from pathlib import Path

import pytest

import database
from database import ARTIFACT_INLINE_MAX_BYTES, create_artifact, delete_conversation


# ── Scenario 3: small file stored inline ──────────────────────────────────

def test_small_file_stored_inline(inited_db: Path, monkeypatch, tmp_path: Path):
    monkeypatch.setattr("config.data_dir", lambda: tmp_path / "data")

    conv_id = _seed_conversation(inited_db)
    content = b"hello world"
    assert len(content) <= ARTIFACT_INLINE_MAX_BYTES

    row = create_artifact(
        name="notes.txt",
        rel_path="notes.txt",
        content_bytes=content,
        conversation_id=conv_id,
    )

    assert row["content"] == content
    assert row["file_path"] is None
    assert row["size_bytes"] == len(content)


# ── Scenario 4: large file stored to DATA_DIR ─────────────────────────────

def test_large_file_stored_to_data_dir(inited_db: Path, monkeypatch, tmp_path: Path):
    data_root = tmp_path / "data"
    monkeypatch.setattr("config.data_dir", lambda: data_root)
    monkeypatch.setattr("database._data_dir", lambda: data_root)

    conv_id = _seed_conversation(inited_db)
    content = b"x" * (ARTIFACT_INLINE_MAX_BYTES + 1)

    row = create_artifact(
        name="bigfile.bin",
        rel_path="bigfile.bin",
        content_bytes=content,
        conversation_id=conv_id,
    )

    assert row["file_path"] is not None
    assert row["content"] is None

    fp = Path(row["file_path"])
    assert fp.exists()
    assert fp.read_bytes() == content

    assert str(row["file_path"]).startswith(str(data_root))


# ── Scenario 13: name collision → two distinct rows, unique file_paths ────

def test_name_collision_produces_distinct_rows(inited_db: Path, monkeypatch, tmp_path: Path):
    data_root = tmp_path / "data"
    monkeypatch.setattr("database._data_dir", lambda: data_root)

    conv_id = _seed_conversation(inited_db)
    content_a = b"version one"
    content_b = b"version two"

    row_a = create_artifact(
        name="output.txt",
        rel_path="output.txt",
        content_bytes=content_a,
        conversation_id=conv_id,
    )
    row_b = create_artifact(
        name="output.txt",
        rel_path="output.txt",
        content_bytes=content_b,
        conversation_id=conv_id,
    )

    assert row_a["id"] != row_b["id"]
    assert row_a["content"] == content_a
    assert row_b["content"] == content_b


def test_name_collision_large_files_have_distinct_paths(inited_db: Path, monkeypatch, tmp_path: Path):
    data_root = tmp_path / "data"
    monkeypatch.setattr("database._data_dir", lambda: data_root)

    conv_id = _seed_conversation(inited_db)
    big = b"y" * (ARTIFACT_INLINE_MAX_BYTES + 1)

    row_a = create_artifact(
        name="report.bin",
        rel_path="report.bin",
        content_bytes=big,
        conversation_id=conv_id,
    )
    row_b = create_artifact(
        name="report.bin",
        rel_path="report.bin",
        content_bytes=big,
        conversation_id=conv_id,
    )

    assert row_a["file_path"] != row_b["file_path"]
    assert Path(row_a["file_path"]).exists()
    assert Path(row_b["file_path"]).exists()


# ── WU-H: delete_conversation removes on-disk artifact files ──────────────

def test_delete_conversation_removes_on_disk_artifact_files(
    inited_db: Path, monkeypatch, tmp_path: Path
):
    data_root = tmp_path / "data"
    monkeypatch.setattr("database._data_dir", lambda: data_root)

    conv_id = _seed_conversation(inited_db)
    big = b"z" * (ARTIFACT_INLINE_MAX_BYTES + 1)

    row = create_artifact(
        name="artifact.bin",
        rel_path="artifact.bin",
        content_bytes=big,
        conversation_id=conv_id,
    )
    fp = Path(row["file_path"])
    assert fp.exists()

    delete_conversation(conv_id)

    assert not fp.exists()

    conn = sqlite3.connect(str(inited_db))
    try:
        count = conn.execute(
            "SELECT COUNT(*) FROM artifacts WHERE conversation_id = ?", (conv_id,)
        ).fetchone()[0]
    finally:
        conn.close()
    assert count == 0


def test_delete_conversation_does_not_error_when_file_already_missing(
    inited_db: Path, monkeypatch, tmp_path: Path
):
    data_root = tmp_path / "data"
    monkeypatch.setattr("database._data_dir", lambda: data_root)

    conv_id = _seed_conversation(inited_db)
    big = b"q" * (ARTIFACT_INLINE_MAX_BYTES + 1)

    row = create_artifact(
        name="ghost.bin",
        rel_path="ghost.bin",
        content_bytes=big,
        conversation_id=conv_id,
    )
    os.unlink(row["file_path"])

    deleted = delete_conversation(conv_id)
    assert deleted is True


# ── Helpers ───────────────────────────────────────────────────────────────

def _seed_conversation(db_path: Path) -> str:
    conn = sqlite3.connect(str(db_path))
    try:
        user_id = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO users (id, name, role) VALUES (?, 'Tester', 'tester')",
            (user_id,),
        )
        conv_id = str(uuid.uuid4())
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "INSERT INTO conversations (id, user_id, title, created_at, updated_at) "
            "VALUES (?, ?, 'Test', ?, ?)",
            (conv_id, user_id, now, now),
        )
        conn.commit()
        return conv_id
    finally:
        conn.close()
