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
  ("session", str)     — native session id from the agent; consumed by the
                         facade for persistence + resume. Not forwarded to UI.
  ("done", None)       — terminator; signals the turn is complete.
  ("cwd", str)         — working directory for this turn; consumed by the
                         facade for artifact capture. Not forwarded to UI.
  ("artifact", dict)   — persisted artifact metadata; forwarded to the SSE
                         endpoint for attribution. Not forwarded as UI text.
"""


_VALID_KINDS = frozenset({"text", "reasoning", "tool", "session", "done", "cwd", "artifact"})


def is_agent_event(value: object) -> bool:
    """Type guard for AgentEvent. Used by tests and defensive backends."""
    if not isinstance(value, tuple) or len(value) != 2:
        return False
    kind, payload = value
    if kind not in _VALID_KINDS:
        return False
    if kind in ("text", "reasoning", "session", "cwd"):
        return isinstance(payload, str)
    if kind in ("tool", "artifact"):
        return isinstance(payload, dict)
    if kind == "done":
        return payload is None
    return False


@dataclass(frozen=True)
class TurnContext:
    """Per-turn metadata propagated to the agent.

    `session_id` is the agent's native session id (e.g. Hermes' ACP
    `sessionId`) when resuming a prior conversation. None means "start a
    fresh session". The facade fills this from
    `conversations.hermes_session_id` so each backend can decide whether
    to resume natively or replay context.
    """

    user_id: str
    user_name: str = ""
    user_role: str = ""
    session_id: str | None = None


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
