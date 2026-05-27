"""Facade tests for backend/agent_bridge.py after Fase 1 rewrite.

The facade keeps the old `call_agent_*` signatures so `main.py` and
`realtime.py` don't change, but internally delegates to whatever
`AgentBackend` `_resolve_backend()` returns (Fase 1: always a
`LocalAcpBackend`; Fase 2 will resolve per-conversation).

A fake `AgentBackend` is injected via `monkeypatch` on `_resolve_backend`
so we never spawn a real `hermes acp` for these tests.
"""

from __future__ import annotations

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
    monkeypatch.setattr(agent_bridge, "_resolve_backend", lambda: fake)
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
    monkeypatch.setattr(agent_bridge, "_resolve_backend", lambda: fake)
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
    monkeypatch.setattr(agent_bridge, "_resolve_backend", lambda: fake)
    monkeypatch.setattr(agent_bridge, "agent_enabled", lambda: True)

    answer = await agent_bridge.call_agent_for_voice(
        "q", user_name="A", user_id="a", user_role="R"
    )

    assert "- " not in answer
    for word in ("one", "two", "three"):
        assert word in answer


async def test_call_agent_passes_user_identity_via_turn_context(monkeypatch):
    fake = _FakeBackend([("text", "ok"), ("done", None)])
    monkeypatch.setattr(agent_bridge, "_resolve_backend", lambda: fake)
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
    monkeypatch.setattr(agent_bridge, "_resolve_backend", lambda: fake)
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
    monkeypatch.setattr(agent_bridge, "_resolve_backend", lambda: fake)
    monkeypatch.setattr(agent_bridge, "agent_enabled", lambda: True)

    answer = await agent_bridge.call_agent(
        "q", user_name="A", user_id="a", user_role="R"
    )

    assert "no answer" in answer.lower()
