"""Fixtures shared by tests under `tests/backend/api/`."""

import asyncio
import json

import pytest


class _FakeProcess:
    """Stand-in for an asyncio subprocess that round-trips JSON lines."""

    def __init__(self) -> None:
        self.stdin_buf = bytearray()
        self._stdout_queue: asyncio.Queue[bytes | None] = asyncio.Queue()

        class _Stdin:
            def __init__(self, parent: "_FakeProcess") -> None:
                self._parent = parent

            def write(self, data: bytes) -> None:
                self._parent.stdin_buf.extend(data)

            async def drain(self) -> None:
                return None

            def close(self) -> None:
                pass

        class _Stdout:
            def __init__(self, parent: "_FakeProcess") -> None:
                self._parent = parent

            async def readline(self) -> bytes:
                line = await self._parent._stdout_queue.get()
                return line or b""

        self.stdin = _Stdin(self)
        self.stdout = _Stdout(self)
        self.returncode: int | None = None

    def kill(self) -> None:
        self.returncode = -9
        self._stdout_queue.put_nowait(None)

    async def wait(self) -> int:
        return self.returncode or 0

    def push_response(self, obj: dict) -> None:
        self._stdout_queue.put_nowait((json.dumps(obj) + "\n").encode())

    def stdin_lines(self) -> list[dict]:
        return [json.loads(l) for l in self.stdin_buf.decode().splitlines() if l.strip()]


@pytest.fixture
def fake_acp(monkeypatch):
    """Replace host_mode._spawn_acp with a sync factory returning _FakeProcess."""
    import host_mode

    proc = _FakeProcess()

    async def _spawn(env):
        return proc

    monkeypatch.setattr(host_mode, "_spawn_acp", _spawn)
    return proc


@pytest.fixture
def host_client(temp_db, monkeypatch, fake_acp):
    """TestClient with the WS bridge ready and one host token seeded."""
    from fastapi.testclient import TestClient

    import database
    import main

    monkeypatch.setattr(database, "configured_host_tokens", lambda: [
        {"token": "secret-T1", "label": "test"},
    ])
    database.init_db()
    return TestClient(main.app)
