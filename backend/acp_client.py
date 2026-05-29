"""Minimal ACP (Agent Client Protocol) client for the Wave-1 spike.

ACP is a JSON-RPC protocol designed by Anthropic + Zed to standardize the
client ↔ agent contract for editors and other front-ends. Hermes exposes
it via `hermes acp` over stdio.

This module is the spike deliverable: a small client that speaks just
enough of the protocol to drive a single conversational turn end-to-end,
plus a high-level `stream_query` convenience that spawns `hermes acp` as
a subprocess and yields events shaped like the existing AgentEvent
contract (`("reasoning", str) | ("text", str) | ("done", None)`).

See `docs/acp-mapping.md` for the protocol details we discovered.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from contextlib import asynccontextmanager
from typing import AsyncIterator, Protocol


AgentEvent = tuple[str, object]  # ("reasoning"|"text"|"done", payload)


class _Writer(Protocol):
    def write(self, data: bytes) -> None: ...
    async def drain(self) -> None: ...


class AcpClient:
    """JSON-RPC client speaking ACP v1 over a pair of asyncio streams.

    The reader/writer are injected so unit tests can feed canned frames
    without spawning a real subprocess. For the real path, use
    `spawn_hermes_acp()` or `stream_query()`.
    """

    def __init__(self, reader: asyncio.StreamReader, writer: _Writer) -> None:
        self._reader = reader
        self._writer = writer
        self._next_id = 0

    def _new_id(self) -> int:
        self._next_id += 1
        return self._next_id

    async def _send(self, msg: dict) -> None:
        self._writer.write((json.dumps(msg) + "\n").encode("utf-8"))
        await self._writer.drain()

    async def _read_next(self) -> dict | None:
        line = await self._reader.readline()
        if not line:
            return None
        return json.loads(line.decode("utf-8"))

    async def _request(self, method: str, params: dict) -> dict:
        msg_id = self._new_id()
        await self._send({
            "jsonrpc": "2.0",
            "id": msg_id,
            "method": method,
            "params": params,
        })
        while True:
            msg = await self._read_next()
            if msg is None:
                raise EOFError(f"stream closed waiting for response to {method!r}")
            if msg.get("id") == msg_id and "result" in msg:
                return msg["result"]
            # Silently swallow notifications and unrelated responses arriving
            # before our reply. Real protocol traffic during initialize and
            # session/new should be minimal; if Hermes ever changes that the
            # spike will surface it as a test failure.

    async def initialize(self) -> dict:
        return await self._request(
            "initialize",
            {"protocolVersion": 1, "clientCapabilities": {}},
        )

    async def new_session(
        self,
        cwd: str = "/tmp",
        mcp_servers: list[dict] | None = None,
    ) -> str:
        result = await self._request(
            "session/new",
            {"cwd": cwd, "mcpServers": mcp_servers or []},
        )
        return result["sessionId"]

    async def load_session(
        self,
        session_id: str,
        cwd: str = "/tmp",
        mcp_servers: list[dict] | None = None,
    ) -> str:
        """Resume a previously-created session by id.

        Hermes replays the prior turn's notifications before sending the
        response — we skip them via `_request`, since the facade has
        already persisted the UI history. Returns the same `session_id`
        as a sanity check.
        """
        result = await self._request(
            "session/load",
            {
                "sessionId": session_id,
                "cwd": cwd,
                "mcpServers": mcp_servers or [],
            },
        )
        return result.get("sessionId", session_id)

    async def prompt(
        self,
        session_id: str,
        content_blocks: list[dict],
    ) -> AsyncIterator[AgentEvent]:
        """Send a turn and yield AgentEvent tuples until completion.

        `content_blocks` is the ACP prompt array verbatim. For text-only
        turns it's `[{"type":"text","text":"..."}]`. For multi-modal it
        includes additional `{"type":"image","data":...,"mimeType":...}`
        blocks. Callers (e.g. `LocalAcpBackend`) build the array; the
        client just forwards it.
        """
        msg_id = self._new_id()
        await self._send({
            "jsonrpc": "2.0",
            "id": msg_id,
            "method": "session/prompt",
            "params": {
                "sessionId": session_id,
                "prompt": content_blocks,
            },
        })
        while True:
            msg = await self._read_next()
            if msg is None:
                # Stream closed mid-turn — surface a terminator so callers
                # always see ("done", None) and can shut down cleanly.
                yield ("done", None)
                return
            if msg.get("method") == "session/update":
                mapped = _map_update(msg.get("params", {}).get("update", {}))
                if mapped is not None:
                    yield mapped
                continue
            if msg.get("id") == msg_id and "result" in msg:
                yield ("done", None)
                return


def _map_update(update: dict) -> AgentEvent | None:
    """Map a single ACP `session/update` payload to an AgentEvent.

    Returns None for noise (usage updates, command lists, anything we
    haven't classified yet). Hermes-specific event names we care about
    were discovered during the spike — see docs/acp-mapping.md.
    """
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


@asynccontextmanager
async def spawn_hermes_acp(
    *,
    env: dict[str, str] | None = None,
) -> AsyncIterator[AcpClient]:
    """Spawn `hermes acp` and yield a connected client. Cleans up on exit.

    `env` is merged with the parent process env so callers can supply the
    `AGENT_REQUESTER_*` identity vars (and `PYTHONUNBUFFERED=1`) without
    losing PATH, HOME, and other unrelated entries.
    """
    import os

    proc_env = os.environ.copy()
    if env:
        proc_env.update(env)
    # Non-TTY subprocess: auto-approve shell-hook prompts or hermes acp blocks
    # forever on the first one (legacy `hermes chat --yolo` did this implicitly).
    proc_env.setdefault("HERMES_ACCEPT_HOOKS", "1")
    proc = await asyncio.create_subprocess_exec(
        "hermes",
        "acp",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=proc_env,
    )
    try:
        assert proc.stdin is not None and proc.stdout is not None
        client = AcpClient(proc.stdout, proc.stdin)
        yield client
    finally:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        await proc.wait()


@asynccontextmanager
async def spawn_openclaw_acp(
    *,
    env: dict[str, str] | None = None,
    url: str | None = None,
    token: str | None = None,
) -> AsyncIterator[AcpClient]:
    """Spawn `openclaw acp` and yield a connected client. Cleans up on exit.

    OpenClaw speaks ACP over stdio just like Hermes (PRD §5.3). When `url`/
    `token` are given they target a remote Gateway (`openclaw acp --url …
    --token …`); otherwise the bridge talks to the local Gateway daemon.
    `token` is also exported as `OPENCLAW_GATEWAY_TOKEN` so file/env auth paths
    work too.

    Note (known gap, PRD §5.3): the stdio bridge has no headless approve-all
    flag — exec/mutating tools prompt and a non-TTY subprocess cannot answer
    them. Read/search tools auto-approve via OpenClaw's allowlist.
    """
    import os

    proc_env = os.environ.copy()
    if env:
        proc_env.update(env)
    if token:
        proc_env.setdefault("OPENCLAW_GATEWAY_TOKEN", token)
    args = ["openclaw", "acp"]
    if url:
        args += ["--url", url]
    if token:
        args += ["--token", token]
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=proc_env,
    )
    try:
        assert proc.stdin is not None and proc.stdout is not None
        client = AcpClient(proc.stdout, proc.stdin)
        yield client
    finally:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        await proc.wait()


async def stream_query(query: str, cwd: str = "/tmp") -> AsyncIterator[AgentEvent]:
    """High-level convenience: spawn hermes acp, run one turn, yield events."""
    async with spawn_hermes_acp() as client:
        await client.initialize()
        session_id = await client.new_session(cwd=cwd)
        async for event in client.prompt(session_id, [{"type": "text", "text": query}]):
            yield event


async def _main() -> int:
    parser = argparse.ArgumentParser(
        description="Stream a single query through hermes acp.",
    )
    parser.add_argument("query", help="The text to send to the agent.")
    parser.add_argument(
        "--cwd",
        default="/tmp",
        help="Working directory passed to session/new (default: /tmp).",
    )
    args = parser.parse_args()

    async for kind, payload in stream_query(args.query, cwd=args.cwd):
        if kind == "reasoning":
            print(f"\033[2m[thinking] {payload}\033[0m", end="", flush=True)
        elif kind == "text":
            print(payload, end="", flush=True)
        elif kind == "done":
            print()
            return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
