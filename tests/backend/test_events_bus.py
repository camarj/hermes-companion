"""Unit tests for backend/events.py — the in-process SSE event bus.

All tests are synchronous-compatible: asyncio.Queue operations that we need
to await are run via asyncio.run() or pytest-asyncio's event loop.
"""

import asyncio

import pytest

import events


@pytest.fixture(autouse=True)
def reset_subscribers():
    """Clear the global subscriber dict before each test to prevent state leakage."""
    events._subscribers.clear()
    yield
    events._subscribers.clear()


# ── B-1: subscribe returns a queue ────────────────────────────────────────

def test_subscribe_returns_queue():
    q = events.subscribe("user-1")
    assert isinstance(q, asyncio.Queue)


# ── B-2: publish delivers to subscribed recipient ─────────────────────────

@pytest.mark.asyncio
async def test_publish_delivers_to_subscriber():
    q = events.subscribe("user-2")
    frame = {"event": "companion.task.created", "task_id": "t1", "payload": {}}
    events.publish_event(["user-2"], frame)
    received = await asyncio.wait_for(q.get(), timeout=0.5)
    assert received == frame


# ── B-3: unsubscribe removes queue and prunes empty key ───────────────────

def test_unsubscribe_removes_queue_and_prunes_key():
    q = events.subscribe("user-3")
    assert "user-3" in events._subscribers
    events.unsubscribe("user-3", q)
    assert "user-3" not in events._subscribers


# ── B-4: publish to absent user is a no-op ────────────────────────────────

def test_publish_to_absent_user_is_noop():
    events.publish_event(["ghost_user"], {"event": "companion.task.created", "payload": {}})
    assert "ghost_user" not in events._subscribers


# ── B-5: overflow drops oldest frame (drop-oldest policy) ─────────────────

@pytest.mark.asyncio
async def test_publish_drops_oldest_on_full_queue(monkeypatch):
    monkeypatch.setattr(events, "MAX_QUEUE_DEPTH", 2)
    q = events.subscribe("user-5")

    frame1 = {"event": "companion.task.created", "task_id": "t1", "payload": {}}
    frame2 = {"event": "companion.task.created", "task_id": "t2", "payload": {}}
    frame3 = {"event": "companion.task.created", "task_id": "t3", "payload": {}}

    events.publish_event(["user-5"], frame1)
    events.publish_event(["user-5"], frame2)
    events.publish_event(["user-5"], frame3)

    received = []
    while not q.empty():
        received.append(q.get_nowait())

    assert len(received) == 2
    assert received[0] == frame2
    assert received[1] == frame3


# ── B-6: two subscribers same user both receive (fan-out for multiple tabs) ─

@pytest.mark.asyncio
async def test_two_subscribers_same_user_both_receive():
    q1 = events.subscribe("user-6")
    q2 = events.subscribe("user-6")
    frame = {"event": "companion.task.created", "task_id": "t1", "payload": {}}
    events.publish_event(["user-6"], frame)
    r1 = await asyncio.wait_for(q1.get(), timeout=0.5)
    r2 = await asyncio.wait_for(q2.get(), timeout=0.5)
    assert r1 == frame
    assert r2 == frame


# ── Additional: non-recipient does not receive ─────────────────────────────

@pytest.mark.asyncio
async def test_non_recipient_does_not_receive():
    q_a = events.subscribe("user-a")
    q_b = events.subscribe("user-b")
    frame = {"event": "companion.task.created", "task_id": "t1", "payload": {}}
    events.publish_event(["user-a"], frame)
    assert q_b.empty()
    received = await asyncio.wait_for(q_a.get(), timeout=0.5)
    assert received == frame
    assert q_b.empty()


# ── Additional: unsubscribe is idempotent ─────────────────────────────────

def test_unsubscribe_is_idempotent():
    q = events.subscribe("user-idem")
    events.unsubscribe("user-idem", q)
    events.unsubscribe("user-idem", q)
    assert "user-idem" not in events._subscribers


# ── Additional: publish never blocks even when the queue overflows ────────

def test_publish_never_blocks_on_overflow(monkeypatch):
    monkeypatch.setattr(events, "MAX_QUEUE_DEPTH", 3)
    q = events.subscribe("user-nowait")
    # Push well past capacity: a blocking put() would hang here forever.
    for i in range(10):
        events.publish_event(["user-nowait"], {"event": "companion.heartbeat", "i": i})
    assert q.qsize() == 3
    # Freshest-wins: the oldest frames were dropped, the last 3 survive.
    survivors = [q.get_nowait()["i"] for _ in range(3)]
    assert survivors == [7, 8, 9]
