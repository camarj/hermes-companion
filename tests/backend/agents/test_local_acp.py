"""AC-W1-L1, L2: LocalAcpBackend streaming + identity propagation.

The backend is exercised against a fake AcpClient injected via a
`client_factory` callable, so tests don't pay the ~2 s cost of spawning
`hermes acp` for each assertion. The real subprocess path is covered by
the existing spike CLI (`python -m acp_client …`) and by manual smoke.
"""

import base64
from contextlib import asynccontextmanager
from pathlib import Path

import pytest

from agents.base import TurnContext
from agents.local_acp import LocalAcpBackend


class _FakeAcpClient:
    def __init__(self, events: list) -> None:
        self._events = events
        self.prompts_received: list[tuple[str, list[dict]]] = []
        self.session_cwd: str | None = None

    async def initialize(self) -> dict:
        return {"agentInfo": {"name": "hermes-agent", "version": "fake"}}

    async def new_session(self, cwd: str = "/tmp") -> str:
        self.session_cwd = cwd
        return "fake-session-id"

    async def prompt(self, session_id: str, content_blocks: list[dict]):
        self.prompts_received.append((session_id, content_blocks))
        for ev in self._events:
            yield ev


def _make_factory(events: list):
    """Build a factory CM that records the env it was called with."""
    captured: dict = {"env": None, "client": None}

    @asynccontextmanager
    async def factory(*, env: dict | None = None):
        captured["env"] = env
        client = _FakeAcpClient(events)
        captured["client"] = client
        yield client

    factory.captured = captured  # type: ignore[attr-defined]
    return factory


async def test_local_acp_round_trips_query_with_streaming():
    factory = _make_factory(
        [
            ("reasoning", "thinking"),
            ("text", "hello"),
            ("done", None),
        ]
    )
    backend = LocalAcpBackend(client_factory=factory)
    ctx = TurnContext(user_id="alice", user_name="Alice")

    events = [ev async for ev in backend.stream("ping", ctx)]

    assert events == [
        ("reasoning", "thinking"),
        ("text", "hello"),
        ("done", None),
    ]
    assert factory.captured["client"].prompts_received == [
        ("fake-session-id", [{"type": "text", "text": "ping"}]),
    ]


async def test_local_acp_propagates_user_identity_via_env():
    factory = _make_factory([("done", None)])
    backend = LocalAcpBackend(client_factory=factory)
    ctx = TurnContext(user_id="alice", user_name="Alice", user_role="CEO")

    async for _ in backend.stream("q", ctx):
        pass

    env = factory.captured["env"]
    assert env["AGENT_REQUESTER_ID"] == "alice"
    assert env["AGENT_REQUESTER_NAME"] == "Alice"
    assert env["AGENT_REQUESTER_ROLE"] == "CEO"


async def test_local_acp_omits_role_when_empty():
    factory = _make_factory([("done", None)])
    backend = LocalAcpBackend(client_factory=factory)
    ctx = TurnContext(user_id="bob", user_name="Bob")

    async for _ in backend.stream("q", ctx):
        pass

    env = factory.captured["env"]
    assert "AGENT_REQUESTER_ROLE" not in env


async def test_local_acp_forces_pythonunbuffered_so_logs_arrive_live():
    factory = _make_factory([("done", None)])
    backend = LocalAcpBackend(client_factory=factory)
    ctx = TurnContext(user_id="x", user_name="X")

    async for _ in backend.stream("q", ctx):
        pass

    assert factory.captured["env"]["PYTHONUNBUFFERED"] == "1"


async def test_local_acp_uses_configured_cwd_for_new_session():
    factory = _make_factory([("done", None)])
    backend = LocalAcpBackend(cwd="/custom/path", client_factory=factory)
    ctx = TurnContext(user_id="x", user_name="X")

    async for _ in backend.stream("q", ctx):
        pass

    assert factory.captured["client"].session_cwd == "/custom/path"


# AC-W1-L3: Local image attachments are inlined as ACP content blocks.

# 1x1 transparent PNG — minimal valid file for testing.
_PNG_BYTES = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d49444154789c6300010000000500010d0a2db40000000049454e44ae426082"
)


async def test_local_acp_inlines_image_attachment_as_base64_content_block(tmp_path: Path):
    img = tmp_path / "tiny.png"
    img.write_bytes(_PNG_BYTES)

    factory = _make_factory([("done", None)])
    backend = LocalAcpBackend(client_factory=factory)
    ctx = TurnContext(user_id="x", user_name="X")

    async for _ in backend.stream("describe this", ctx, image_paths=[str(img)]):
        pass

    session_id, blocks = factory.captured["client"].prompts_received[0]
    assert session_id == "fake-session-id"
    assert blocks[0] == {"type": "text", "text": "describe this"}
    assert blocks[1] == {
        "type": "image",
        "data": base64.b64encode(_PNG_BYTES).decode("ascii"),
        "mimeType": "image/png",
    }


async def test_local_acp_supports_multiple_image_attachments(tmp_path: Path):
    img1 = tmp_path / "a.png"
    img2 = tmp_path / "b.png"
    img1.write_bytes(_PNG_BYTES)
    img2.write_bytes(_PNG_BYTES)

    factory = _make_factory([("done", None)])
    backend = LocalAcpBackend(client_factory=factory)
    ctx = TurnContext(user_id="x", user_name="X")

    async for _ in backend.stream("compare", ctx, image_paths=[str(img1), str(img2)]):
        pass

    blocks = factory.captured["client"].prompts_received[0][1]
    image_blocks = [b for b in blocks if b.get("type") == "image"]
    assert len(image_blocks) == 2


async def test_local_acp_omits_image_block_when_no_attachments():
    factory = _make_factory([("done", None)])
    backend = LocalAcpBackend(client_factory=factory)
    ctx = TurnContext(user_id="x", user_name="X")

    async for _ in backend.stream("just text", ctx):
        pass

    blocks = factory.captured["client"].prompts_received[0][1]
    assert blocks == [{"type": "text", "text": "just text"}]
