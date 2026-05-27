"""AC-W1-R1: `HERMES_COMPANION_MODE=host` exposes ONLY /api/host/*.

When the env var isn't set (default = client mode), every existing
endpoint stays alive. When set to "host", client routes return 404
while host routes (and /api/health for liveness probes) keep working.
"""

import pytest


# ── Default (client mode) ──────────────────────────────────────────────────

def test_default_mode_allows_client_routes(client, monkeypatch):
    monkeypatch.delenv("HERMES_COMPANION_MODE", raising=False)

    resp = client.get("/api/agents")

    assert resp.status_code == 200


def test_default_mode_allows_host_routes_too(host_client):
    """Client mode doesn't disable the bridge — useful for single-box demos."""
    # The fixture seeds a token; just verify the endpoint mounted.
    # Auth failure 4401 confirms the route is reachable.
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect) as excinfo:
        with host_client.websocket_connect("/api/host/acp"):
            pass
    assert excinfo.value.code == 4401


# ── Host mode ──────────────────────────────────────────────────────────────

def test_host_mode_blocks_client_get_routes(client, monkeypatch):
    monkeypatch.setenv("HERMES_COMPANION_MODE", "host")

    assert client.get("/api/agents").status_code == 404
    assert client.get("/api/conversations").status_code == 404
    assert client.get("/api/users").status_code == 404
    assert client.get("/api/me").status_code == 404


def test_host_mode_blocks_client_post_routes(client, monkeypatch):
    monkeypatch.setenv("HERMES_COMPANION_MODE", "host")

    assert client.post("/api/conversations").status_code == 404
    assert client.post("/api/agents", json={"id": "x", "label": "x"}).status_code == 404


def test_host_mode_keeps_health_alive(client, monkeypatch):
    monkeypatch.setenv("HERMES_COMPANION_MODE", "host")

    # /api/health stays so orchestrators (k8s, docker-compose) can probe it.
    assert client.get("/api/health").status_code == 200


def test_host_mode_keeps_host_routes_alive(host_client, monkeypatch):
    monkeypatch.setenv("HERMES_COMPANION_MODE", "host")
    from starlette.websockets import WebSocketDisconnect

    # With a valid bearer the bridge accepts; without one it 4401s — either
    # outcome proves the route still exists.
    with pytest.raises(WebSocketDisconnect) as excinfo:
        with host_client.websocket_connect("/api/host/acp"):
            pass
    assert excinfo.value.code == 4401
