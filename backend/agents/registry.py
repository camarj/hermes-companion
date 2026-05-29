"""Backend registry keyed by agent `type` (AC-W2-A1).

Backend selection has two orthogonal axes:
  * `transport` (local-acp / remote-acp) — *where* the agent runs. Handled by
    `agent_bridge._resolve_backend` (remote always goes through the sidecar).
  * `type` (hermes / openclaw / custom) — *which* CLI + event mapping. Resolved
    here, table-driven, so adding a type is "implement an AgentBackend subclass
    + one `register_local_backend(...)` line" with no change to the dispatcher.

An unknown or absent type falls back to the `hermes` local backend so existing
single-Hermes setups keep working (back-compat).
"""

from __future__ import annotations

from typing import Callable

from agents.base import AgentBackend
from agents.local_acp import LocalAcpBackend

LocalBackendFactory = Callable[[dict], AgentBackend]

_LOCAL_BACKENDS: dict[str, LocalBackendFactory] = {}

_FALLBACK_TYPE = "hermes"


def register_local_backend(agent_type: str, factory: LocalBackendFactory) -> None:
    """Register `factory` as the builder for local instances of `agent_type`."""
    _LOCAL_BACKENDS[agent_type.lower()] = factory


def registered_local_types() -> list[str]:
    return sorted(_LOCAL_BACKENDS)


def build_local_backend(agent: dict) -> AgentBackend:
    """Build the local backend for an agent instance dict, by its `type`."""
    agent_type = (agent.get("type") or _FALLBACK_TYPE).lower()
    factory = _LOCAL_BACKENDS.get(agent_type) or _LOCAL_BACKENDS[_FALLBACK_TYPE]
    return factory(agent)


# ── Built-in registrations ──────────────────────────────────────────────────
register_local_backend(
    "hermes",
    lambda agent: LocalAcpBackend(
        system_prompt_override=agent.get("system_prompt_override")
    ),
)
