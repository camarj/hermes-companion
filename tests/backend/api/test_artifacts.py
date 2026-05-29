"""AC-W3-A1 scenarios 5-8: artifact download + listing endpoints.

Also covers WU-D: message attribution (attach_artifacts_to_message called in
the chat SSE handler after add_message, and data-artifacts frame emitted).
"""

import json
import pytest


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def conv_id(client):
    """Create a conversation owned by u1 and return its id."""
    resp = client.post("/api/conversations")
    assert resp.status_code == 200
    return resp.json()["id"]


@pytest.fixture
def artifact_id(client, conv_id, seeded_db):
    """Seed one inline artifact in the u1 conversation and return its id."""
    import database
    art = database.create_artifact(
        name="report.md",
        rel_path="report.md",
        content_bytes=b"# hello world",
        conversation_id=conv_id,
    )
    return art["id"]


@pytest.fixture
def large_artifact_id(client, conv_id, seeded_db, tmp_path, monkeypatch):
    """Seed a large (file-path) artifact and return its id."""
    import database

    monkeypatch.setenv("COMPANION_DATA_DIR", str(tmp_path / "data"))

    big_content = b"x" * (database.ARTIFACT_INLINE_MAX_BYTES + 1)
    art = database.create_artifact(
        name="bigfile.bin",
        rel_path="bigfile.bin",
        content_bytes=big_content,
        conversation_id=conv_id,
    )
    return art["id"]


# ── Scenario 5: Download inline bytes ────────────────────────────────────────

def test_download_inline_artifact_returns_bytes(client, artifact_id):
    """Scenario 5: GET /api/artifacts/{id}/download returns correct bytes inline."""
    resp = client.get(f"/api/artifacts/{artifact_id}/download")

    assert resp.status_code == 200
    assert resp.content == b"# hello world"
    assert "attachment" in resp.headers["content-disposition"]
    assert "report.md" in resp.headers["content-disposition"]


def test_download_inline_artifact_content_type(client, artifact_id):
    """Scenario 5b: Content-Type matches stored mime_type."""
    resp = client.get(f"/api/artifacts/{artifact_id}/download")

    assert resp.status_code == 200
    assert "text/" in resp.headers["content-type"]


# ── Scenario 6: Download file-path bytes ────────────────────────────────────

def test_download_file_path_artifact_returns_bytes(client, large_artifact_id):
    """Scenario 6: GET /api/artifacts/{id}/download returns file-path bytes."""
    import database
    art = database.get_artifact(large_artifact_id)
    assert art is not None
    assert art["file_path"] is not None

    resp = client.get(f"/api/artifacts/{large_artifact_id}/download")

    assert resp.status_code == 200
    assert len(resp.content) == database.ARTIFACT_INLINE_MAX_BYTES + 1
    assert "attachment" in resp.headers["content-disposition"]
    assert "bigfile.bin" in resp.headers["content-disposition"]


# ── Scenario 7: Reject unauthenticated caller ────────────────────────────────

def test_download_artifact_requires_auth(client, artifact_id, seeded_db):
    """Scenario 7: No session cookie → 401."""
    from fastapi.testclient import TestClient
    import main

    no_auth_client = TestClient(main.app)
    resp = no_auth_client.get(f"/api/artifacts/{artifact_id}/download")

    assert resp.status_code == 401


# ── Scenario 8: Reject wrong-user access ────────────────────────────────────

def test_download_artifact_wrong_user_returns_404(client, conv_id, seeded_db, monkeypatch):
    """Scenario 8: Authenticated user B cannot download user A's artifact."""
    import database
    import main

    # Seed user B alongside u1
    monkeypatch.setattr(database, "configured_team", lambda: [
        {"id": "u1", "name": "User One", "role": "tester", "shared_space": False},
        {"id": "u2", "name": "User Two", "role": "tester", "shared_space": False},
    ])
    database.init_db()

    art = database.create_artifact(
        name="secret.txt",
        rel_path="secret.txt",
        content_bytes=b"sensitive data",
        conversation_id=conv_id,
    )

    from fastapi.testclient import TestClient
    client_b = TestClient(main.app)
    client_b.cookies.set("companion_user", "u2")
    resp = client_b.get(f"/api/artifacts/{art['id']}/download")

    assert resp.status_code == 404


# ── List conversation artifacts endpoint ─────────────────────────────────────

def test_list_conversation_artifacts_returns_metadata(client, conv_id, seeded_db):
    """GET /api/conversations/{conv_id}/artifacts returns artifact metadata (no bytes)."""
    import database

    database.create_artifact(
        name="file1.txt",
        rel_path="file1.txt",
        content_bytes=b"content one",
        conversation_id=conv_id,
    )
    database.create_artifact(
        name="file2.txt",
        rel_path="file2.txt",
        content_bytes=b"content two",
        conversation_id=conv_id,
    )

    resp = client.get(f"/api/conversations/{conv_id}/artifacts")

    assert resp.status_code == 200
    body = resp.json()
    assert "artifacts" in body
    assert len(body["artifacts"]) == 2
    names = {a["name"] for a in body["artifacts"]}
    assert names == {"file1.txt", "file2.txt"}
    # No content or file_path leaked
    for art in body["artifacts"]:
        assert "content" not in art
        assert "file_path" not in art


def test_list_conversation_artifacts_requires_auth(client, conv_id, seeded_db):
    """GET /api/conversations/{conv_id}/artifacts requires authentication."""
    from fastapi.testclient import TestClient
    import main

    no_auth_client = TestClient(main.app)
    resp = no_auth_client.get(f"/api/conversations/{conv_id}/artifacts")
    assert resp.status_code == 401


def test_list_conversation_artifacts_wrong_user_returns_403_or_404(
    client, conv_id, seeded_db, monkeypatch
):
    """User B cannot list user A's conversation artifacts."""
    import database
    import main

    monkeypatch.setattr(database, "configured_team", lambda: [
        {"id": "u1", "name": "User One", "role": "tester", "shared_space": False},
        {"id": "u2", "name": "User Two", "role": "tester", "shared_space": False},
    ])
    database.init_db()

    from fastapi.testclient import TestClient
    client_b = TestClient(main.app)
    client_b.cookies.set("companion_user", "u2")
    resp = client_b.get(f"/api/conversations/{conv_id}/artifacts")
    assert resp.status_code in (403, 404)


# ── WU-D: data-artifacts SSE frame + attach_artifacts_to_message ─────────────

def test_chat_stream_emits_data_artifacts_frame_and_attaches_to_message(
    client, conv_id, seeded_db, monkeypatch
):
    """WU-D: SSE stream buffers artifact events, then after add_message emits
    data-artifacts frame and calls attach_artifacts_to_message so the DB row
    has message_id set."""
    import database
    import main

    # Insert an artifact row with a known id so attach_artifacts_to_message can find it
    art = database.create_artifact(
        name="result.md",
        rel_path="result.md",
        content_bytes=b"hello",
        conversation_id=conv_id,
    )
    art_id = art["id"]

    artifact_record = {
        "id": art_id,
        "name": "result.md",
        "conversation_id": conv_id,
        "message_id": None,
        "mime_type": "text/markdown",
        "size_bytes": 5,
        "rel_path": "result.md",
        "created_at": "2026-01-01T00:00:00+00:00",
    }

    async def fake_stream(*args, **kwargs):
        yield ("text", "the answer")
        yield ("artifact", artifact_record)

    # Patch on main module since main.py imported call_agent_stream directly
    monkeypatch.setattr(main, "call_agent_stream", fake_stream)

    with client.stream("POST", "/api/chat/stream", json={
        "messages": [{"role": "user", "parts": [{"type": "text", "text": "hi"}]}],
        "conversation_id": conv_id,
    }) as r:
        assert r.status_code == 200
        raw = r.read().decode()

    frames = [
        json.loads(line[len("data: "):])
        for line in raw.splitlines()
        if line.startswith("data: ") and not line.startswith("data: [DONE]")
    ]
    frame_types = [f["type"] for f in frames]
    assert "data-artifacts" in frame_types, f"Expected data-artifacts in {frame_types}"

    artifacts_frame = next(f for f in frames if f["type"] == "data-artifacts")
    assert "messageId" in artifacts_frame
    assert "artifacts" in artifacts_frame
    assert any(a["id"] == art_id for a in artifacts_frame["artifacts"])

    # Verify the DB row now has message_id set (attach happened)
    db_art = database.get_artifact(art_id)
    assert db_art is not None
    assert db_art["message_id"] == artifacts_frame["messageId"]


def test_chat_stream_no_data_artifacts_frame_when_no_artifacts(
    client, conv_id, seeded_db, monkeypatch
):
    """WU-D: When the stream yields no artifact events, no data-artifacts frame is emitted."""
    import main

    async def fake_stream(*args, **kwargs):
        yield ("text", "the answer")

    monkeypatch.setattr(main, "call_agent_stream", fake_stream)

    with client.stream("POST", "/api/chat/stream", json={
        "messages": [{"role": "user", "parts": [{"type": "text", "text": "hello"}]}],
        "conversation_id": conv_id,
    }) as r:
        assert r.status_code == 200
        raw = r.read().decode()

    frames = [
        json.loads(line[len("data: "):])
        for line in raw.splitlines()
        if line.startswith("data: ") and not line.startswith("data: [DONE]")
    ]
    frame_types = [f["type"] for f in frames]
    assert "data-artifacts" not in frame_types
