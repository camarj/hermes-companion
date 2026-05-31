"""AC-W3-T1 — /api/tasks REST endpoint tests.

Covers: Scenarios 1, 2, 3, 4, 5, 6, 8 (bus seam), 9 (bus seam), 10, 12, 14.

TDD note: all tests here were written BEFORE the handlers existed (RED first).
"""

import asyncio
import pytest


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def conv_id(client):
    """Create a conversation owned by u1 and return its id."""
    resp = client.post("/api/conversations")
    assert resp.status_code == 200
    return resp.json()["id"]


@pytest.fixture
def task_id(client, conv_id):
    """Seed one task for u1 and return its id."""
    resp = client.post("/api/tasks", json={"title": "Seed task", "conversation_id": conv_id})
    assert resp.status_code == 201
    return resp.json()["id"]


@pytest.fixture
def client_b(seeded_db, monkeypatch):
    """TestClient authenticated as a second user u2."""
    import database

    monkeypatch.setattr(database, "configured_team", lambda: [
        {"id": "u1", "name": "User One", "role": "tester", "shared_space": False},
        {"id": "u2", "name": "User Two", "role": "tester", "shared_space": False},
    ])
    database.init_db()

    from fastapi.testclient import TestClient
    import main

    c = TestClient(main.app)
    c.cookies.set("companion_user", "u2")
    return c


# ── Scenario 1: happy path ─────────────────────────────────────────────────────

def test_create_task_happy_path(client, conv_id):
    """Scenario 1: POST /api/tasks → 201 with pending status + UUID id."""
    resp = client.post("/api/tasks", json={"title": "Summarize Q3", "conversation_id": conv_id})

    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "pending"
    assert len(body["id"]) == 36  # uuid4
    assert body["title"] == "Summarize Q3"
    assert body["conversation_id"] == conv_id

    import database
    row = database.get_task(body["id"])
    assert row is not None
    assert row["user_id"] == "u1"


# ── Scenario 2: empty title ────────────────────────────────────────────────────

def test_create_task_empty_title_400(client):
    """Scenario 2: empty/missing title → 400, no row inserted."""
    resp = client.post("/api/tasks", json={"title": ""})
    assert resp.status_code == 400

    import database
    rows = database.list_tasks("u1")
    assert rows == []


def test_create_task_whitespace_title_400(client):
    """Whitespace-only title must also be rejected."""
    resp = client.post("/api/tasks", json={"title": "   "})
    assert resp.status_code == 400


# ── Scenario 3: unowned conversation ──────────────────────────────────────────

def test_create_task_unowned_conversation(client, client_b):
    """Scenario 3: u1 cannot create a task on u2's private conversation."""
    resp_b = client_b.post("/api/conversations")
    assert resp_b.status_code == 200
    b_conv_id = resp_b.json()["id"]

    resp = client.post("/api/tasks", json={"title": "Sneak", "conversation_id": b_conv_id})
    assert resp.status_code in (403, 404)


# ── Auth guard ─────────────────────────────────────────────────────────────────

def test_create_task_requires_auth(client):
    """POST without cookie → 401."""
    client.cookies.clear()
    resp = client.post("/api/tasks", json={"title": "X"})
    assert resp.status_code == 401


def test_list_tasks_requires_auth(client):
    """GET /api/tasks without cookie → 401."""
    client.cookies.clear()
    resp = client.get("/api/tasks")
    assert resp.status_code == 401


# ── Scenario 4: lifecycle transition persisted ────────────────────────────────

def test_patch_task_status_transition(client, task_id):
    """Scenario 4: PATCH status=running → 200, status updated, updated_at bumped."""
    resp = client.patch(f"/api/tasks/{task_id}", json={"status": "running"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "running"
    assert body["updated_at"] >= body["created_at"]


# ── Scenario 5: invalid status → 400 ─────────────────────────────────────────

def test_patch_task_invalid_status_400(client, task_id):
    """Scenario 5: PATCH with a non-enum status → 400, status unchanged."""
    resp = client.patch(f"/api/tasks/{task_id}", json={"status": "exploded"})
    assert resp.status_code == 400

    import database
    row = database.get_task(task_id)
    assert row["status"] == "pending"


# ── Illegal status transition → 409 (carry-over from T1-1a review) ───────────

def test_patch_task_illegal_transition_409(client, task_id):
    """Transitioning from a terminal status back to pending must return 409."""
    # Move to done (terminal)
    resp = client.patch(f"/api/tasks/{task_id}", json={"status": "running"})
    assert resp.status_code == 200
    resp = client.patch(f"/api/tasks/{task_id}", json={"status": "done"})
    assert resp.status_code == 200

    # Attempt illegal reverse transition
    resp = client.patch(f"/api/tasks/{task_id}", json={"status": "pending"})
    assert resp.status_code == 409

    import database
    row = database.get_task(task_id)
    assert row["status"] == "done"  # unchanged


def test_patch_task_running_to_pending_409(client, task_id):
    """running → pending is not a valid transition."""
    client.patch(f"/api/tasks/{task_id}", json={"status": "running"})
    resp = client.patch(f"/api/tasks/{task_id}", json={"status": "pending"})
    assert resp.status_code == 409


def test_patch_task_terminal_cancelled_no_outgoing(client, task_id):
    """cancelled is terminal; further transitions must return 409."""
    client.patch(f"/api/tasks/{task_id}", json={"status": "cancelled"})
    resp = client.patch(f"/api/tasks/{task_id}", json={"status": "running"})
    assert resp.status_code == 409


# ── Scenario 6: PATCH other user's task → 404 ────────────────────────────────

def test_patch_other_users_task_404(client, client_b, conv_id):
    """Scenario 6: user B PATCHes user A's task → 404 (avoids enumeration)."""
    resp = client.post("/api/tasks", json={"title": "A's task", "conversation_id": conv_id})
    assert resp.status_code == 201
    a_task_id = resp.json()["id"]

    resp_b = client_b.patch(f"/api/tasks/{a_task_id}", json={"status": "running"})
    assert resp_b.status_code == 404


# ── List tasks ─────────────────────────────────────────────────────────────────

def test_list_tasks_returns_user_tasks(client, conv_id):
    """Seeding two tasks then GET /api/tasks returns both for the owner."""
    client.post("/api/tasks", json={"title": "Task A", "conversation_id": conv_id})
    client.post("/api/tasks", json={"title": "Task B", "conversation_id": conv_id})

    resp = client.get("/api/tasks")
    assert resp.status_code == 200
    tasks = resp.json()["tasks"]
    assert len(tasks) == 2


def test_list_tasks_isolation_across_users(client, client_b, conv_id):
    """User B should NOT see user A's tasks in their own list."""
    client.post("/api/tasks", json={"title": "A private", "conversation_id": conv_id})

    resp_b = client_b.get("/api/tasks")
    assert resp_b.status_code == 200
    assert resp_b.json()["tasks"] == []


# ── Scenario 14: filter by conversation ───────────────────────────────────────

def test_list_tasks_filter_by_conversation(client):
    """Scenario 14: ?conversation_id= returns only that conversation's tasks."""
    conv1 = client.post("/api/conversations").json()["id"]
    conv2 = client.post("/api/conversations").json()["id"]
    client.post("/api/tasks", json={"title": "In C1", "conversation_id": conv1})
    client.post("/api/tasks", json={"title": "In C2", "conversation_id": conv2})

    resp = client.get(f"/api/tasks?conversation_id={conv1}")
    assert resp.status_code == 200
    tasks = resp.json()["tasks"]
    assert len(tasks) == 1
    assert tasks[0]["conversation_id"] == conv1


# ── Scenario 12: reconnect reconciles via REST ────────────────────────────────

def test_reconnect_reconciles_via_rest(client, task_id):
    """Scenario 12: task transitioned to done; GET /api/tasks reflects done status."""
    client.patch(f"/api/tasks/{task_id}", json={"status": "running"})
    client.patch(f"/api/tasks/{task_id}", json={"status": "done"})

    resp = client.get("/api/tasks")
    tasks = resp.json()["tasks"]
    assert any(t["id"] == task_id and t["status"] == "done" for t in tasks)


# ── Scenario 8 (bus seam): create emits companion.task.created ────────────────

@pytest.mark.asyncio
async def test_create_task_emits_event(seeded_db):
    """Scenario 8 (bus seam): creating a task publishes companion.task.created."""
    import events
    from fastapi.testclient import TestClient
    import main

    client = TestClient(main.app)
    client.cookies.set("companion_user", "u1")
    conv_resp = client.post("/api/conversations")
    conv_id = conv_resp.json()["id"]

    q = events.subscribe("u1")
    try:
        resp = client.post("/api/tasks", json={"title": "Bus test", "conversation_id": conv_id})
        assert resp.status_code == 201
        task_id = resp.json()["id"]

        frame = await asyncio.wait_for(q.get(), timeout=1.0)
        assert frame["event"] == "companion.task.created"
        assert frame["task_id"] == task_id
    finally:
        events.unsubscribe("u1", q)


# ── Scenario 9 (bus seam): patch emits companion.task.updated ─────────────────

@pytest.mark.asyncio
async def test_patch_task_emits_updated_event(seeded_db):
    """Scenario 9 (bus seam): PATCH status=done publishes companion.task.updated."""
    import events
    from fastapi.testclient import TestClient
    import main

    client = TestClient(main.app)
    client.cookies.set("companion_user", "u1")
    conv_resp = client.post("/api/conversations")
    conv_id = conv_resp.json()["id"]
    create_resp = client.post("/api/tasks", json={"title": "Will be done", "conversation_id": conv_id})
    tid = create_resp.json()["id"]

    # drain the create event
    q = events.subscribe("u1")
    try:
        # subscribe after create; first event will be from the patch
        client.patch(f"/api/tasks/{tid}", json={"status": "running"})
        frame = await asyncio.wait_for(q.get(), timeout=1.0)
        assert frame["event"] == "companion.task.updated"
        assert frame["payload"]["status"] == "running"
    finally:
        events.unsubscribe("u1", q)


# ── Rejected/no-op PATCH must not emit an event (review carry-over) ───────────

@pytest.mark.asyncio
async def test_illegal_transition_publishes_no_event(seeded_db):
    """A 409 illegal transition must not mutate nor publish an event."""
    import events
    from fastapi.testclient import TestClient
    import main

    client = TestClient(main.app)
    client.cookies.set("companion_user", "u1")
    tid = client.post("/api/tasks", json={"title": "Terminal"}).json()["id"]
    client.patch(f"/api/tasks/{tid}", json={"status": "cancelled"})  # pending → cancelled (legal)

    q = events.subscribe("u1")
    try:
        resp = client.patch(f"/api/tasks/{tid}", json={"status": "pending"})  # illegal
        assert resp.status_code == 409
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(q.get(), timeout=0.2)
    finally:
        events.unsubscribe("u1", q)


def test_same_status_patch_does_not_bump_updated_at(client, task_id):
    """A PATCH to the current status is a no-op: updated_at must not advance."""
    before = client.get("/api/tasks").json()["tasks"][0]["updated_at"]
    resp = client.patch(f"/api/tasks/{task_id}", json={"status": "pending"})
    assert resp.status_code == 200
    assert resp.json()["updated_at"] == before


# ── Scenario 10: event isolation across users ─────────────────────────────────

@pytest.mark.asyncio
async def test_event_isolation_across_users(seeded_db, monkeypatch):
    """Scenario 10: user A creates a task; user B's queue stays empty."""
    import database
    monkeypatch.setattr(database, "configured_team", lambda: [
        {"id": "u1", "name": "User One", "role": "tester", "shared_space": False},
        {"id": "u2", "name": "User Two", "role": "tester", "shared_space": False},
    ])
    database.init_db()

    import events
    from fastapi.testclient import TestClient
    import main

    client_a = TestClient(main.app)
    client_a.cookies.set("companion_user", "u1")
    conv_resp = client_a.post("/api/conversations")
    conv_id = conv_resp.json()["id"]

    q_b = events.subscribe("u2")
    try:
        client_a.post("/api/tasks", json={"title": "A private task", "conversation_id": conv_id})
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(q_b.get(), timeout=0.2)
    finally:
        events.unsubscribe("u2", q_b)
