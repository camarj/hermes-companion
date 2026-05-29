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
    def __init__(
        self,
        events: list,
        *,
        new_session_id: str = "fake-session-id",
    ) -> None:
        self._events = events
        self._new_session_id = new_session_id
        self.prompts_received: list[tuple[str, list[dict]]] = []
        self.session_cwd: str | None = None
        self.loaded_session_id: str | None = None

    async def initialize(self) -> dict:
        return {"agentInfo": {"name": "hermes-agent", "version": "fake"}}

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

    # cwd event is emitted first (AC-W3-A1), then session (AC-W1-D4), then payload.
    assert events == [
        ("cwd", "/tmp"),
        ("session", "fake-session-id"),
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


# AC-W1-D4: session id emission + resume.

async def test_local_acp_emits_session_event_at_start_of_stream():
    factory = _make_factory([
        ("reasoning", "thinking"),
        ("text", "hi"),
        ("done", None),
    ])
    backend = LocalAcpBackend(client_factory=factory)
    ctx = TurnContext(user_id="x", user_name="X")

    events = [ev async for ev in backend.stream("q", ctx)]

    # cwd event first (AC-W3-A1), then session id (AC-W1-D4), then payload.
    assert events[0] == ("cwd", "/tmp")
    assert events[1] == ("session", "fake-session-id")
    assert events[2:] == [
        ("reasoning", "thinking"),
        ("text", "hi"),
        ("done", None),
    ]


async def test_local_acp_calls_new_session_when_no_prior_id():
    factory = _make_factory([("done", None)])
    backend = LocalAcpBackend(client_factory=factory)
    ctx = TurnContext(user_id="x", user_name="X")

    async for _ in backend.stream("q", ctx):
        pass

    assert factory.captured["client"].loaded_session_id is None
    assert factory.captured["client"].session_cwd == "/tmp"


async def test_local_acp_calls_load_session_when_context_has_session_id():
    factory = _make_factory([("done", None)])
    backend = LocalAcpBackend(client_factory=factory)
    ctx = TurnContext(user_id="x", user_name="X", session_id="prior-xyz")

    events = []
    async for ev in backend.stream("q", ctx):
        events.append(ev)

    fake = factory.captured["client"]
    assert fake.loaded_session_id == "prior-xyz"
    # cwd event first, then session event echoes the resumed id.
    assert events[0][0] == "cwd"
    assert events[1] == ("session", "prior-xyz")


# AC-W1-U5: LocalAcpBackend honors system_prompt_override.

async def test_local_acp_materializes_agents_md_when_system_prompt_set():
    """With a system_prompt_override, the cwd passed to session/new must
    contain an AGENTS.md file with that content (Hermes' prompt builder
    picks it up natively)."""
    factory = _make_factory([("done", None)])
    prompt = "You are terse. Reply in one sentence."
    backend = LocalAcpBackend(
        client_factory=factory,
        system_prompt_override=prompt,
    )
    ctx = TurnContext(user_id="x", user_name="X")

    async for _ in backend.stream("q", ctx):
        pass

    cwd = factory.captured["client"].session_cwd
    assert cwd is not None
    assert cwd != "/tmp"

    agents_md = Path(cwd) / "AGENTS.md"
    assert agents_md.is_file()
    assert agents_md.read_text(encoding="utf-8") == prompt


async def test_local_acp_uses_configured_cwd_when_no_system_prompt():
    """Without an override, cwd stays as whatever was configured."""
    factory = _make_factory([("done", None)])
    backend = LocalAcpBackend(cwd="/custom", client_factory=factory)
    ctx = TurnContext(user_id="x", user_name="X")

    async for _ in backend.stream("q", ctx):
        pass

    assert factory.captured["client"].session_cwd == "/custom"


async def test_local_acp_empty_override_does_not_materialize_dir():
    """Empty string / whitespace shouldn't create a tmpdir."""
    factory = _make_factory([("done", None)])
    backend = LocalAcpBackend(
        client_factory=factory,
        system_prompt_override="   ",
    )
    ctx = TurnContext(user_id="x", user_name="X")

    async for _ in backend.stream("q", ctx):
        pass

    assert factory.captured["client"].session_cwd == "/tmp"


# ── AC-W3-A1: cwd emission ────────────────────────────────────────────────

async def test_local_acp_emits_cwd_before_session_event():
    """LocalAcpBackend must yield ("cwd", str) as the first event, before ("session", ...)."""
    factory = _make_factory([("text", "ok"), ("done", None)])
    backend = LocalAcpBackend(cwd="/custom/cwd", client_factory=factory)
    ctx = TurnContext(user_id="x", user_name="X")

    events = [ev async for ev in backend.stream("q", ctx)]

    assert events[0][0] == "cwd", f"first event must be 'cwd', got {events[0][0]!r}"
    assert isinstance(events[0][1], str)
    assert events[1][0] == "session", f"second event must be 'session', got {events[1][0]!r}"


async def test_local_acp_emits_cwd_value_matches_resolved_cwd():
    """The cwd payload must equal the resolved session cwd, not a hardcoded value."""
    factory = _make_factory([("done", None)])
    backend = LocalAcpBackend(cwd="/expected/path", client_factory=factory)
    ctx = TurnContext(user_id="x", user_name="X")

    events = [ev async for ev in backend.stream("q", ctx)]

    cwd_events = [ev for ev in events if ev[0] == "cwd"]
    assert len(cwd_events) == 1
    assert cwd_events[0][1] == "/expected/path"
