"""Facade tests for backend/agent_bridge.py after Fase 1 rewrite.

The facade keeps the old `call_agent_*` signatures so `main.py` and
`realtime.py` don't change, but internally delegates to whatever
`AgentBackend` `_resolve_backend()` returns (Fase 1: always a
`LocalAcpBackend`; Fase 2 will resolve per-conversation).

A fake `AgentBackend` is injected via `monkeypatch` on `_resolve_backend`
so we never spawn a real `hermes acp` for these tests.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import AsyncIterator

import pytest

import agent_bridge
from agents.base import AgentBackend, AgentEvent, TurnContext


class _FakeBackend(AgentBackend):
    def __init__(self, events: list[AgentEvent]) -> None:
        self._events = events
        self.captured: tuple[str, TurnContext, list[str] | None] | None = None

    async def stream(
        self,
        query: str,
        context: TurnContext,
        *,
        image_paths: list[str] | None = None,
    ) -> AsyncIterator[AgentEvent]:
        self.captured = (query, context, image_paths)
        for ev in self._events:
            yield ev


async def test_call_agent_stream_strips_done_terminator(monkeypatch):
    fake = _FakeBackend([
        ("reasoning", "think"),
        ("text", "hi"),
        ("done", None),
    ])
    monkeypatch.setattr(agent_bridge, "_resolve_backend", lambda conv_id: fake)
    monkeypatch.setattr(agent_bridge, "agent_enabled", lambda: True)

    events = [
        ev async for ev in agent_bridge.call_agent_stream(
            "q", user_name="A", user_id="a", user_role="R"
        )
    ]

    assert events == [("reasoning", "think"), ("text", "hi")]


async def test_call_agent_returns_concatenated_text(monkeypatch):
    fake = _FakeBackend([
        ("reasoning", "ignored by call_agent"),
        ("text", "hel"),
        ("text", "lo"),
        ("done", None),
    ])
    monkeypatch.setattr(agent_bridge, "_resolve_backend", lambda conv_id: fake)
    monkeypatch.setattr(agent_bridge, "agent_enabled", lambda: True)

    answer = await agent_bridge.call_agent(
        "q", user_name="A", user_id="a", user_role="R"
    )

    assert answer == "hello"


async def test_call_agent_for_voice_flattens_markdown_bullets(monkeypatch):
    fake = _FakeBackend([
        ("text", "- one\n- two\n- three\n"),
        ("done", None),
    ])
    monkeypatch.setattr(agent_bridge, "_resolve_backend", lambda conv_id: fake)
    monkeypatch.setattr(agent_bridge, "agent_enabled", lambda: True)

    answer = await agent_bridge.call_agent_for_voice(
        "q", user_name="A", user_id="a", user_role="R"
    )

    assert "- " not in answer
    for word in ("one", "two", "three"):
        assert word in answer


async def test_call_agent_passes_user_identity_via_turn_context(monkeypatch):
    fake = _FakeBackend([("text", "ok"), ("done", None)])
    monkeypatch.setattr(agent_bridge, "_resolve_backend", lambda conv_id: fake)
    monkeypatch.setattr(agent_bridge, "agent_enabled", lambda: True)

    await agent_bridge.call_agent(
        "the query", user_name="Alice", user_id="alice", user_role="CEO"
    )

    assert fake.captured is not None
    query, ctx, _ = fake.captured
    assert query == "the query"
    assert ctx.user_id == "alice"
    assert ctx.user_name == "Alice"
    assert ctx.user_role == "CEO"


async def test_call_agent_stream_forwards_image_paths(monkeypatch):
    fake = _FakeBackend([("text", "ok"), ("done", None)])
    monkeypatch.setattr(agent_bridge, "_resolve_backend", lambda conv_id: fake)
    monkeypatch.setattr(agent_bridge, "agent_enabled", lambda: True)

    paths = ["/tmp/a.png", "/tmp/b.png"]
    async for _ in agent_bridge.call_agent_stream(
        "q", user_name="A", user_id="a", user_role="", image_paths=paths
    ):
        pass

    assert fake.captured is not None
    _, _, captured_paths = fake.captured
    assert captured_paths == paths


async def test_call_agent_stream_returns_friendly_message_when_disabled(monkeypatch):
    monkeypatch.setattr(agent_bridge, "agent_enabled", lambda: False)

    events = [
        ev async for ev in agent_bridge.call_agent_stream(
            "q", user_name="A", user_id="a", user_role="R"
        )
    ]

    assert len(events) == 1
    kind, payload = events[0]
    assert kind == "text"
    assert isinstance(payload, str)
    assert "agent" in payload.lower()


async def test_call_agent_returns_fallback_when_no_text_yielded(monkeypatch):
    fake = _FakeBackend([("reasoning", "thinking only"), ("done", None)])
    monkeypatch.setattr(agent_bridge, "_resolve_backend", lambda conv_id: fake)
    monkeypatch.setattr(agent_bridge, "agent_enabled", lambda: True)

    answer = await agent_bridge.call_agent(
        "q", user_name="A", user_id="a", user_role="R"
    )

    assert "no answer" in answer.lower()


# AC-W1-D4: facade persists hermes_session_id and resumes on next call.

async def test_call_agent_stream_strips_session_event(monkeypatch):
    """The session event is plumbing — must never reach the SSE consumer."""
    fake = _FakeBackend([
        ("session", "abc-123"),
        ("text", "hi"),
        ("done", None),
    ])
    monkeypatch.setattr(agent_bridge, "_resolve_backend", lambda conv_id: fake)
    monkeypatch.setattr(agent_bridge, "agent_enabled", lambda: True)

    events = [
        ev async for ev in agent_bridge.call_agent_stream(
            "q", user_name="A", user_id="a", user_role="R"
        )
    ]

    # No "session" in the stream — only what the UI consumes.
    assert events == [("text", "hi")]


async def test_call_agent_stream_persists_session_id_when_conversation_id_given(
    monkeypatch
):
    fake = _FakeBackend([
        ("session", "fresh-session"),
        ("text", "ok"),
        ("done", None),
    ])
    monkeypatch.setattr(agent_bridge, "_resolve_backend", lambda conv_id: fake)
    monkeypatch.setattr(agent_bridge, "agent_enabled", lambda: True)

    persisted: list[tuple[str, str]] = []
    monkeypatch.setattr(
        agent_bridge, "update_conversation_session_id",
        lambda conv_id, sid: persisted.append((conv_id, sid)),
    )
    monkeypatch.setattr(
        agent_bridge, "get_conversation_session_id",
        lambda conv_id: None,
    )

    async for _ in agent_bridge.call_agent_stream(
        "q", user_name="A", user_id="a", user_role="R",
        conversation_id="conv-1",
    ):
        pass

    assert persisted == [("conv-1", "fresh-session")]


async def test_call_agent_stream_skips_persist_when_no_conversation_id(monkeypatch):
    fake = _FakeBackend([
        ("session", "x"), ("text", "ok"), ("done", None),
    ])
    monkeypatch.setattr(agent_bridge, "_resolve_backend", lambda conv_id: fake)
    monkeypatch.setattr(agent_bridge, "agent_enabled", lambda: True)

    called = []
    monkeypatch.setattr(
        agent_bridge, "update_conversation_session_id",
        lambda *a, **k: called.append((a, k)),
    )
    monkeypatch.setattr(
        agent_bridge, "get_conversation_session_id",
        lambda *a, **k: None,
    )

    async for _ in agent_bridge.call_agent_stream(
        "q", user_name="A", user_id="a", user_role="R"
    ):
        pass

    assert called == []


async def test_call_agent_stream_loads_existing_session_id_into_context(monkeypatch):
    """When a conversation already has a stored session id, the facade
    fills `TurnContext.session_id` so the backend resumes."""
    fake = _FakeBackend([("session", "loaded"), ("text", "ok"), ("done", None)])
    monkeypatch.setattr(agent_bridge, "_resolve_backend", lambda conv_id: fake)
    monkeypatch.setattr(agent_bridge, "agent_enabled", lambda: True)
    monkeypatch.setattr(
        agent_bridge, "get_conversation_session_id",
        lambda conv_id: "stored-session-xyz",
    )
    monkeypatch.setattr(
        agent_bridge, "update_conversation_session_id",
        lambda *a, **k: None,
    )

    async for _ in agent_bridge.call_agent_stream(
        "q", user_name="A", user_id="a", user_role="R",
        conversation_id="conv-1",
    ):
        pass

    assert fake.captured is not None
    _, ctx, _ = fake.captured
    assert ctx.session_id == "stored-session-xyz"


async def test_call_agent_stream_skips_persist_when_session_id_unchanged(monkeypatch):
    """If the backend echoes the SAME session id we already have, no write."""
    fake = _FakeBackend([("session", "same"), ("text", "ok"), ("done", None)])
    monkeypatch.setattr(agent_bridge, "_resolve_backend", lambda conv_id: fake)
    monkeypatch.setattr(agent_bridge, "agent_enabled", lambda: True)

    writes = []
    monkeypatch.setattr(
        agent_bridge, "update_conversation_session_id",
        lambda conv_id, sid: writes.append((conv_id, sid)),
    )
    monkeypatch.setattr(
        agent_bridge, "get_conversation_session_id",
        lambda conv_id: "same",
    )

    async for _ in agent_bridge.call_agent_stream(
        "q", user_name="A", user_id="a", user_role="R",
        conversation_id="conv-1",
    ):
        pass

    assert writes == []


# ── AC-W3-A1: _snapshot_dir helper ────────────────────────────────────────

def test_snapshot_dir_returns_rel_path_mtime_size_hash_tuple(tmp_path):
    """_snapshot_dir returns {rel_path: (mtime, size, sha256_hex)} for all files."""
    (tmp_path / "a.txt").write_text("hello")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "b.txt").write_text("world")

    snapshot = agent_bridge._snapshot_dir(str(tmp_path))

    assert "a.txt" in snapshot
    assert "sub/b.txt" in snapshot or str(Path("sub") / "b.txt") in snapshot

    entry = snapshot["a.txt"]
    assert isinstance(entry, tuple) and len(entry) == 3
    mtime, size, sha = entry
    assert isinstance(mtime, float)
    assert size == 5
    assert isinstance(sha, str) and len(sha) == 64  # SHA-256 hex


def test_snapshot_dir_empty_returns_empty_dict(tmp_path):
    snapshot = agent_bridge._snapshot_dir(str(tmp_path))
    assert snapshot == {}


def test_snapshot_dir_nonexistent_path_returns_empty_dict(tmp_path):
    missing = str(tmp_path / "does_not_exist")
    snapshot = agent_bridge._snapshot_dir(missing)
    assert snapshot == {}


def test_snapshot_dir_does_not_read_bytes_for_old_files(tmp_path, monkeypatch):
    """_snapshot_dir must NOT read file contents for files older than the tie window.

    Lazy hashing: only files whose mtime is within ~2 s of now are hashed.
    Older files produce an empty-string hash placeholder via stat() only.
    This proves the O(stat) path for accumulated workdir files between turns.
    """
    old_file = tmp_path / "old.bin"
    old_file.write_bytes(b"some binary data that should never be read")

    # Back-date the file well outside the 2-second tie window.
    old_mtime = __import__("time").time() - 60.0
    os.utime(str(old_file), (old_mtime, old_mtime))

    read_calls: list[str] = []

    original_read_bytes = Path.read_bytes

    def spy_read_bytes(self: Path) -> bytes:
        read_calls.append(str(self))
        return original_read_bytes(self)

    monkeypatch.setattr(Path, "read_bytes", spy_read_bytes)

    snapshot = agent_bridge._snapshot_dir(str(tmp_path))

    assert "old.bin" in snapshot, "old file must still appear in snapshot"
    mtime, size, sha = snapshot["old.bin"]
    assert sha == "", "old file hash must be empty (lazy — no content read)"
    assert read_calls == [], (
        "_snapshot_dir must not call read_bytes for files outside the tie window; "
        f"unexpected reads: {read_calls}"
    )
