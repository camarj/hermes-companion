"""AC-W1-U1: /api/agents CRUD round-trips."""


def test_get_agents_returns_seeded(client):
    resp = client.get("/api/agents")

    assert resp.status_code == 200
    body = resp.json()
    assert "agents" in body
    ids = [a["id"] for a in body["agents"]]
    assert "default" in ids


def test_post_agent_creates_new_instance(client):
    resp = client.post("/api/agents", json={
        "id": "vps-prod",
        "label": "Hermes VPS prod",
        "transport": "remote-acp",
        "transport_config": {
            "url": "wss://vps.example.com/api/host/acp",
            "token": "env:HERMES_VPS_TOKEN",
        },
    })

    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["id"] == "vps-prod"
    assert body["transport"] == "remote-acp"
    assert body["created_via"] == "user"

    listed = client.get("/api/agents").json()["agents"]
    assert any(a["id"] == "vps-prod" for a in listed)


def test_post_agent_rejects_duplicate_id(client):
    client.post("/api/agents", json={
        "id": "dup", "label": "Dup", "transport": "local-acp",
    })

    resp = client.post("/api/agents", json={
        "id": "dup", "label": "Dup2", "transport": "local-acp",
    })

    assert resp.status_code == 409


def test_post_agent_validates_required_fields(client):
    resp = client.post("/api/agents", json={"label": "no id"})

    assert resp.status_code == 422  # FastAPI validation error


def test_put_agent_updates_label_and_system_prompt(client):
    resp = client.put("/api/agents/default", json={
        "label": "Renamed",
        "system_prompt_override": "You are very curt.",
    })

    assert resp.status_code == 200
    body = resp.json()
    assert body["label"] == "Renamed"
    assert body["system_prompt_override"] == "You are very curt."


def test_put_agent_404_when_missing(client):
    resp = client.put("/api/agents/ghost", json={"label": "X"})

    assert resp.status_code == 404


def test_delete_agent_removes_when_no_conversations(client):
    client.post("/api/agents", json={
        "id": "tmp", "label": "Temp", "transport": "local-acp",
    })

    resp = client.delete("/api/agents/tmp")

    assert resp.status_code == 204
    listed = client.get("/api/agents").json()["agents"]
    assert all(a["id"] != "tmp" for a in listed)


def test_delete_agent_refuses_when_conversation_references_it(client):
    # default agent has a conversation pointing at it.
    client.post("/api/conversations", json={"agent_id": "default"})

    resp = client.delete("/api/agents/default")

    assert resp.status_code == 409
    assert "conversation" in resp.json()["detail"].lower()


def test_agents_endpoints_require_authentication(client):
    client.cookies.clear()
    assert client.get("/api/agents").status_code == 401
    assert client.post("/api/agents", json={"id": "x", "label": "X"}).status_code == 401
    assert client.put("/api/agents/x", json={"label": "X"}).status_code == 401
    assert client.delete("/api/agents/x").status_code == 401
