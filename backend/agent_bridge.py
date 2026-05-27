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

import os
from typing import AsyncIterator, Optional

from agents.base import AgentBackend, AgentEvent, TurnContext
from agents.local_acp import LocalAcpBackend
from agents.remote_acp import RemoteAcpBackend
from config import agent_enabled
from database import (
    get_agent_instance,
    get_conversation,
    get_conversation_session_id,
    update_conversation_session_id,
)


def _resolve_token(raw: str) -> str:
    """Resolve a token reference that may be a literal or `env:VAR_NAME`."""
    if raw.startswith("env:"):
        return os.environ.get(raw[len("env:"):], "")
    return raw


def _resolve_backend(conversation_id: Optional[str]) -> AgentBackend:
    """Pick the right AgentBackend for this turn.

    Resolution order:
      1. No conversation_id (voice without conversation, legacy callers) → Local.
      2. Conversation row missing or its agent_id is NULL → Local (AC-W1-B1).
      3. agent_instance.transport == "local-acp" → LocalAcpBackend.
      4. agent_instance.transport == "remote-acp" → RemoteAcpBackend, with
         token resolved via `_resolve_token()`.
      5. Anything else → Local (forward-compat for future transports).
    """
    if not conversation_id:
        return LocalAcpBackend()

    conv = get_conversation(conversation_id)
    agent_id = conv.get("agent_id") if conv else None
    if not agent_id:
        return LocalAcpBackend()

    agent = get_agent_instance(agent_id)
    if not agent:
        return LocalAcpBackend()

    transport = agent.get("transport")
    if transport == "remote-acp":
        cfg = agent.get("transport_config") or {}
        return RemoteAcpBackend(
            url=cfg.get("url", ""),
            token=_resolve_token(cfg.get("token", "")),
            system_prompt_override=agent.get("system_prompt_override"),
        )
    return LocalAcpBackend(
        system_prompt_override=agent.get("system_prompt_override"),
    )


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

    backend = _resolve_backend(conversation_id)
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
