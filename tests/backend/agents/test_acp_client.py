"""AC-W1-A4: ACP client speaks JSON-RPC over stdio and maps events.

The client takes asyncio stream-like objects so tests can feed canned
JSON-RPC frames without spawning `hermes acp` for every assertion. A
separate manual / integration test (run via `python -m backend.acp_client`)
exercises the real subprocess path.
"""

import asyncio
import json

import pytest

from acp_client import AcpClient


class _FakeWriter:
    """Stand-in for an asyncio StreamWriter that records bytes written."""

    def __init__(self) -> None:
        self.buffer = bytearray()
        self.closed = False

    def write(self, data: bytes) -> None:
        self.buffer.extend(data)

    async def drain(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True


def _make_reader(messages: list[dict]) -> asyncio.StreamReader:
    reader = asyncio.StreamReader()
    for msg in messages:
        reader.feed_data((json.dumps(msg) + "\n").encode())
    reader.feed_eof()
    return reader


def _sent_messages(writer: _FakeWriter) -> list[dict]:
    lines = writer.buffer.decode().splitlines()
    return [json.loads(line) for line in lines if line.strip()]


async def test_initialize_sends_protocol_v1_and_returns_agent_info():
    reader = _make_reader([
        {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "protocolVersion": 1,
                "agentInfo": {"name": "hermes-agent", "version": "0.14.0"},
                "agentCapabilities": {"loadSession": True},
            },
        },
    ])
    writer = _FakeWriter()
    client = AcpClient(reader, writer)

    result = await client.initialize()

    assert result["agentInfo"]["name"] == "hermes-agent"
    sent = _sent_messages(writer)
    assert sent[0]["method"] == "initialize"
    assert sent[0]["params"]["protocolVersion"] == 1


async def test_new_session_returns_session_id():
    reader = _make_reader([
        {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"sessionId": "abc-123", "models": {"availableModels": []}},
        },
    ])
    writer = _FakeWriter()
    client = AcpClient(reader, writer)

    session_id = await client.new_session(cwd="/tmp")

    assert session_id == "abc-123"
    sent = _sent_messages(writer)
    assert sent[0]["method"] == "session/new"
    assert sent[0]["params"]["cwd"] == "/tmp"


async def test_prompt_yields_reasoning_text_done_in_order():
    reader = _make_reader([
        {
            "jsonrpc": "2.0",
            "method": "session/update",
            "params": {
                "sessionId": "s",
                "update": {
                    "sessionUpdate": "agent_thought_chunk",
                    "content": {"text": "thinking", "type": "text"},
                },
            },
        },
        {
            "jsonrpc": "2.0",
            "method": "session/update",
            "params": {
                "sessionId": "s",
                "update": {
                    "sessionUpdate": "agent_message_chunk",
                    "content": {"text": "hello", "type": "text"},
                },
            },
        },
        {"jsonrpc": "2.0", "id": 1, "result": {"stopReason": "end_turn"}},
    ])
    writer = _FakeWriter()
    client = AcpClient(reader, writer)

    events = [ev async for ev in client.prompt("s", [{"type": "text", "text": "ping"}])]

    assert events == [
        ("reasoning", "thinking"),
        ("text", "hello"),
        ("done", None),
    ]
    sent = _sent_messages(writer)
    assert sent[0]["method"] == "session/prompt"
    assert sent[0]["params"]["sessionId"] == "s"
    assert sent[0]["params"]["prompt"] == [{"type": "text", "text": "ping"}]


async def test_load_session_resumes_an_existing_session():
    """ACP session/load takes the prior sessionId and rehydrates it.

    The response shape matches session/new (models + sessionId), with
    the same id echoed back. Tests just confirm we send the right
    method and parse the result.
    """
    reader = _make_reader([
        {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "sessionId": "prior-abc",
                "models": {"availableModels": []},
            },
        },
    ])
    writer = _FakeWriter()
    client = AcpClient(reader, writer)

    session_id = await client.load_session("prior-abc", cwd="/tmp")

    assert session_id == "prior-abc"
    sent = _sent_messages(writer)
    assert sent[0]["method"] == "session/load"
    assert sent[0]["params"]["sessionId"] == "prior-abc"
    assert sent[0]["params"]["cwd"] == "/tmp"


async def test_prompt_ignores_known_noise_updates():
    reader = _make_reader([
        {
            "jsonrpc": "2.0",
            "method": "session/update",
            "params": {
                "sessionId": "s",
                "update": {
                    "sessionUpdate": "available_commands_update",
                    "availableCommands": [],
                },
            },
        },
        {
            "jsonrpc": "2.0",
            "method": "session/update",
            "params": {
                "sessionId": "s",
                "update": {
                    "sessionUpdate": "usage_update",
                    "size": 100,
                    "used": 50,
                },
            },
        },
        {
            "jsonrpc": "2.0",
            "method": "session/update",
            "params": {
                "sessionId": "s",
                "update": {
                    "sessionUpdate": "agent_message_chunk",
                    "content": {"text": "hi", "type": "text"},
                },
            },
        },
        {"jsonrpc": "2.0", "id": 1, "result": {"stopReason": "end_turn"}},
    ])
    writer = _FakeWriter()
    client = AcpClient(reader, writer)

    events = [ev async for ev in client.prompt("s", [{"type": "text", "text": "ping"}])]

    assert events == [("text", "hi"), ("done", None)]
