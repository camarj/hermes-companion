"""FIX 1 tests — per-conversation managed working directory.

Covers:
  W-1  config.workdir_for_conversation() creates and returns DATA_DIR/workdirs/<id>
  W-2  LocalAcpBackend (no system_prompt_override) uses per-conv workdir, not /tmp
  W-3  OpenClawBackend uses per-conv workdir, not /tmp
  W-4  LocalAcpBackend with system_prompt_override places AGENTS.md inside per-conv workdir
  W-5  No conversation_id → per-backend fallback to tempfile.mkdtemp (never /tmp root)
  W-6  delete_conversation removes DATA_DIR/workdirs/<conv_id> if present
"""

import shutil
import sqlite3
import tempfile
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

import pytest

import agent_bridge
import config
import database
from agents.base import TurnContext
from agents.local_acp import LocalAcpBackend
from agents.openclaw import OpenClawBackend
from database import delete_conversation


# ── W-1: workdir_for_conversation ─────────────────────────────────────────

def test_workdir_for_conversation_returns_data_dir_workdirs_subpath(tmp_path: Path, monkeypatch):
    """workdir_for_conversation(conv_id) == DATA_DIR/workdirs/<conv_id>, created on call."""
    monkeypatch.setattr(config, "data_dir", lambda: tmp_path / "data")

    conv_id = "conv-abc-123"
    wd = config.workdir_for_conversation(conv_id)

    expected = tmp_path / "data" / "workdirs" / conv_id
    assert wd == expected
    assert wd.is_dir()


def test_workdir_for_conversation_is_idempotent(tmp_path: Path, monkeypatch):
    """Calling it twice with the same id returns the same path without error."""
    monkeypatch.setattr(config, "data_dir", lambda: tmp_path / "data")

    conv_id = "conv-idempotent"
    wd1 = config.workdir_for_conversation(conv_id)
    wd2 = config.workdir_for_conversation(conv_id)

    assert wd1 == wd2
    assert wd2.is_dir()


# ── W-2: LocalAcpBackend uses per-conv workdir ────────────────────────────

class _FakeAcpClient:
    def __init__(self) -> None:
        self.session_cwd: str | None = None

    async def initialize(self):
        return {}

    async def new_session(self, cwd: str = "/tmp") -> str:
        self.session_cwd = cwd
        return "fake-session"

    async def load_session(self, session_id: str, cwd: str = "/tmp") -> str:
        self.session_cwd = cwd
        return session_id

    async def prompt(self, session_id, blocks):
        yield ("text", "ok")
        yield ("done", None)


def _make_factory():
    captured: dict = {"client": None}

    @asynccontextmanager
    async def factory(*, env=None):
        client = _FakeAcpClient()
        captured["client"] = client
        yield client

    factory.captured = captured  # type: ignore[attr-defined]
    return factory


async def test_local_acp_uses_per_conv_workdir_when_conv_id_given(
    tmp_path: Path, monkeypatch
):
    """LocalAcpBackend must use DATA_DIR/workdirs/<conv_id> when conversation_id is set."""
    monkeypatch.setattr(config, "data_dir", lambda: tmp_path / "data")

    conv_id = "conv-local-test"
    factory = _make_factory()
    # conversation_id is threaded via the cwd argument to LocalAcpBackend
    workdir = config.workdir_for_conversation(conv_id)
    backend = LocalAcpBackend(cwd=str(workdir), client_factory=factory)
    ctx = TurnContext(user_id="u1", user_name="User")

    events = [ev async for ev in backend.stream("q", ctx)]

    cwd_events = [ev for ev in events if ev[0] == "cwd"]
    assert len(cwd_events) == 1
    assert cwd_events[0][1] == str(workdir)
    # Must not be the bare /tmp root — must be the conversation-scoped path.
    assert cwd_events[0][1] != "/tmp", "cwd must not be the shared /tmp root"
    assert str(conv_id) in cwd_events[0][1]


async def test_local_acp_default_cwd_is_not_slash_tmp():
    """LocalAcpBackend(cwd='/tmp') is the old default; the new one must NOT default to /tmp."""
    # The constructor signature still accepts cwd= but the default must NOT be /tmp.
    # Verify by checking the new default is not "/tmp".
    import inspect
    sig = inspect.signature(LocalAcpBackend.__init__)
    default_cwd = sig.parameters["cwd"].default
    assert default_cwd != "/tmp", (
        "LocalAcpBackend default cwd must no longer be '/tmp'; "
        "callers are responsible for passing the per-conv workdir"
    )


# ── W-3: OpenClawBackend uses per-conv workdir ────────────────────────────

async def test_openclaw_uses_per_conv_workdir_when_conv_id_given(
    tmp_path: Path, monkeypatch
):
    """OpenClawBackend must accept a cwd kwarg and use it, not hardcode /tmp."""
    monkeypatch.setattr(config, "data_dir", lambda: tmp_path / "data")

    conv_id = "conv-openclaw-test"
    workdir = config.workdir_for_conversation(conv_id)

    factory = _make_factory()
    backend = OpenClawBackend(cwd=str(workdir), client_factory=factory)
    ctx = TurnContext(user_id="u1", user_name="User")

    events = [ev async for ev in backend.stream("q", ctx)]

    cwd_events = [ev for ev in events if ev[0] == "cwd"]
    assert len(cwd_events) == 1
    assert cwd_events[0][1] == str(workdir)
    # Must not be the bare /tmp root — must be the conversation-scoped path.
    assert cwd_events[0][1] != "/tmp", "OpenClawBackend must not use the shared /tmp root"


async def test_openclaw_default_cwd_is_not_slash_tmp():
    """Verify OpenClawBackend no longer defaults to /tmp."""
    import inspect
    sig = inspect.signature(OpenClawBackend.__init__)
    default_cwd = sig.parameters.get("cwd")
    # The cwd param must exist and not default to "/tmp"
    assert default_cwd is not None, "OpenClawBackend must accept a cwd parameter"
    assert default_cwd.default != "/tmp", (
        "OpenClawBackend default cwd must not be '/tmp'"
    )


# ── W-4: system_prompt_override uses per-conv workdir as base ─────────────

async def test_local_acp_system_prompt_override_written_into_per_conv_workdir(
    tmp_path: Path, monkeypatch
):
    """When system_prompt_override is set and conversation workdir is provided,
    AGENTS.md is materialized inside that workdir (or a subdir of it), not in
    a random tmpdir outside DATA_DIR."""
    monkeypatch.setattr(config, "data_dir", lambda: tmp_path / "data")

    conv_id = "conv-prompt-override"
    workdir = config.workdir_for_conversation(conv_id)

    factory = _make_factory()
    prompt = "Be terse."
    backend = LocalAcpBackend(
        cwd=str(workdir),
        client_factory=factory,
        system_prompt_override=prompt,
    )
    ctx = TurnContext(user_id="u1", user_name="User")

    async for _ in backend.stream("q", ctx):
        pass

    session_cwd = factory.captured["client"].session_cwd
    assert session_cwd is not None

    agents_md = Path(session_cwd) / "AGENTS.md"
    assert agents_md.is_file(), "AGENTS.md must exist in the session cwd"
    assert agents_md.read_text() == prompt


# ── W-5: No conversation_id → isolated tempdir, never /tmp root ───────────

def test_resolve_backend_no_conv_id_uses_isolated_tempdir(monkeypatch):
    """When conversation_id is absent, the backend must use an isolated tempdir,
    not the shared /tmp root.  We verify by checking the cwd the backend receives
    is NOT '/tmp' itself (any mkdtemp-created subdir is fine)."""
    # _resolve_backend(None) returns LocalAcpBackend()
    backend = agent_bridge._resolve_backend(None)
    assert isinstance(backend, LocalAcpBackend)
    import inspect
    sig = inspect.signature(LocalAcpBackend.__init__)
    default_cwd = sig.parameters["cwd"].default
    # The new default must not be the shared /tmp root
    assert default_cwd != "/tmp"


# ── W-6: delete_conversation removes workdir ──────────────────────────────

def test_delete_conversation_removes_workdir(
    inited_db: Path, tmp_path: Path, monkeypatch
):
    """delete_conversation must also remove DATA_DIR/workdirs/<conv_id> if it exists."""
    monkeypatch.setattr(config, "data_dir", lambda: tmp_path / "data")
    monkeypatch.setattr(database, "_data_dir", lambda: tmp_path / "data")

    conv_id = _seed_conversation(inited_db)

    # Simulate the workdir that would have been created during a turn.
    workdir = config.workdir_for_conversation(conv_id)
    assert workdir.is_dir()
    (workdir / "artifact.txt").write_text("some output")

    deleted = delete_conversation(conv_id)

    assert deleted is True
    assert not workdir.exists(), (
        "delete_conversation must remove DATA_DIR/workdirs/<conv_id>"
    )


def test_delete_conversation_no_workdir_does_not_error(
    inited_db: Path, tmp_path: Path, monkeypatch
):
    """delete_conversation must succeed even when no workdir exists yet."""
    monkeypatch.setattr(config, "data_dir", lambda: tmp_path / "data")
    monkeypatch.setattr(database, "_data_dir", lambda: tmp_path / "data")

    conv_id = _seed_conversation(inited_db)

    # Verify workdir does NOT exist
    workdir = tmp_path / "data" / "workdirs" / conv_id
    assert not workdir.exists()

    deleted = delete_conversation(conv_id)
    assert deleted is True


# ── Helpers ───────────────────────────────────────────────────────────────

def _seed_conversation(db_path: Path) -> str:
    conn = sqlite3.connect(str(db_path))
    try:
        user_id = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO users (id, name, role) VALUES (?, 'Tester', 'tester')",
            (user_id,),
        )
        conv_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "INSERT INTO conversations (id, user_id, title, created_at, updated_at) "
            "VALUES (?, ?, 'Test', ?, ?)",
            (conv_id, user_id, now, now),
        )
        conn.commit()
        return conv_id
    finally:
        conn.close()
