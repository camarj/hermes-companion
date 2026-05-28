"""AC-W1-B1a: hermes acp is spawned with shell-hook auto-approval.

The legacy `hermes chat ... --yolo` auto-approved tool/hook prompts. The ACP
migration spawns `hermes acp` in a non-TTY subprocess; without auto-approval it
blocks forever on the first shell-hook permission prompt, hanging the turn. Both
the local and host spawn points must set HERMES_ACCEPT_HOOKS=1.
"""

import asyncio
from unittest.mock import MagicMock

import acp_client
import host_mode


class _FakeProc:
    def __init__(self):
        self.stdin = MagicMock()
        self.stdout = MagicMock()
        self.stderr = MagicMock()

    def kill(self):
        pass

    async def wait(self):
        return 0


def _capturing_exec(captured):
    async def fake_exec(*args, **kwargs):
        captured["args"] = args
        captured["env"] = kwargs.get("env")
        return _FakeProc()

    return fake_exec


def test_local_spawn_auto_accepts_hooks(monkeypatch):
    captured: dict = {}
    monkeypatch.setattr(
        acp_client.asyncio, "create_subprocess_exec", _capturing_exec(captured)
    )

    async def run():
        async with acp_client.spawn_hermes_acp():
            pass

    asyncio.run(run())
    assert captured["env"].get("HERMES_ACCEPT_HOOKS") == "1"


def test_host_spawn_auto_accepts_hooks(monkeypatch):
    captured: dict = {}
    monkeypatch.setattr(
        host_mode.asyncio, "create_subprocess_exec", _capturing_exec(captured)
    )

    asyncio.run(host_mode._spawn_acp({"AGENT_REQUESTER_ID": "raul"}))
    assert captured["env"].get("HERMES_ACCEPT_HOOKS") == "1"
