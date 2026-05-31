"""AC-W3-T1 — GET /api/events SSE endpoint tests.

Covers: Scenarios 7, 8 (bus seam + SSE wire via generator), 11 (heartbeat),
cleanup on disconnect.

httpx.ASGITransport buffers the full response body before returning, so it
cannot be used with an infinite streaming generator — it hangs until the server
closes the stream (which never happens for SSE).  Instead we drive the
endpoint's async generator directly (wrapping it in an AsyncMock request) and
use the event bus subscription seam for wire-level SSE assertions.  This is
exactly the testability contract documented in design-t1 §10.

TDD note: all tests here were written BEFORE the handler existed (RED first).
"""

import asyncio
import json
from unittest.mock import AsyncMock

import pytest


# ── Scenario 7: auth required before stream opens ─────────────────────────────

def test_events_requires_auth(client):
    """Scenario 7: GET /api/events without cookie → 401 before stream opens."""
    client.cookies.clear()
    resp = client.get("/api/events")
    assert resp.status_code == 401


# ── Scenario 11: heartbeat emitted during idle stream ─────────────────────────

@pytest.mark.asyncio
async def test_events_emits_heartbeat(seeded_db, monkeypatch):
    """Scenario 11: heartbeat frame arrives after HEARTBEAT_INTERVAL_SECONDS.

    Drives the endpoint generator directly so the test is not blocked by
    httpx buffering.  Monkeypatches the interval to 0.05s.
    """
    import events
    monkeypatch.setattr(events, "HEARTBEAT_INTERVAL_SECONDS", 0.05)

    frames = await _drive_generator(seeded_db, n=2, deadline=2.0)

    heartbeats = [f for f in frames if f.get("event") == "companion.heartbeat"]
    assert len(heartbeats) >= 1


# ── Scenario 8: task.created arrives on SSE ───────────────────────────────────

@pytest.mark.asyncio
async def test_events_emits_task_created_frame(seeded_db, monkeypatch):
    """Scenario 8 (SSE wire via generator): companion.task.created delivered.

    Subscribes the generator for u1, then publishes a task.created event
    directly via the bus, and asserts the generator yields it.
    """
    import events
    monkeypatch.setattr(events, "HEARTBEAT_INTERVAL_SECONDS", 0.5)

    async def _publish_after_delay():
        await asyncio.sleep(0.15)
        events.publish_event(["u1"], {
            "event": "companion.task.created",
            "conversation_id": "conv-test",
            "task_id": "task-xyz",
            "payload": {"id": "task-xyz", "status": "pending"},
        })

    poster = asyncio.create_task(_publish_after_delay())
    try:
        frames = await _drive_generator(
            seeded_db, n=3, deadline=2.0, stop_event="companion.task.created"
        )
    finally:
        poster.cancel()
        try:
            await poster
        except asyncio.CancelledError:
            pass

    task_frames = [f for f in frames if f.get("event") == "companion.task.created"]
    assert len(task_frames) >= 1
    assert task_frames[0]["task_id"] == "task-xyz"


# ── Queue cleanup on disconnect ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_events_queue_pruned_on_disconnect(seeded_db, monkeypatch):
    """The generator's finally-block unsubscribes when the client disconnects.

    _drive_generator flips is_disconnected()→True after the prime frame, so the
    REAL production path runs (loop break → finally → unsubscribe). The prune is
    asserted deterministically — not via GC/refcount timing.
    """
    import events
    monkeypatch.setattr(events, "HEARTBEAT_INTERVAL_SECONDS", 0.05)

    assert "u1" not in events._subscribers
    await _drive_generator(seeded_db, n=1, deadline=2.0)
    assert "u1" not in events._subscribers


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_mock_request(user_id: str):
    """Minimal request mock for the api_events generator.

    The generator checks `await request.is_disconnected()` at each loop top.
    `_state["disconnected"]` is flipped by the driver once enough frames are
    collected, so the generator takes its real break → finally → unsubscribe
    path instead of being abandoned mid-stream (which would rely on GC).
    """
    req = AsyncMock()
    req.cookies = {"companion_user": user_id}
    state = {"disconnected": False}

    async def _is_disconnected():
        return state["disconnected"]

    req.is_disconnected = _is_disconnected
    req._state = state
    return req


async def _drive_generator(
    seeded_db,
    n: int,
    deadline: float,
    stop_event: str | None = None,
) -> list[dict]:
    """Call api_events, collect up to `n` frames, then signal disconnect and
    drain to completion so the generator's finally-block runs deterministically.

    Stops collecting early when `stop_event` is seen. The outer wait_for is a
    safety deadline only — under normal operation the stream ends itself.
    """
    import main

    req = _make_mock_request("u1")
    frames: list[dict] = []

    async def _consume():
        response = await main.api_events(req)
        # StreamingResponse body is an async generator. Once we have enough
        # frames we flip the request to disconnected and KEEP iterating — the
        # generator then breaks at its loop top and runs finally (unsubscribe),
        # ending the async-for cleanly without GC reliance.
        async for chunk in response.body_iterator:
            text = chunk.decode("utf-8", errors="replace") if isinstance(chunk, bytes) else chunk
            for raw_line in text.split("\n"):
                raw_line = raw_line.strip()
                if not raw_line.startswith("data: "):
                    continue
                try:
                    frame = json.loads(raw_line[6:])
                except json.JSONDecodeError:
                    continue
                frames.append(frame)
                if len(frames) >= n or (stop_event and frame.get("event") == stop_event):
                    req._state["disconnected"] = True

    try:
        await asyncio.wait_for(_consume(), timeout=deadline)
    except asyncio.TimeoutError:
        pass

    return frames
