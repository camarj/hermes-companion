"""AC-W3-A1 artifact capture integration tests (WU-C: C-2, C-3, C-4).

These tests exercise the _scan_new_artifacts helper and the end-to-end
call_agent_stream capture path.

Scenarios covered:
  1  — New file captured and attributed (integration)
  2  — Pre-existing file not captured (_scan_new_artifacts diff)
  4  — Binary file captured with correct MIME type
  11 — Empty cwd / no new files → zero artifacts
  12 — Binary file captured correctly
"""

import sqlite3
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

import pytest

import agent_bridge
import database
from agents.base import AgentBackend, AgentEvent, TurnContext


# ── _scan_new_artifacts helper ─────────────────────────────────────────────

def test_scan_new_artifacts_returns_only_new_files(tmp_path: Path):
    existing = tmp_path / "old.txt"
    existing.write_text("pre-existing content")

    pre_snapshot = agent_bridge._snapshot_dir(str(tmp_path))

    new_file = tmp_path / "report.md"
    new_file.write_text("new content")

    results = agent_bridge._scan_new_artifacts(str(tmp_path), pre_snapshot)

    names = [r["name"] for r in results]
    assert "report.md" in names
    assert "old.txt" not in names


def test_scan_new_artifacts_returns_modified_files(tmp_path: Path):
    existing = tmp_path / "modified.txt"
    existing.write_text("original")

    pre_snapshot = agent_bridge._snapshot_dir(str(tmp_path))

    import time; time.sleep(0.01)
    existing.write_text("changed content with more bytes")

    results = agent_bridge._scan_new_artifacts(str(tmp_path), pre_snapshot)
    names = [r["name"] for r in results]
    assert "modified.txt" in names


def test_scan_new_artifacts_returns_empty_when_nothing_changed(tmp_path: Path):
    (tmp_path / "stable.txt").write_text("unchanged")
    pre_snapshot = agent_bridge._snapshot_dir(str(tmp_path))

    results = agent_bridge._scan_new_artifacts(str(tmp_path), pre_snapshot)
    assert results == []


def test_scan_new_artifacts_includes_content_bytes(tmp_path: Path):
    pre_snapshot = agent_bridge._snapshot_dir(str(tmp_path))

    content = b"hello bytes"
    new_file = tmp_path / "data.txt"
    new_file.write_bytes(content)

    results = agent_bridge._scan_new_artifacts(str(tmp_path), pre_snapshot)

    assert len(results) == 1
    assert results[0]["content_bytes"] == content
    assert results[0]["size_bytes"] == len(content)


def test_scan_new_artifacts_includes_rel_path(tmp_path: Path):
    sub = tmp_path / "subdir"
    sub.mkdir()
    pre_snapshot = agent_bridge._snapshot_dir(str(tmp_path))

    (sub / "nested.txt").write_text("nested")

    results = agent_bridge._scan_new_artifacts(str(tmp_path), pre_snapshot)

    assert len(results) == 1
    assert "subdir" in results[0]["rel_path"] or "nested.txt" in results[0]["rel_path"]


# ── Scenario 12: binary file gets correct MIME type ────────────────────────

_MINIMAL_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d49444154789c6300010000000500010d0a2db40000000049454e44ae426082"
)


def test_scan_new_artifacts_detects_png_mime_type(tmp_path: Path):
    pre_snapshot = agent_bridge._snapshot_dir(str(tmp_path))

    png_file = tmp_path / "image.png"
    png_file.write_bytes(_MINIMAL_PNG)

    results = agent_bridge._scan_new_artifacts(str(tmp_path), pre_snapshot)

    assert len(results) == 1
    assert results[0]["mime_type"].startswith("image/")


# ── Scenario 2: empty cwd → zero artifacts ────────────────────────────────

def test_scan_new_artifacts_empty_cwd_returns_empty(tmp_path: Path):
    pre_snapshot = agent_bridge._snapshot_dir(str(tmp_path))
    results = agent_bridge._scan_new_artifacts(str(tmp_path), pre_snapshot)
    assert results == []


# ── Scenario 1: integration — call_agent_stream persists artifact ──────────

class _CwdBackend(AgentBackend):
    """Fake backend that reports a cwd and writes a file during the turn."""
    def __init__(self, cwd: str, filename: str, file_content: bytes) -> None:
        self._cwd = cwd
        self._filename = filename
        self._file_content = file_content

    async def stream(
        self,
        query: str,
        context: TurnContext,
        *,
        image_paths=None,
    ):
        yield ("cwd", self._cwd)
        yield ("session", "fake-session")
        (Path(self._cwd) / self._filename).write_bytes(self._file_content)
        yield ("text", "done")
        yield ("done", None)


async def test_call_agent_stream_persists_new_artifact(
    inited_db: Path, monkeypatch, tmp_path: Path
):
    cwd = str(tmp_path / "agent_cwd")
    Path(cwd).mkdir()

    data_root = tmp_path / "data"
    monkeypatch.setattr("database._data_dir", lambda: data_root)

    conv_id = _seed_conversation(inited_db)

    backend = _CwdBackend(cwd=cwd, filename="report.md", file_content=b"# Report")
    monkeypatch.setattr(agent_bridge, "_resolve_backend", lambda c: backend)
    monkeypatch.setattr(agent_bridge, "agent_enabled", lambda: True)
    monkeypatch.setattr(agent_bridge, "get_conversation_session_id", lambda c: None)
    monkeypatch.setattr(agent_bridge, "update_conversation_session_id", lambda *a: None)

    events = [
        ev async for ev in agent_bridge.call_agent_stream(
            "write something", user_id="u1", conversation_id=conv_id
        )
    ]

    text_events = [ev for ev in events if ev[0] == "text"]
    artifact_events = [ev for ev in events if ev[0] == "artifact"]

    assert len(text_events) == 1
    assert text_events[0][1] == "done"
    assert len(artifact_events) == 1

    art = artifact_events[0][1]
    assert art["name"] == "report.md"
    assert art["conversation_id"] == conv_id
    assert art["size_bytes"] == len(b"# Report")


async def test_call_agent_stream_does_not_capture_pre_existing_files(
    inited_db: Path, monkeypatch, tmp_path: Path
):
    cwd = str(tmp_path / "agent_cwd")
    Path(cwd).mkdir()
    (Path(cwd) / "old.txt").write_text("pre-existing")

    data_root = tmp_path / "data"
    monkeypatch.setattr("database._data_dir", lambda: data_root)

    conv_id = _seed_conversation(inited_db)

    class _NothingNewBackend(AgentBackend):
        async def stream(self, query, context, *, image_paths=None):
            yield ("cwd", cwd)
            yield ("session", "s")
            yield ("text", "nothing new")
            yield ("done", None)

    monkeypatch.setattr(agent_bridge, "_resolve_backend", lambda c: _NothingNewBackend())
    monkeypatch.setattr(agent_bridge, "agent_enabled", lambda: True)
    monkeypatch.setattr(agent_bridge, "get_conversation_session_id", lambda c: None)
    monkeypatch.setattr(agent_bridge, "update_conversation_session_id", lambda *a: None)

    events = [
        ev async for ev in agent_bridge.call_agent_stream(
            "q", user_id="u1", conversation_id=conv_id
        )
    ]

    artifact_events = [ev for ev in events if ev[0] == "artifact"]
    assert artifact_events == []


async def test_call_agent_stream_no_cwd_event_means_no_artifact_capture(
    inited_db: Path, monkeypatch, tmp_path: Path
):
    """When no cwd event is emitted (e.g. RemoteAcpBackend), no scan is done."""
    conv_id = _seed_conversation(inited_db)

    class _NoCwdBackend(AgentBackend):
        async def stream(self, query, context, *, image_paths=None):
            yield ("session", "s")
            yield ("text", "answer")
            yield ("done", None)

    monkeypatch.setattr(agent_bridge, "_resolve_backend", lambda c: _NoCwdBackend())
    monkeypatch.setattr(agent_bridge, "agent_enabled", lambda: True)
    monkeypatch.setattr(agent_bridge, "get_conversation_session_id", lambda c: None)
    monkeypatch.setattr(agent_bridge, "update_conversation_session_id", lambda *a: None)

    events = [
        ev async for ev in agent_bridge.call_agent_stream(
            "q", user_id="u1", conversation_id=conv_id
        )
    ]

    artifact_events = [ev for ev in events if ev[0] == "artifact"]
    assert artifact_events == []


async def test_call_agent_cwd_and_artifact_events_stripped_from_text_accumulation(
    monkeypatch, tmp_path
):
    """call_agent (voice path) must not include cwd/artifact text in the result."""
    cwd = str(tmp_path / "cwd")
    Path(cwd).mkdir()

    class _ArtifactBackend(AgentBackend):
        async def stream(self, query, context, *, image_paths=None):
            yield ("cwd", cwd)
            yield ("session", "s")
            (Path(cwd) / "out.txt").write_bytes(b"x" * 10)
            yield ("text", "the answer")
            yield ("done", None)

    monkeypatch.setattr(agent_bridge, "_resolve_backend", lambda c: _ArtifactBackend())
    monkeypatch.setattr(agent_bridge, "agent_enabled", lambda: True)
    monkeypatch.setattr(agent_bridge, "get_conversation_session_id", lambda c: None)
    monkeypatch.setattr(agent_bridge, "update_conversation_session_id", lambda *a: None)
    monkeypatch.setattr("database._data_dir", lambda: tmp_path / "data")

    result = await agent_bridge.call_agent("q", user_id="u1")
    assert result == "the answer"


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
