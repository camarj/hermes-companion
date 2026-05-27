"""AC-W1-D3 (HTTP layer): POST /api/conversations honours agent_id."""


def test_post_conversation_uses_default_agent_when_body_omitted(client):
    resp = client.post("/api/conversations")

    assert resp.status_code == 200
    body = resp.json()
    assert body["agent_id"] == "default"


def test_post_conversation_accepts_explicit_agent_id(client):
    resp = client.post("/api/conversations", json={"agent_id": "default"})

    assert resp.status_code == 200
    assert resp.json()["agent_id"] == "default"


def test_post_conversation_rejects_unknown_agent_id(client):
    resp = client.post("/api/conversations", json={"agent_id": "ghost"})

    assert resp.status_code == 400
    assert "agent_id" in resp.json()["detail"].lower()


def test_post_conversation_requires_authentication(client):
    client.cookies.clear()

    resp = client.post("/api/conversations")

    assert resp.status_code == 401
