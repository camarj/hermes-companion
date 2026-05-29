"""AC-W2-A1: a new agent type is dispatched without editing the dispatcher.

The registry makes backend selection table-driven by agent `type`. Adding a
new type is "implement an AgentBackend subclass + one registration line" — the
dispatcher (`agent_bridge._resolve_backend`) never changes. These tests pin
that contract plus the hermes back-compat fallback.
"""

import pytest

import agent_bridge
from agents import registry
from agents.base import AgentBackend, TurnContext
from agents.local_acp import LocalAcpBackend


class _SentinelBackend(AgentBackend):
    def __init__(self, agent: dict) -> None:
        self.agent = agent

    async def stream(self, query, context, *, image_paths=None):  # pragma: no cover
        yield ("done", None)


@pytest.fixture
def _clean_registry(monkeypatch: pytest.MonkeyPatch):
    """Run each test against a copy of the registry so registrations don't leak."""
    saved = dict(registry._LOCAL_BACKENDS)
    yield
    registry._LOCAL_BACKENDS.clear()
    registry._LOCAL_BACKENDS.update(saved)


def test_hermes_is_registered_by_default() -> None:
    backend = registry.build_local_backend({"type": "hermes"})
    assert isinstance(backend, LocalAcpBackend)


def test_registered_type_is_built(_clean_registry) -> None:
    registry.register_local_backend("sentinel", lambda agent: _SentinelBackend(agent))
    backend = registry.build_local_backend({"type": "sentinel", "label": "x"})
    assert isinstance(backend, _SentinelBackend)
    assert backend.agent["label"] == "x"


def test_unknown_type_falls_back_to_hermes(_clean_registry) -> None:
    assert isinstance(
        registry.build_local_backend({"type": "does-not-exist"}), LocalAcpBackend
    )


def test_absent_type_falls_back_to_hermes(_clean_registry) -> None:
    assert isinstance(registry.build_local_backend({}), LocalAcpBackend)


def test_registered_local_types_lists_registrations(_clean_registry) -> None:
    registry.register_local_backend("sentinel", lambda agent: _SentinelBackend(agent))
    assert "hermes" in registry.registered_local_types()
    assert "sentinel" in registry.registered_local_types()


def test_dispatcher_routes_new_type_without_edits(
    _clean_registry, monkeypatch: pytest.MonkeyPatch
) -> None:
    """_resolve_backend must consult the registry, so a freshly registered
    type resolves through it with no change to agent_bridge itself."""
    registry.register_local_backend("sentinel", lambda agent: _SentinelBackend(agent))
    monkeypatch.setattr(agent_bridge, "get_conversation", lambda cid: {"agent_id": "a1"})
    monkeypatch.setattr(
        agent_bridge,
        "get_agent_instance",
        lambda aid: {"id": "a1", "type": "sentinel", "transport": "local-acp"},
    )
    backend = agent_bridge._resolve_backend("conv-1")
    assert isinstance(backend, _SentinelBackend)
