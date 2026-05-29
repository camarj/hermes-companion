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

import os
from typing import Callable, Optional

from agents.base import AgentBackend
from agents.local_acp import LocalAcpBackend
from agents.openclaw import OpenClawBackend

LocalBackendFactory = Callable[[dict], AgentBackend]


def resolve_token(raw: str) -> str:
    """Resolve a token reference that may be a literal or `env:VAR_NAME`."""
    if raw.startswith("env:"):
        return os.environ.get(raw[len("env:") :], "")
    return raw

_LOCAL_BACKENDS: dict[str, LocalBackendFactory] = {}

_FALLBACK_TYPE = "hermes"


def register_local_backend(agent_type: str, factory: LocalBackendFactory) -> None:
    """Register `factory` as the builder for local instances of `agent_type`."""
    _LOCAL_BACKENDS[agent_type.lower()] = factory


def registered_local_types() -> list[str]:
    return sorted(_LOCAL_BACKENDS)


def build_local_backend(agent: dict, *, cwd: Optional[str] = None) -> AgentBackend:
    """Build the local backend for an agent instance dict, by its `type`.

    When `cwd` is provided it is forwarded to the factory so the backend uses
    the per-conversation managed workdir instead of an isolated mkdtemp.
    Factories that do not accept `cwd` (e.g. custom third-party registrations)
    are called without it — they retain their own isolation behaviour.
    """
    agent_type = (agent.get("type") or _FALLBACK_TYPE).lower()
    factory = _LOCAL_BACKENDS.get(agent_type) or _LOCAL_BACKENDS[_FALLBACK_TYPE]
    if cwd is not None:
        try:
            return factory(agent, cwd=cwd)
        except TypeError:
            pass
    return factory(agent)


# ── Built-in registrations ──────────────────────────────────────────────────
def _build_hermes(agent: dict, *, cwd: Optional[str] = None) -> AgentBackend:
    kwargs: dict = {"system_prompt_override": agent.get("system_prompt_override")}
    if cwd is not None:
        kwargs["cwd"] = cwd
    return LocalAcpBackend(**kwargs)


register_local_backend("hermes", _build_hermes)


def _build_openclaw(agent: dict, *, cwd: Optional[str] = None) -> AgentBackend:
    cfg = agent.get("transport_config") or {}
    raw_token = cfg.get("token") or ""
    kwargs: dict = {
        "gateway_url": cfg.get("url") or None,
        "gateway_token": resolve_token(raw_token) or None,
        "system_prompt_override": agent.get("system_prompt_override"),
    }
    if cwd is not None:
        kwargs["cwd"] = cwd
    return OpenClawBackend(**kwargs)


register_local_backend("openclaw", _build_openclaw)
