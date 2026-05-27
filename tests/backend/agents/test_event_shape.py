"""AC-W1-A2: AgentEvent is the discriminated union the frontend consumes.

Every event emitted by any backend must match one of:
  ("text", str), ("reasoning", str), ("tool", dict), ("done", None)
"""

from typing import AsyncIterator

from agents.base import AgentBackend, AgentEvent, TurnContext, is_agent_event


def test_valid_events_pass_the_guard():
    assert is_agent_event(("text", "hello"))
    assert is_agent_event(("reasoning", "thinking"))
    assert is_agent_event(("tool", {"name": "search", "args": {}}))
    assert is_agent_event(("session", "abc-123"))
    assert is_agent_event(("done", None))


def test_invalid_events_are_rejected():
    assert not is_agent_event(("text", 123))  # payload must be str
    assert not is_agent_event(("reasoning", None))
    assert not is_agent_event(("tool", "not a dict"))
    assert not is_agent_event(("session", 123))  # payload must be str
    assert not is_agent_event(("done", "not None"))
    assert not is_agent_event(("unknown_kind", "x"))
    assert not is_agent_event(("text",))  # too few elements
    assert not is_agent_event("text")  # not a tuple


async def test_arbitrary_backend_only_yields_valid_events():
    class Fake(AgentBackend):
        async def stream(
            self,
            query: str,
            context: TurnContext,
            *,
            image_paths: list[str] | None = None,
        ) -> AsyncIterator[AgentEvent]:
            yield ("reasoning", "let me think")
            yield ("tool", {"name": "noop", "args": {}})
            yield ("text", "answer")
            yield ("done", None)

    backend = Fake()
    ctx = TurnContext(user_id="x", user_name="X")
    async for event in backend.stream("q", ctx):
        assert is_agent_event(event), f"invalid event: {event!r}"
