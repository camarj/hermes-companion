"""AC-W1-R2: /api/host/acp WS requires valid bearer; bridges JSON-RPC.

Bridge correctness is exercised against a fake `hermes acp` subprocess
factory injected via `host_mode._spawn_acp` monkeypatch. The real
subprocess path is verified in the PR's end-to-end smoke (PR description).
"""

import json
import pytest

from starlette.websockets import WebSocketDisconnect

import host_mode


def test_ws_rejects_connection_without_authorization(host_client):
    with pytest.raises(WebSocketDisconnect) as excinfo:
        with host_client.websocket_connect("/api/host/acp"):
            pass
    assert excinfo.value.code == 4401


def test_ws_rejects_invalid_bearer(host_client):
    with pytest.raises(WebSocketDisconnect) as excinfo:
        with host_client.websocket_connect(
            "/api/host/acp",
            headers={"Authorization": "Bearer wrong"},
        ):
            pass
    assert excinfo.value.code == 4401


def test_ws_accepts_valid_bearer_and_proxies_jsonrpc(host_client, fake_acp):
    """A frame the client sends reaches stdin; a frame stdout emits reaches the client."""
    with host_client.websocket_connect(
        "/api/host/acp",
        headers={"Authorization": "Bearer secret-T1"},
    ) as ws:
        # Client → bridge → subprocess stdin.
        client_frame = {
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": 1, "clientCapabilities": {}},
        }
        ws.send_text(json.dumps(client_frame))

        # Subprocess responds.
        fake_acp.push_response({
            "jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": 1},
        })
        reply = ws.receive_text()

    assert json.loads(reply) == {
        "jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": 1},
    }
    # And stdin actually saw the initialize.
    sent = fake_acp.stdin_lines()
    assert sent[0]["method"] == "initialize"


def test_ws_passes_identity_headers_to_subprocess_env(host_client, monkeypatch, fake_acp):
    """The remote client supplies AGENT_REQUESTER_* via X-Requester-* headers."""
    captured_env: dict = {}

    async def _spawn(env):
        captured_env.update(env)
        return fake_acp

    monkeypatch.setattr(host_mode, "_spawn_acp", _spawn)

    with host_client.websocket_connect(
        "/api/host/acp",
        headers={
            "Authorization": "Bearer secret-T1",
            "X-Requester-Id": "alice",
            "X-Requester-Name": "Alice",
            "X-Requester-Role": "CEO",
        },
    ) as ws:
        ws.send_text(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"}))
        fake_acp.push_response({"jsonrpc": "2.0", "id": 1, "result": {}})
        ws.receive_text()

    assert captured_env["AGENT_REQUESTER_ID"] == "alice"
    assert captured_env["AGENT_REQUESTER_NAME"] == "Alice"
    assert captured_env["AGENT_REQUESTER_ROLE"] == "CEO"
    assert captured_env["PYTHONUNBUFFERED"] == "1"
