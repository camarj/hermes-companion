"""Local Hermes agent backend (AC-W1-L1, L2, L3).

Spawns `hermes acp` as a subprocess and yields events through the ACP
client built in the spike (`backend/acp_client.py`). Replaces the
banner-regex parser in the legacy `agent_bridge.py:call_agent_stream`
path while preserving the same `AgentEvent` shape the frontend consumes.

Identity propagation continues to use the existing `AGENT_REQUESTER_*`
environment variables so Hermes' own user-scoping logic keeps working
unchanged.
"""

from __future__ import annotations

import base64
import mimetypes
from pathlib import Path
from typing import AsyncContextManager, AsyncIterator, Callable

from acp_client import AcpClient, spawn_hermes_acp

from .base import AgentBackend, AgentEvent, TurnContext


# A factory takes optional env and returns an async context manager
# yielding an AcpClient-like object. Production uses spawn_hermes_acp;
# tests inject a fake to avoid spawning the real subprocess.
AcpClientFactory = Callable[..., AsyncContextManager[AcpClient]]


def _build_env(context: TurnContext) -> dict[str, str]:
    """Reproduce the env contract Hermes already understands.

    Hermes reads `AGENT_REQUESTER_*` to scope memory and integrations to
    the requesting user. `PYTHONUNBUFFERED=1` keeps stdout flushed so
    streaming arrives promptly instead of in a 4KB chunk at process exit.
    """
    env: dict[str, str] = {
        "AGENT_REQUESTER_ID": context.user_id,
        "AGENT_REQUESTER_NAME": context.user_name,
        "PYTHONUNBUFFERED": "1",
    }
    if context.user_role:
        env["AGENT_REQUESTER_ROLE"] = context.user_role
    return env


class LocalAcpBackend(AgentBackend):
    def __init__(
        self,
        *,
        cwd: str = "/tmp",
        client_factory: AcpClientFactory | None = None,
    ) -> None:
        self._cwd = cwd
        # Default to the real spawn; tests pass an asynccontextmanager fake.
        self._client_factory: AcpClientFactory = client_factory or spawn_hermes_acp

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
            session_id = await client.new_session(cwd=self._cwd)
            async for event in client.prompt(session_id, content_blocks):
                yield event


def _build_prompt_blocks(
    query: str,
    image_paths: list[str] | None,
) -> list[dict]:
    """Assemble the ACP `prompt` array: the user text first, then any
    images inlined as `{type, data, mimeType}` content blocks.

    Images are base64-encoded from disk; no upload step occurs. This is
    what distinguishes the local path from `RemoteAcpBackend`, which
    uploads to the host sidecar first (AC-W1-R4).
    """
    blocks: list[dict] = [{"type": "text", "text": query}]
    for path in image_paths or []:
        data = Path(path).read_bytes()
        blocks.append({
            "type": "image",
            "data": base64.b64encode(data).decode("ascii"),
            "mimeType": _guess_mime(path),
        })
    return blocks


def _guess_mime(path: str) -> str:
    mime, _ = mimetypes.guess_type(path)
    return mime or "application/octet-stream"
