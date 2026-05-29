"""Thin facade over the polymorphic AgentBackend layer.

`main.py` and `realtime.py` import `call_agent`, `call_agent_stream`, and
`call_agent_for_voice` from here. These signatures are preserved across
the Fase 1 ACP migration so the call sites do not change. Internally the
facade builds a `TurnContext` from the loose kwargs and delegates to the
backend returned by `_resolve_backend()`.

`_resolve_backend` looks up the conversation's `agent_id` and instantiates
the backend matching that instance's `transport` (`local-acp` →
`LocalAcpBackend`, `remote-acp` → `RemoteAcpBackend`). Conversations with a
NULL `agent_id` fall back to a local `hermes acp` subprocess (AC-W1-B1).
"""

from __future__ import annotations

import asyncio
import mimetypes
import os
from pathlib import Path
from typing import AsyncIterator, Optional

from agents.base import AgentBackend, AgentEvent, TurnContext
from agents.local_acp import LocalAcpBackend
from agents.registry import build_local_backend, resolve_token
from agents.remote_acp import RemoteAcpBackend
from config import agent_enabled
from database import (
    create_artifact,
    get_agent_instance,
    get_conversation,
    get_conversation_session_id,
    update_conversation_session_id,
)


def _snapshot_dir(path: str) -> dict[str, tuple[float, int]]:
    """Return {rel_path: (mtime, size)} for every file under `path`.

    Runs synchronously; wrap in asyncio.to_thread when calling from async code.
    Returns an empty dict when the directory doesn't exist or is empty.
    """
    result: dict[str, tuple[float, int]] = {}
    root = Path(path)
    if not root.is_dir():
        return result
    for dirpath, _, filenames in os.walk(root):
        for fname in filenames:
            full = Path(dirpath) / fname
            try:
                st = full.stat()
                rel = str(full.relative_to(root))
                result[rel] = (st.st_mtime, st.st_size)
            except OSError:
                pass
    return result


def _scan_new_artifacts(
    cwd: str,
    pre_snapshot: dict[str, tuple[float, int]],
) -> list[dict]:
    """Diff post-turn cwd state against pre_snapshot.

    Returns a list of dicts for files that are NEW or MODIFIED (by size or
    mtime). Each dict has: name, rel_path, mime_type, size_bytes, content_bytes.

    Runs synchronously; wrap in asyncio.to_thread when calling from async code.
    """
    post_snapshot = _snapshot_dir(cwd)
    results: list[dict] = []
    root = Path(cwd)
    for rel_path, (post_mtime, post_size) in post_snapshot.items():
        pre_entry = pre_snapshot.get(rel_path)
        if pre_entry is not None:
            pre_mtime, pre_size = pre_entry
            if post_mtime == pre_mtime and post_size == pre_size:
                continue
        full = root / rel_path
        try:
            content_bytes = full.read_bytes()
        except OSError:
            continue
        name = full.name
        mime_type, _ = mimetypes.guess_type(name)
        mime_type = mime_type or "application/octet-stream"
        results.append({
            "name": name,
            "rel_path": rel_path,
            "mime_type": mime_type,
            "size_bytes": len(content_bytes),
            "content_bytes": content_bytes,
        })
    return results


def _resolve_backend(conversation_id: Optional[str]) -> AgentBackend:
    """Pick the right AgentBackend for this turn.

    Resolution order:
      1. No conversation_id (voice without conversation, legacy callers) → Local.
      2. Conversation row missing or its agent_id is NULL → Local (AC-W1-B1).
      3. agent_instance.transport == "remote-acp" → RemoteAcpBackend, with
         token resolved via `_resolve_token()` (type-agnostic — the host runs
         whatever CLI it was provisioned with).
      4. Otherwise (local-acp / default) → the registry picks the backend by
         the instance `type` (AC-W2-A1). Adding a type needs no change here.
    """
    if not conversation_id:
        return LocalAcpBackend()

    conv = get_conversation(conversation_id)
    agent_id = conv.get("agent_id") if conv else None
    if not agent_id:
        return LocalAcpBackend()

    agent = get_agent_instance(agent_id)
    if not agent:
        return LocalAcpBackend()

    transport = agent.get("transport")
    if transport == "remote-acp":
        cfg = agent.get("transport_config") or {}
        return RemoteAcpBackend(
            url=cfg.get("url", ""),
            token=resolve_token(cfg.get("token", "")),
            system_prompt_override=agent.get("system_prompt_override"),
        )
    return build_local_backend(agent)


_DISABLED_MESSAGE = (
    "No external agent is configured. Set `agent.command` in config.yaml."
)


def _flatten_for_voice(text: str) -> str:
    """Strip markdown bullets/headings so TTS doesn't stutter on punctuation."""
    cleaned: list[str] = []
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        while s and s[0] in "-*#> ":
            s = s[1:].lstrip()
        cleaned.append(s)
    return " ".join(cleaned).strip() or text


async def call_agent_stream(
    query: str,
    user_name: str = "",
    user_id: str = "",
    user_role: str = "",
    *,
    image_paths: list[str] | None = None,
    conversation_id: str | None = None,
    log_prefix: str = "[agent/local_acp]",
) -> AsyncIterator[tuple[str, str]]:
    """Yield `(kind, text/dict)` tuples for each consumable AgentEvent.

    Yields kinds: "text", "reasoning", "artifact". The terminal "done" and
    internal "session"/"cwd" events are consumed without forwarding.

    AC-W3-A1: when a ("cwd", path) event arrives, a pre-turn snapshot is
    taken. After the stream completes, new/modified files are scanned and
    persisted as artifact rows; one ("artifact", dict) event is yielded per
    captured artifact (with message_id=None; the SSE caller attaches that
    after add_message returns).

    When `conversation_id` is given (AC-W1-D4), the facade:
      * loads the stored `hermes_session_id` and puts it on the
        TurnContext so the backend resumes the native session;
      * captures the `("session", id)` event the backend emits and
        persists it back to the conversation row if it changed.
    """
    if not agent_enabled():
        yield ("text", _DISABLED_MESSAGE)
        return

    prior_session = get_conversation_session_id(conversation_id) if conversation_id else None

    backend = _resolve_backend(conversation_id)
    context = TurnContext(
        user_id=user_id,
        user_name=user_name,
        user_role=user_role,
        session_id=prior_session,
    )
    print(f"{log_prefix} stream user={user_id} query={query[:80]!r}")

    cwd: str | None = None
    pre_snapshot: dict[str, tuple[float, int]] = {}

    async for kind, payload in backend.stream(query, context, image_paths=image_paths):
        if kind == "done":
            break
        if kind == "session" and isinstance(payload, str):
            if conversation_id and payload != prior_session:
                update_conversation_session_id(conversation_id, payload)
            continue
        if kind == "cwd" and isinstance(payload, str):
            cwd = payload
            pre_snapshot = await asyncio.to_thread(_snapshot_dir, cwd)
            continue
        if kind == "artifact":
            continue
        if kind in ("text", "reasoning") and isinstance(payload, str):
            yield (kind, payload)
        # "tool" events not yet surfaced in the UI — silently dropped.

    if cwd:
        new_files = await asyncio.to_thread(_scan_new_artifacts, cwd, pre_snapshot)
        for file_info in new_files:
            try:
                artifact = create_artifact(
                    name=file_info["name"],
                    rel_path=file_info["rel_path"],
                    content_bytes=file_info["content_bytes"],
                    conversation_id=conversation_id,
                )
                yield ("artifact", artifact)
            except Exception as exc:
                print(f"{log_prefix} artifact capture failed for {file_info['name']!r}: {exc}")


async def call_agent(
    query: str,
    user_name: str = "",
    user_id: str = "",
    user_role: str = "",
    *,
    conversation_id: str | None = None,
    log_prefix: str = "[agent]",
) -> str:
    """Run a turn and return the full assistant message as one string."""
    parts: list[str] = []
    async for kind, payload in call_agent_stream(
        query,
        user_name=user_name,
        user_id=user_id,
        user_role=user_role,
        conversation_id=conversation_id,
        log_prefix=log_prefix,
    ):
        if kind == "text":
            parts.append(payload)
    return "".join(parts) or "The agent returned no answer."


async def call_agent_for_voice(
    query: str,
    user_name: str = "",
    user_id: str = "",
    user_role: str = "",
    *,
    conversation_id: str | None = None,
) -> str:
    """Voice variant: flattens bullets / headings so TTS reads naturally."""
    answer = await call_agent(
        query,
        user_name=user_name,
        user_id=user_id,
        user_role=user_role,
        conversation_id=conversation_id,
        log_prefix="[realtime/agent]",
    )
    return _flatten_for_voice(answer)
