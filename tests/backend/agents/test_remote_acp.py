"""RemoteAcpBackend — AC-W1-R3, R4, R5 + U5 full.

Hermetic: a fake WS client replaces websockets.connect, and httpx requests
are intercepted by an httpx.MockTransport. No subprocesses, no network.
"""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from typing import Any

import httpx
import pytest
from websockets.exceptions import ConnectionClosed

from agents.base import TurnContext
from agents.remote_acp import RemoteAcpBackend


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakeWS:
    """Minimal stand-in for a websockets client connection."""

    def __init__(self) -> None:
        self.sent: list[str] = []
        self._recv_queue: asyncio.Queue[str | Exception] = asyncio.Queue()
        self.closed = False

    async def send(self, message: str) -> None:
        self.sent.append(message)

    async def recv(self) -> str:
        item = await self._recv_queue.get()
        if isinstance(item, Exception):
            raise item
        return item

    async def close(self) -> None:
        self.closed = True

    def push(self, frame: dict) -> None:
        self._recv_queue.put_nowait(json.dumps(frame))

    def push_close(self) -> None:
        self._recv_queue.put_nowait(ConnectionClosed(None, None))

    def sent_frames(self) -> list[dict]:
        return [json.loads(s) for s in self.sent]


@pytest.fixture
def fake_ws() -> _FakeWS:
    return _FakeWS()


@pytest.fixture
def ws_connector(fake_ws):
    """Factory whose returned async context manager yields the same fake."""
    captured: dict[str, Any] = {}

    @asynccontextmanager
    async def _connector(url, *, headers):
        captured["url"] = url
        captured["headers"] = headers
        yield fake_ws

    _connector.captured = captured  # type: ignore[attr-defined]
    return _connector


@pytest.fixture
def http_factory():
    """Capture HTTP requests via an httpx MockTransport."""
    recorded: list[httpx.Request] = []
    responses: dict[str, dict] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        recorded.append(request)
        body = responses.get(str(request.url), {})
        return httpx.Response(200, json=body)

    transport = httpx.MockTransport(handler)

    def factory() -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=transport)

    factory.recorded = recorded  # type: ignore[attr-defined]
    factory.responses = responses  # type: ignore[attr-defined]
    return factory


# ---------------------------------------------------------------------------
# Cycle 1: WS connect with bearer + identity headers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ws_opens_with_bearer_and_identity_headers(
    fake_ws, ws_connector, http_factory,
):
    backend = RemoteAcpBackend(
        url="ws://host:8000/api/host/acp",
        token="T1",
        ws_connector=ws_connector,
        http_client_factory=http_factory,
    )

    fake_ws.push({"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": 1}})
    fake_ws.push({"jsonrpc": "2.0", "id": 2, "result": {"sessionId": "S"}})
    fake_ws.push({"jsonrpc": "2.0", "id": 3, "result": {"stopReason": "end_turn"}})

    ctx = TurnContext(user_id="alice", user_name="Alice", user_role="CEO")
    events = [ev async for ev in backend.stream("hi", ctx)]

    assert ws_connector.captured["url"] == "ws://host:8000/api/host/acp"
    headers = ws_connector.captured["headers"]
    assert headers["Authorization"] == "Bearer T1"
    assert headers["X-Requester-Id"] == "alice"
    assert headers["X-Requester-Name"] == "Alice"
    assert headers["X-Requester-Role"] == "CEO"
    # Sanity: turn completed.
    assert events[-1] == ("done", None)


# ---------------------------------------------------------------------------
# Cycle 2: AC-W1-R3 — round-trip events match LocalAcpBackend shape
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_round_trip_yields_acp_events_in_order(
    fake_ws, ws_connector, http_factory,
):
    backend = RemoteAcpBackend(
        url="ws://h/api/host/acp", token="T",
        ws_connector=ws_connector, http_client_factory=http_factory,
    )

    fake_ws.push({"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": 1}})
    fake_ws.push({"jsonrpc": "2.0", "id": 2, "result": {"sessionId": "sess-xyz"}})
    # Streamed updates between session/prompt request and its response.
    fake_ws.push({
        "jsonrpc": "2.0", "method": "session/update",
        "params": {"update": {
            "sessionUpdate": "agent_thought_chunk",
            "content": {"type": "text", "text": "thinking…"},
        }},
    })
    fake_ws.push({
        "jsonrpc": "2.0", "method": "session/update",
        "params": {"update": {
            "sessionUpdate": "agent_message_chunk",
            "content": {"type": "text", "text": "hello"},
        }},
    })
    fake_ws.push({"jsonrpc": "2.0", "id": 3, "result": {"stopReason": "end_turn"}})

    events = [
        ev async for ev in backend.stream("hi", TurnContext(user_id="u"))
    ]

    assert events == [
        ("session", "sess-xyz"),
        ("reasoning", "thinking…"),
        ("text", "hello"),
        ("done", None),
    ]
    # And the prompt was the expected JSON-RPC frame.
    sent = fake_ws.sent_frames()
    assert sent[0]["method"] == "initialize"
    assert sent[1]["method"] == "session/new"
    assert sent[2]["method"] == "session/prompt"
    assert sent[2]["params"]["sessionId"] == "sess-xyz"
    assert sent[2]["params"]["prompt"] == [{"type": "text", "text": "hi"}]


# ---------------------------------------------------------------------------
# Cycle 3: session resume via session/load
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resume_calls_session_load_when_session_id_present(
    fake_ws, ws_connector, http_factory,
):
    backend = RemoteAcpBackend(
        url="ws://h/api/host/acp", token="T",
        ws_connector=ws_connector, http_client_factory=http_factory,
    )

    fake_ws.push({"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": 1}})
    fake_ws.push({"jsonrpc": "2.0", "id": 2, "result": {"sessionId": "prior-S"}})
    fake_ws.push({"jsonrpc": "2.0", "id": 3, "result": {"stopReason": "end_turn"}})

    ctx = TurnContext(user_id="u", session_id="prior-S")
    [_ async for _ in backend.stream("hi", ctx)]

    methods = [f["method"] for f in fake_ws.sent_frames()]
    assert methods == ["initialize", "session/load", "session/prompt"]
    load_params = fake_ws.sent_frames()[1]["params"]
    assert load_params["sessionId"] == "prior-S"


# ---------------------------------------------------------------------------
# Cycle 4: AC-W1-R5 — WS disconnect mid-stream
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_disconnect_mid_stream_yields_retry_and_done(
    fake_ws, ws_connector, http_factory,
):
    backend = RemoteAcpBackend(
        url="ws://h/api/host/acp", token="T",
        ws_connector=ws_connector, http_client_factory=http_factory,
    )

    fake_ws.push({"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": 1}})
    fake_ws.push({"jsonrpc": "2.0", "id": 2, "result": {"sessionId": "S"}})
    fake_ws.push({
        "jsonrpc": "2.0", "method": "session/update",
        "params": {"update": {
            "sessionUpdate": "agent_message_chunk",
            "content": {"type": "text", "text": "hel"},
        }},
    })
    fake_ws.push_close()  # host dies mid-stream

    events = [ev async for ev in backend.stream("hi", TurnContext(user_id="u"))]
    assert events[-2:] == [
        ("text", "[connection lost — retry]"),
        ("done", None),
    ]


# ---------------------------------------------------------------------------
# Cycle 5: AC-W1-U5 full — system prompt POST precedes session/new
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_system_prompt_override_creates_cwd_and_uses_it(
    fake_ws, ws_connector, http_factory,
):
    http_factory.responses[
        "http://host:8000/api/host/config/system-prompt"
    ] = {"cwd": "/tmp/hermes-companion-uploads/sp-abc"}

    backend = RemoteAcpBackend(
        url="ws://host:8000/api/host/acp",
        token="T1",
        system_prompt_override="You are terse.",
        ws_connector=ws_connector,
        http_client_factory=http_factory,
    )

    fake_ws.push({"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": 1}})
    fake_ws.push({"jsonrpc": "2.0", "id": 2, "result": {"sessionId": "S"}})
    fake_ws.push({"jsonrpc": "2.0", "id": 3, "result": {"stopReason": "end_turn"}})

    ctx = TurnContext(user_id="u", user_name="U")
    [_ async for _ in backend.stream("hi", ctx)]

    # HTTP precondition: one POST to /api/host/config/system-prompt with the bearer.
    sp_requests = [
        r for r in http_factory.recorded
        if r.url.path == "/api/host/config/system-prompt"
    ]
    assert len(sp_requests) == 1
    assert sp_requests[0].headers["Authorization"] == "Bearer T1"
    body = json.loads(sp_requests[0].content)
    assert body["system_prompt"] == "You are terse."

    # And the returned cwd reached the session/new frame.
    session_new = fake_ws.sent_frames()[1]
    assert session_new["method"] == "session/new"
    assert session_new["params"]["cwd"] == "/tmp/hermes-companion-uploads/sp-abc"


@pytest.mark.asyncio
async def test_no_system_prompt_skips_http_call(
    fake_ws, ws_connector, http_factory,
):
    backend = RemoteAcpBackend(
        url="ws://host:8000/api/host/acp", token="T1",
        ws_connector=ws_connector, http_client_factory=http_factory,
    )

    fake_ws.push({"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": 1}})
    fake_ws.push({"jsonrpc": "2.0", "id": 2, "result": {"sessionId": "S"}})
    fake_ws.push({"jsonrpc": "2.0", "id": 3, "result": {"stopReason": "end_turn"}})

    [_ async for _ in backend.stream("hi", TurnContext(user_id="u"))]

    assert not any(
        r.url.path == "/api/host/config/system-prompt"
        for r in http_factory.recorded
    )


# ---------------------------------------------------------------------------
# Cycle 6: AC-W1-R4 — vision upload precedes prompt; block references handle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_vision_uploads_each_frame_and_references_handle(
    fake_ws, ws_connector, http_factory, tmp_path,
):
    img = tmp_path / "frame.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\nbytes")

    http_factory.responses["http://h/api/host/upload"] = {
        "handle": "/srv/uploads/abc.png",
        "size": 14,
        "mime_type": "image/png",
        "filename": "frame.png",
    }

    backend = RemoteAcpBackend(
        url="ws://h/api/host/acp", token="T",
        ws_connector=ws_connector, http_client_factory=http_factory,
    )

    fake_ws.push({"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": 1}})
    fake_ws.push({"jsonrpc": "2.0", "id": 2, "result": {"sessionId": "S"}})
    fake_ws.push({"jsonrpc": "2.0", "id": 3, "result": {"stopReason": "end_turn"}})

    [
        _ async for _ in backend.stream(
            "what's this?",
            TurnContext(user_id="u"),
            image_paths=[str(img)],
        )
    ]

    # HTTP precondition: one POST to /api/host/upload, multipart.
    upload_requests = [
        r for r in http_factory.recorded
        if r.url.path == "/api/host/upload"
    ]
    assert len(upload_requests) == 1
    assert upload_requests[0].headers["Authorization"] == "Bearer T"
    assert b"multipart/form-data" in upload_requests[0].headers["content-type"].encode()

    # ACP prompt references the handle, NOT the local path (AC-W1-R4).
    prompt_frame = fake_ws.sent_frames()[2]
    blocks = prompt_frame["params"]["prompt"]
    assert blocks[0] == {"type": "text", "text": "what's this?"}
    assert blocks[1]["type"] == "resource_link"
    assert blocks[1]["uri"] == "file:///srv/uploads/abc.png"
    assert blocks[1]["mimeType"] == "image/png"
    # Crucially: the original local path is gone.
    assert str(img) not in json.dumps(blocks)
