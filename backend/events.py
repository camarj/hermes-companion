"""In-process SSE event bus.

One asyncio.Queue PER OPEN STREAM (not per user). A user with two browser
tabs has TWO queues registered under the same user_id; publish fans out to
all of them. Swappable for Redis later WITHOUT touching main.py — this module
is the only place that knows the queue dict exists.
"""
import asyncio

HEARTBEAT_INTERVAL_SECONDS = 30.0
MAX_QUEUE_DEPTH = 100

# user_id -> set of live per-stream queues
_subscribers: dict[str, set[asyncio.Queue]] = {}


def subscribe(user_id: str) -> asyncio.Queue:
    """Register a new per-stream queue for this user. Call once per SSE connection."""
    q: asyncio.Queue = asyncio.Queue(maxsize=MAX_QUEUE_DEPTH)
    _subscribers.setdefault(user_id, set()).add(q)
    return q


def unsubscribe(user_id: str, queue: asyncio.Queue) -> None:
    """Remove one stream's queue. Idempotent. Prunes the user_id key when the
    last stream for that user disconnects (no leaked empty sets)."""
    bucket = _subscribers.get(user_id)
    if not bucket:
        return
    bucket.discard(queue)
    if not bucket:
        _subscribers.pop(user_id, None)


def publish_event(user_ids: list[str], event: dict) -> None:
    """Fan a single event frame out to every open stream of every recipient user.

    NON-BLOCKING — never awaits I/O. If a user has no open stream this is a
    no-op (events are NOT buffered for absent users; the DB is the source of
    truth and the client reconciles via GET /api/tasks on reconnect).

    On a full queue (slow/stuck client) drop the OLDEST frame to make room,
    then enqueue the new one — bounded memory, freshest-wins.
    """
    for uid in user_ids:
        for q in list(_subscribers.get(uid, ())):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                # Single-threaded loop, no await between get and put: the queue
                # is guaranteed to have a free slot here, so the inner put cannot
                # raise QueueFull. The guard stays only to survive a future async
                # refactor without silently blocking.
                try:
                    q.get_nowait()        # drop oldest
                except asyncio.QueueEmpty:
                    pass
                try:
                    q.put_nowait(event)
                except asyncio.QueueFull:
                    pass                  # give up this frame; never block
