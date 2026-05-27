"""Polymorphic agent backend contract (AC-W1-A1, AC-W1-A2).

Every agent type — Hermes local, Hermes remote, OpenClaw, future custom
backends — implements `AgentBackend.stream(...)` and yields events of
the discriminated union `AgentEvent`. The SSE chat endpoint and the
Realtime voice tool consume the same shapes the existing frontend
already renders, so the contract is preserved across the migration.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import AsyncIterator


AgentEvent = tuple[str, object]
"""Discriminated union the frontend already consumes.

One of:
  ("text", str)        — final-answer chunk; rendered as the assistant bubble.
  ("reasoning", str)   — chain-of-thought chunk; rendered as a thinking block.
  ("tool", dict)       — tool-call notification; rendered as a tool preview.
  ("done", None)       — terminator; signals the turn is complete.
"""


_VALID_KINDS = frozenset({"text", "reasoning", "tool", "done"})


def is_agent_event(value: object) -> bool:
    """Type guard for AgentEvent. Used by tests and defensive backends."""
    if not isinstance(value, tuple) or len(value) != 2:
        return False
    kind, payload = value
    if kind not in _VALID_KINDS:
        return False
    if kind in ("text", "reasoning"):
        return isinstance(payload, str)
    if kind == "tool":
        return isinstance(payload, dict)
    if kind == "done":
        return payload is None
    return False


@dataclass(frozen=True)
class TurnContext:
    """Carries who is asking. Propagated to the agent so it can scope work
    to the requesting user (memory, integrations, permissions)."""

    user_id: str
    user_name: str = ""
    user_role: str = ""


class AgentBackend(ABC):
    """Abstract contract for any agent backend the UI can talk to.

    Implementations:
      LocalAcpBackend   — spawns `hermes acp` as a subprocess (Wave 1).
      RemoteAcpBackend  — connects to a sidecar over WSS (Wave 1).
      OpenClawBackend   — Wave 2.
    """

    @abstractmethod
    async def stream(
        self,
        query: str,
        context: TurnContext,
        *,
        image_paths: list[str] | None = None,
    ) -> AsyncIterator[AgentEvent]:
        """Run one turn and yield events until completion.

        The generator MUST yield a terminal `("done", None)` event, even
        on internal failure (so callers can always shut down cleanly).
        """
        # Body is unreachable but Python requires it for AsyncIterator return.
        # Subclasses use `async def` + `yield`; this stub exists only to
        # advertise the signature on the ABC.
        if False:
            yield  # pragma: no cover
