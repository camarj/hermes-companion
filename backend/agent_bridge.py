"""Thin facade over the polymorphic AgentBackend layer.

`main.py` and `realtime.py` import `call_agent`, `call_agent_stream`, and
`call_agent_for_voice` from here. These signatures are preserved across
the Fase 1 ACP migration so the call sites do not change. Internally the
facade builds a `TurnContext` from the loose kwargs and delegates to the
backend returned by `_resolve_backend()`.

Wave 2 will extend `_resolve_backend` to look up the conversation's
`agent_id` and instantiate the matching backend type. For Wave 1 it
always returns a `LocalAcpBackend` — every chat goes to the local
`hermes acp` subprocess via the standardised protocol.
"""

from __future__ import annotations

from typing import AsyncIterator

from agents.base import AgentBackend, AgentEvent, TurnContext
from agents.local_acp import LocalAcpBackend
from config import agent_enabled
from database import (
    get_conversation_session_id,
    update_conversation_session_id,
)


def _resolve_backend() -> AgentBackend:
    """Hook for tests + Wave 2 per-conversation backend resolution.

    Wave 1: always LocalAcpBackend (one global Hermes process per turn).
    """
    return LocalAcpBackend()


_DISABLED_MESSAGE = (
    "No external agent is configured. Set `agent.command` in config.yaml."
)


def _flatten_for_voice(text: str) -> str:
    """Strip markdown bullets/headings so TTS doesn't stutter on punctuation."""
    cleaned: list[str] = []
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        while s and s[0] in "-*#> ":
            s = s[1:].lstrip()
        cleaned.append(s)
    return " ".join(cleaned).strip() or text


async def call_agent_stream(
    query: str,
    user_name: str = "",
    user_id: str = "",
    user_role: str = "",
    *,
    image_paths: list[str] | None = None,
    conversation_id: str | None = None,
    log_prefix: str = "[agent/local_acp]",
) -> AsyncIterator[tuple[str, str]]:
    """Yield `(kind, text)` tuples for each AgentEvent of kind text or reasoning.

    The terminal `("done", None)` event is consumed internally; callers
    just iterate until the generator is exhausted (matches the old
    contract).

    When `conversation_id` is given (AC-W1-D4), the facade:
      * loads the stored `hermes_session_id` and puts it on the
        TurnContext so the backend resumes the native session;
      * captures the `("session", id)` event the backend emits and
        persists it back to the conversation row if it changed.
    """
    if not agent_enabled():
        yield ("text", _DISABLED_MESSAGE)
        return

    prior_session = get_conversation_session_id(conversation_id) if conversation_id else None

    backend = _resolve_backend()
    context = TurnContext(
        user_id=user_id,
        user_name=user_name,
        user_role=user_role,
        session_id=prior_session,
    )
    print(f"{log_prefix} stream user={user_id} query={query[:80]!r}")

    async for kind, payload in backend.stream(query, context, image_paths=image_paths):
        if kind == "done":
            return
        if kind == "session" and isinstance(payload, str):
            if conversation_id and payload != prior_session:
                update_conversation_session_id(conversation_id, payload)
            continue
        if kind in ("text", "reasoning") and isinstance(payload, str):
            yield (kind, payload)
        # "tool" events not yet surfaced in the UI — silently dropped.


async def call_agent(
    query: str,
    user_name: str = "",
    user_id: str = "",
    user_role: str = "",
    *,
    conversation_id: str | None = None,
    log_prefix: str = "[agent]",
) -> str:
    """Run a turn and return the full assistant message as one string."""
    parts: list[str] = []
    async for kind, payload in call_agent_stream(
        query,
        user_name=user_name,
        user_id=user_id,
        user_role=user_role,
        conversation_id=conversation_id,
        log_prefix=log_prefix,
    ):
        if kind == "text":
            parts.append(payload)
    return "".join(parts) or "The agent returned no answer."


async def call_agent_for_voice(
    query: str,
    user_name: str = "",
    user_id: str = "",
    user_role: str = "",
    *,
    conversation_id: str | None = None,
) -> str:
    """Voice variant: flattens bullets / headings so TTS reads naturally."""
    answer = await call_agent(
        query,
        user_name=user_name,
        user_id=user_id,
        user_role=user_role,
        conversation_id=conversation_id,
        log_prefix="[realtime/agent]",
    )
    return _flatten_for_voice(answer)
