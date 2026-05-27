"""AC-W1-A1: AgentBackend defines the polymorphic contract.

Verifies the ABC enforces a `stream` method with the documented signature
and refuses instantiation of subclasses that don't implement it.
"""

import inspect
from typing import AsyncIterator

import pytest

from agents.base import AgentBackend, AgentEvent, TurnContext


def test_subclass_without_stream_cannot_be_instantiated():
    class Incomplete(AgentBackend):
        pass

    with pytest.raises(TypeError):
        Incomplete()  # type: ignore[abstract]


def test_stream_signature_matches_contract():
    sig = inspect.signature(AgentBackend.stream, eval_str=True)
    params = list(sig.parameters.values())
    # self + query + context + image_paths (keyword-only)
    assert [p.name for p in params] == ["self", "query", "context", "image_paths"]
    assert params[1].annotation is str
    assert params[2].annotation is TurnContext
    assert params[3].kind == inspect.Parameter.KEYWORD_ONLY
    assert params[3].default is None


def test_turn_context_carries_user_identity():
    ctx = TurnContext(user_id="alice", user_name="Alice", user_role="CEO")
    assert ctx.user_id == "alice"
    assert ctx.user_name == "Alice"
    assert ctx.user_role == "CEO"


def test_turn_context_defaults_role_to_empty():
    ctx = TurnContext(user_id="bob", user_name="Bob")
    assert ctx.user_role == ""


async def test_concrete_subclass_with_stream_can_be_instantiated_and_iterated():
    class Echo(AgentBackend):
        async def stream(
            self,
            query: str,
            context: TurnContext,
            *,
            image_paths: list[str] | None = None,
        ) -> AsyncIterator[AgentEvent]:
            yield ("text", query)
            yield ("done", None)

    backend = Echo()
    ctx = TurnContext(user_id="x", user_name="X")
    events = [ev async for ev in backend.stream("ping", ctx)]
    assert events == [("text", "ping"), ("done", None)]
