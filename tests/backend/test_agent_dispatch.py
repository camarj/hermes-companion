"""Per-conversation backend dispatch (AC-W1-A1 full).

`_resolve_backend(conversation_id)` looks up the conversation's
`agent_id`, reads the matching agent_instance, and returns the right
`AgentBackend` subclass. Legacy conversations with NULL agent_id keep
landing on `LocalAcpBackend` so AC-W1-B1 stays satisfied.
"""

from __future__ import annotations

import os

import pytest

import agent_bridge
from agents.local_acp import LocalAcpBackend
from agents.remote_acp import RemoteAcpBackend


# ---------------------------------------------------------------------------
# Fakes for get_conversation / get_agent_instance
# ---------------------------------------------------------------------------


def _patch_lookups(monkeypatch, *, conv=None, agent=None):
    monkeypatch.setattr(
        agent_bridge, "get_conversation",
        lambda conv_id: conv,
    )
    monkeypatch.setattr(
        agent_bridge, "get_agent_instance",
        lambda agent_id: agent if agent and agent["id"] == agent_id else None,
    )


# ---------------------------------------------------------------------------
# Dispatch by transport
# ---------------------------------------------------------------------------


def test_resolve_backend_no_conversation_id_returns_local():
    """Legacy callers (voice, chat without conversation) get LocalAcpBackend."""
    backend = agent_bridge._resolve_backend(None)
    assert isinstance(backend, LocalAcpBackend)


def test_resolve_backend_unknown_conversation_returns_local(monkeypatch):
    _patch_lookups(monkeypatch, conv=None)
    backend = agent_bridge._resolve_backend("nope")
    assert isinstance(backend, LocalAcpBackend)


def test_resolve_backend_conversation_with_null_agent_id_returns_local(monkeypatch):
    """Back-compat: rows that pre-date the registry should still work."""
    _patch_lookups(monkeypatch, conv={"id": "c", "agent_id": None})
    backend = agent_bridge._resolve_backend("c")
    assert isinstance(backend, LocalAcpBackend)


def test_resolve_backend_local_transport_returns_local(monkeypatch):
    _patch_lookups(
        monkeypatch,
        conv={"id": "c", "agent_id": "local-default"},
        agent={
            "id": "local-default",
            "transport": "local-acp",
            "transport_config": {},
            "system_prompt_override": None,
        },
    )
    backend = agent_bridge._resolve_backend("c")
    assert isinstance(backend, LocalAcpBackend)


def test_resolve_backend_remote_transport_returns_remote(monkeypatch):
    _patch_lookups(
        monkeypatch,
        conv={"id": "c", "agent_id": "vps-prod"},
        agent={
            "id": "vps-prod",
            "transport": "remote-acp",
            "transport_config": {
                "url": "wss://vps.example.com/api/host/acp",
                "token": "literal-secret",
            },
            "system_prompt_override": "Be terse.",
        },
    )

    backend = agent_bridge._resolve_backend("c")
    assert isinstance(backend, RemoteAcpBackend)
    assert backend._url == "wss://vps.example.com/api/host/acp"
    assert backend._token == "literal-secret"
    assert backend._system_prompt == "Be terse."


def test_resolve_backend_remote_resolves_env_token_ref(monkeypatch):
    """`token: "env:HERMES_VPS_TOKEN"` should read the env var at resolve time."""
    monkeypatch.setenv("HERMES_VPS_TOKEN", "from-env-T")
    _patch_lookups(
        monkeypatch,
        conv={"id": "c", "agent_id": "vps-prod"},
        agent={
            "id": "vps-prod",
            "transport": "remote-acp",
            "transport_config": {
                "url": "wss://vps/api/host/acp",
                "token": "env:HERMES_VPS_TOKEN",
            },
            "system_prompt_override": None,
        },
    )

    backend = agent_bridge._resolve_backend("c")
    assert isinstance(backend, RemoteAcpBackend)
    assert backend._token == "from-env-T"


def test_resolve_backend_unknown_transport_falls_back_to_local(monkeypatch):
    """Future transports we don't know yet shouldn't crash an existing install."""
    _patch_lookups(
        monkeypatch,
        conv={"id": "c", "agent_id": "x"},
        agent={
            "id": "x",
            "transport": "future-transport",
            "transport_config": {},
            "system_prompt_override": None,
        },
    )

    backend = agent_bridge._resolve_backend("c")
    assert isinstance(backend, LocalAcpBackend)


# ---------------------------------------------------------------------------
# call_agent_stream end-to-end uses dispatched backend
# ---------------------------------------------------------------------------


async def test_call_agent_stream_picks_remote_when_conversation_bound(monkeypatch):
    """call_agent_stream's resolve hook actually consults conversation_id."""
    captured = {}

    def fake_resolve(conv_id):
        captured["conv_id"] = conv_id

        class _Fake:
            async def stream(self, query, context, *, image_paths=None):
                yield ("text", "ok")
                yield ("done", None)

        return _Fake()

    monkeypatch.setattr(agent_bridge, "_resolve_backend", fake_resolve)
    monkeypatch.setattr(agent_bridge, "agent_enabled", lambda: True)
    monkeypatch.setattr(
        agent_bridge, "get_conversation_session_id",
        lambda conv_id: None,
    )

    async for _ in agent_bridge.call_agent_stream(
        "q", user_name="A", user_id="a", user_role="R",
        conversation_id="conv-77",
    ):
        pass

    assert captured["conv_id"] == "conv-77"
