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
import tempfile
from pathlib import Path
from typing import AsyncContextManager, AsyncIterator, Callable, Optional

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
        cwd: Optional[str] = None,
        client_factory: AcpClientFactory | None = None,
        system_prompt_override: Optional[str] = None,
    ) -> None:
        # When no cwd is supplied (e.g. fallback path with no conversation_id),
        # create an isolated tmpdir so we never land in the shared /tmp root.
        self._cwd = cwd if cwd is not None else tempfile.mkdtemp(prefix="hermes-companion-local-")
        self._system_prompt = system_prompt_override
        # Default to the real spawn; tests pass an asynccontextmanager fake.
        self._client_factory: AcpClientFactory = client_factory or spawn_hermes_acp

    def _resolve_session_cwd(self) -> str:
        """Materialize AGENTS.md inside the configured cwd when an override is set
        (AC-W1-U5). Hermes reads AGENTS.md from the session cwd as part of its
        prompt builder — that's the only knob it respects for an external system
        prompt.

        When a system_prompt_override is present we create a per-session subdir
        inside self._cwd so the AGENTS.md is isolated per-turn while still living
        under the conversation-scoped workdir (FIX 1). When no override is set we
        use self._cwd directly.
        """
        if not self._system_prompt or not self._system_prompt.strip():
            return self._cwd
        session_dir = Path(tempfile.mkdtemp(prefix="hermes-companion-local-", dir=self._cwd))
        (session_dir / "AGENTS.md").write_text(
            self._system_prompt, encoding="utf-8",
        )
        return str(session_dir)

    async def stream(
        self,
        query: str,
        context: TurnContext,
        *,
        image_paths: list[str] | None = None,
    ) -> AsyncIterator[AgentEvent]:
        env = _build_env(context)
        content_blocks = _build_prompt_blocks(query, image_paths)
        cwd = self._resolve_session_cwd()
        yield ("cwd", cwd)
        async with self._client_factory(env=env) as client:
            await client.initialize()
            if context.session_id:
                session_id = await client.load_session(
                    context.session_id, cwd=cwd,
                )
            else:
                session_id = await client.new_session(cwd=cwd)
            # Surface the id so the facade can persist it on the
            # conversation row (AC-W1-D4) — facade strips this event
            # before forwarding to the SSE stream.
            yield ("session", session_id)
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
