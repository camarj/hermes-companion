"""AC-W2-A2: OpenClawBackend streams over ACP, reusing the acp_client.

OpenClaw speaks ACP over stdio (`openclaw acp`) just like Hermes, so the
backend mirrors LocalAcpBackend's flow with a different spawn command +
gateway auth. The stdio bridge emits text + tool_call but NOT reasoning
frames (PRD §5.3) — so the backend simply yields whatever the client
yields, and the absence of reasoning is the documented capability gap.

Backend behaviour is exercised against a fake AcpClient; the spawn argv +
gateway env are pinned by monkeypatching create_subprocess_exec.
"""

import base64
from contextlib import asynccontextmanager
from pathlib import Path

import acp_client
from agents.base import TurnContext
from agents.openclaw import OpenClawBackend


class _FakeAcpClient:
    def __init__(self, events: list, *, new_session_id: str = "oc-session") -> None:
        self._events = events
        self._new_session_id = new_session_id
        self.prompts_received: list[tuple[str, list[dict]]] = []
        self.session_cwd: str | None = None
        self.loaded_session_id: str | None = None

    async def initialize(self) -> dict:
        return {"agentInfo": {"name": "openclaw", "version": "fake"}}

    async def new_session(self, cwd: str = "/tmp") -> str:
        self.session_cwd = cwd
        return self._new_session_id

    async def load_session(self, session_id: str, cwd: str = "/tmp") -> str:
        self.loaded_session_id = session_id
        self.session_cwd = cwd
        return session_id

    async def prompt(self, session_id: str, content_blocks: list[dict]):
        self.prompts_received.append((session_id, content_blocks))
        for ev in self._events:
            yield ev


def _make_factory(events: list):
    captured: dict = {"env": None, "client": None}

    @asynccontextmanager
    async def factory(*, env: dict | None = None):
        captured["env"] = env
        client = _FakeAcpClient(events)
        captured["client"] = client
        yield client

    factory.captured = captured  # type: ignore[attr-defined]
    return factory


async def test_openclaw_round_trips_query_and_emits_session_first():
    factory = _make_factory([("text", "hi from openclaw"), ("done", None)])
    cwd = "/some/conv/workdir"
    backend = OpenClawBackend(cwd=cwd, client_factory=factory)
    ctx = TurnContext(user_id="alice", user_name="Alice")

    events = [ev async for ev in backend.stream("ping", ctx)]

    # cwd event first (AC-W3-A1), then session, then payload.
    assert events == [
        ("cwd", cwd),
        ("session", "oc-session"),
        ("text", "hi from openclaw"),
        ("done", None),
    ]
    assert factory.captured["client"].prompts_received == [
        ("oc-session", [{"type": "text", "text": "ping"}]),
    ]


async def test_openclaw_passes_through_tool_events_without_reasoning():
    """OpenClaw emits text + tool_call but no reasoning — the backend just
    forwards whatever the client yields; absence of reasoning is expected."""
    factory = _make_factory(
        [("tool", {"name": "search"}), ("text", "done searching"), ("done", None)]
    )
    backend = OpenClawBackend(client_factory=factory)
    ctx = TurnContext(user_id="x", user_name="X")

    kinds = [ev[0] async for ev in backend.stream("q", ctx)]
    assert "reasoning" not in kinds
    assert kinds == ["cwd", "session", "tool", "text", "done"]


async def test_openclaw_propagates_identity_env():
    factory = _make_factory([("done", None)])
    backend = OpenClawBackend(client_factory=factory)
    ctx = TurnContext(user_id="bob", user_name="Bob", user_role="Eng")

    async for _ in backend.stream("q", ctx):
        pass

    env = factory.captured["env"]
    assert env["AGENT_REQUESTER_ID"] == "bob"
    assert env["AGENT_REQUESTER_NAME"] == "Bob"
    assert env["AGENT_REQUESTER_ROLE"] == "Eng"
    assert env["PYTHONUNBUFFERED"] == "1"


async def test_openclaw_resumes_session_when_context_has_id():
    factory = _make_factory([("done", None)])
    backend = OpenClawBackend(client_factory=factory)
    ctx = TurnContext(user_id="x", user_name="X", session_id="prior-oc")

    events = [ev async for ev in backend.stream("q", ctx)]

    assert factory.captured["client"].loaded_session_id == "prior-oc"
    # cwd event first, then session
    assert events[0][0] == "cwd"
    assert events[1] == ("session", "prior-oc")


_PNG_BYTES = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d49444154789c6300010000000500010d0a2db40000000049454e44ae426082"
)


async def test_openclaw_inlines_image_as_base64_block(tmp_path: Path):
    img = tmp_path / "tiny.png"
    img.write_bytes(_PNG_BYTES)

    factory = _make_factory([("done", None)])
    backend = OpenClawBackend(client_factory=factory)
    ctx = TurnContext(user_id="x", user_name="X")

    async for _ in backend.stream("look", ctx, image_paths=[str(img)]):
        pass

    blocks = factory.captured["client"].prompts_received[0][1]
    assert blocks[1] == {
        "type": "image",
        "data": base64.b64encode(_PNG_BYTES).decode("ascii"),
        "mimeType": "image/png",
    }


async def test_spawn_openclaw_acp_builds_argv_and_gateway_env(monkeypatch):
    """The default spawn runs `openclaw acp` with gateway flags + token env."""
    captured: dict = {}

    class _FakeProc:
        def __init__(self):
            self.stdin = object()
            self.stdout = object()
            self.stderr = object()

        def kill(self):
            pass

        async def wait(self):
            return 0

    async def fake_exec(*args, env=None, **kwargs):
        captured["args"] = args
        captured["env"] = env
        return _FakeProc()

    monkeypatch.setattr(acp_client.asyncio, "create_subprocess_exec", fake_exec)

    async with acp_client.spawn_openclaw_acp(
        url="wss://host:18789", token="secret-tok"
    ):
        pass

    assert captured["args"][0] == "openclaw"
    assert captured["args"][1] == "acp"
    assert "--url" in captured["args"]
    assert "wss://host:18789" in captured["args"]
    assert "--token" in captured["args"]
    assert captured["env"]["OPENCLAW_GATEWAY_TOKEN"] == "secret-tok"


async def test_spawn_openclaw_acp_omits_flags_when_no_gateway(monkeypatch):
    captured: dict = {}

    class _FakeProc:
        def __init__(self):
            self.stdin = object()
            self.stdout = object()

        def kill(self):
            pass

        async def wait(self):
            return 0

    async def fake_exec(*args, env=None, **kwargs):
        captured["args"] = args
        return _FakeProc()

    monkeypatch.setattr(acp_client.asyncio, "create_subprocess_exec", fake_exec)

    async with acp_client.spawn_openclaw_acp():
        pass

    assert captured["args"] == ("openclaw", "acp")
