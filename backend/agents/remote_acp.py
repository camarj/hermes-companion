"""Remote Hermes agent backend (AC-W1-R3, R4, R5; AC-W1-U5 full).

Connects to a `hermes-companion` instance running in host mode over the
authenticated WebSocket bridge documented at `/api/host/acp`. The bridge
ferries JSON-RPC frames to/from a remote `hermes acp` subprocess; this
backend speaks the same ACP protocol as `LocalAcpBackend`, so chat,
voice, and vision feel identical to the user.

Two HTTP preconditions sit beside the WS turn:
  * vision frames upload to `POST /api/host/upload` and travel as ACP
    `resource_link` content blocks pointing at the returned handle; the
    raw bytes never cross the wire inside the prompt (AC-W1-R4).
  * a non-empty `system_prompt_override` POSTs to
    `POST /api/host/config/system-prompt`, and the returned `cwd` is
    passed to `session/new` so Hermes' prompt builder picks up the new
    `AGENTS.md` (AC-W1-U5 full).
"""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from typing import AsyncIterator, Awaitable, Callable, Optional, Protocol
from urllib.parse import urlsplit, urlunsplit

import httpx
import websockets
from websockets.exceptions import ConnectionClosed

from .base import AgentBackend, AgentEvent, TurnContext


class _WSLike(Protocol):
    async def send(self, message: str) -> None: ...
    async def recv(self) -> str: ...
    async def close(self) -> None: ...


WSConnector = Callable[..., Awaitable[_WSLike]]
HttpClientFactory = Callable[..., httpx.AsyncClient]


def _http_base_from_ws(ws_url: str) -> str:
    """Derive the HTTP base URL from the WS URL the bridge lives at.

    `ws://host:8000/api/host/acp` → `http://host:8000`
    `wss://host/api/host/acp`     → `https://host`
    """
    parts = urlsplit(ws_url)
    scheme = {"ws": "http", "wss": "https"}.get(parts.scheme, parts.scheme)
    return urlunsplit((scheme, parts.netloc, "", "", ""))


@asynccontextmanager
async def _default_ws_connector(url: str, *, headers: dict[str, str]) -> _WSLike:
    """Production WS connector. Tests pass their own factory."""
    async with websockets.connect(url, additional_headers=headers) as ws:
        yield ws  # type: ignore[misc]


class RemoteAcpBackend(AgentBackend):
    def __init__(
        self,
        *,
        url: str,
        token: str,
        system_prompt_override: Optional[str] = None,
        ws_connector: Optional[Callable] = None,
        http_client_factory: Optional[HttpClientFactory] = None,
    ) -> None:
        self._url = url
        self._token = token
        self._system_prompt = system_prompt_override
        self._ws_connector = ws_connector or _default_ws_connector
        self._http_factory = http_client_factory or httpx.AsyncClient

    def _auth_headers(self, context: TurnContext) -> dict[str, str]:
        headers = {"Authorization": f"Bearer {self._token}"}
        if context.user_id:
            headers["X-Requester-Id"] = context.user_id
        if context.user_name:
            headers["X-Requester-Name"] = context.user_name
        if context.user_role:
            headers["X-Requester-Role"] = context.user_role
        return headers

    async def _materialize_system_prompt(self, headers: dict[str, str]) -> Optional[str]:
        if not self._system_prompt or not self._system_prompt.strip():
            return None
        base = _http_base_from_ws(self._url)
        async with self._http_factory() as client:
            resp = await client.post(
                f"{base}/api/host/config/system-prompt",
                headers=headers,
                json={"system_prompt": self._system_prompt},
            )
            resp.raise_for_status()
            return resp.json()["cwd"]

    async def _upload_images(
        self,
        headers: dict[str, str],
        image_paths: list[str],
    ) -> list[dict]:
        """Upload each image; return ACP resource_link blocks referencing handles."""
        base = _http_base_from_ws(self._url)
        blocks: list[dict] = []
        async with self._http_factory() as client:
            for path in image_paths:
                with open(path, "rb") as fp:
                    files = {"file": (path, fp.read(), _guess_mime(path))}
                resp = await client.post(
                    f"{base}/api/host/upload",
                    headers=headers,
                    files=files,
                )
                resp.raise_for_status()
                body = resp.json()
                blocks.append({
                    "type": "resource_link",
                    "uri": f"file://{body['handle']}",
                    "mimeType": body.get("mime_type", "application/octet-stream"),
                })
        return blocks

    async def stream(
        self,
        query: str,
        context: TurnContext,
        *,
        image_paths: list[str] | None = None,
    ) -> AsyncIterator[AgentEvent]:
        # AC-W3-A1 limitation: RemoteAcpBackend yields NO ("cwd", ...) event.
        # The agent's working directory lives on the remote host's filesystem;
        # the companion process cannot walk it locally. The artifact capture
        # facade skips the scan when no cwd event is received. Capturing remote
        # artifacts would require a host-side listing+download endpoint that
        # does not exist. This is a documented limitation, not a TODO.
        auth = self._auth_headers(context)

        try:
            cwd = await self._materialize_system_prompt(auth)
        except Exception:
            cwd = None

        image_blocks: list[dict] = []
        if image_paths:
            try:
                image_blocks = await self._upload_images(auth, image_paths)
            except Exception:
                image_blocks = []

        content_blocks: list[dict] = [{"type": "text", "text": query}] + image_blocks

        next_id = 0

        def _id() -> int:
            nonlocal next_id
            next_id += 1
            return next_id

        try:
            async with self._ws_connector(self._url, headers=auth) as ws:
                # initialize
                init_id = _id()
                await ws.send(json.dumps({
                    "jsonrpc": "2.0", "id": init_id, "method": "initialize",
                    "params": {"protocolVersion": 1, "clientCapabilities": {}},
                }))
                await _await_result(ws, init_id)

                # session/new or session/load
                session_id = await _open_session(
                    ws, _id, context.session_id, cwd or "/tmp",
                )
                yield ("session", session_id)

                # session/prompt + stream
                prompt_id = _id()
                await ws.send(json.dumps({
                    "jsonrpc": "2.0", "id": prompt_id, "method": "session/prompt",
                    "params": {"sessionId": session_id, "prompt": content_blocks},
                }))

                async for event in _consume_until_done(ws, prompt_id):
                    yield event
        except (ConnectionClosed, ConnectionError, asyncio.IncompleteReadError, OSError):
            yield ("text", "[connection lost — retry]")
            yield ("done", None)
            return


async def _await_result(ws: _WSLike, msg_id: int) -> dict:
    while True:
        raw = await ws.recv()
        msg = json.loads(raw)
        if msg.get("id") == msg_id and "result" in msg:
            return msg["result"]


async def _open_session(
    ws: _WSLike,
    next_id: Callable[[], int],
    prior_session_id: Optional[str],
    cwd: str,
) -> str:
    if prior_session_id:
        msg_id = next_id()
        await ws.send(json.dumps({
            "jsonrpc": "2.0", "id": msg_id, "method": "session/load",
            "params": {
                "sessionId": prior_session_id,
                "cwd": cwd,
                "mcpServers": [],
            },
        }))
        result = await _await_result(ws, msg_id)
        return result.get("sessionId", prior_session_id)

    msg_id = next_id()
    await ws.send(json.dumps({
        "jsonrpc": "2.0", "id": msg_id, "method": "session/new",
        "params": {"cwd": cwd, "mcpServers": []},
    }))
    result = await _await_result(ws, msg_id)
    return result["sessionId"]


async def _consume_until_done(ws: _WSLike, prompt_id: int) -> AsyncIterator[AgentEvent]:
    while True:
        raw = await ws.recv()
        msg = json.loads(raw)
        if msg.get("method") == "session/update":
            mapped = _map_update(msg.get("params", {}).get("update", {}))
            if mapped is not None:
                yield mapped
            continue
        if msg.get("id") == prompt_id and "result" in msg:
            yield ("done", None)
            return


def _map_update(update: dict) -> AgentEvent | None:
    kind = update.get("sessionUpdate")
    if kind == "agent_thought_chunk":
        text = (update.get("content") or {}).get("text")
        if isinstance(text, str):
            return ("reasoning", text)
    elif kind == "agent_message_chunk":
        text = (update.get("content") or {}).get("text")
        if isinstance(text, str):
            return ("text", text)
    return None


def _guess_mime(path: str) -> str:
    import mimetypes
    mime, _ = mimetypes.guess_type(path)
    return mime or "application/octet-stream"
