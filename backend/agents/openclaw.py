"""OpenClaw agent backend (AC-W2-A2, PRD §5.2/§5.3).

OpenClaw speaks ACP over stdio via `openclaw acp`, the same shape as
`hermes acp`, so this backend reuses `acp_client` and mirrors
`LocalAcpBackend`'s flow with a different spawn command + gateway auth.

Two intentional differences from the Hermes backend:
  * **No reasoning frames.** OpenClaw's stdio bridge emits text + `tool_call`
    but not thought/plan updates, so no `("reasoning", …)` events appear. The
    UI already degrades gracefully (no thinking block).
  * **system_prompt_override is not yet applied.** The Hermes backend
    materializes AGENTS.md in the session cwd, which is Hermes-specific.
    OpenClaw manages its own prompt/config, so the override is accepted but
    inert for now — a documented capability gap, not a silent drop.
"""

from __future__ import annotations

from functools import partial
from typing import AsyncIterator, Optional

from acp_client import spawn_openclaw_acp

from .base import AgentBackend, AgentEvent, TurnContext
from .local_acp import AcpClientFactory, _build_env, _build_prompt_blocks


class OpenClawBackend(AgentBackend):
    def __init__(
        self,
        *,
        gateway_url: Optional[str] = None,
        gateway_token: Optional[str] = None,
        client_factory: AcpClientFactory | None = None,
        system_prompt_override: Optional[str] = None,
    ) -> None:
        # Stored but inert for now — see module docstring (capability gap).
        self._system_prompt = system_prompt_override
        self._client_factory: AcpClientFactory = client_factory or partial(
            spawn_openclaw_acp, url=gateway_url, token=gateway_token
        )

    async def stream(
        self,
        query: str,
        context: TurnContext,
        *,
        image_paths: list[str] | None = None,
    ) -> AsyncIterator[AgentEvent]:
        env = _build_env(context)
        content_blocks = _build_prompt_blocks(query, image_paths)
        async with self._client_factory(env=env) as client:
            await client.initialize()
            if context.session_id:
                session_id = await client.load_session(context.session_id, cwd="/tmp")
            else:
                session_id = await client.new_session(cwd="/tmp")
            yield ("session", session_id)
            async for event in client.prompt(session_id, content_blocks):
                yield event
