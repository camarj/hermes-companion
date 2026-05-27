"""Per-agent inspection dispatcher (AC-W1-U4 backend, follow-on to host_mode).

The frontend asks the companion for an agent's skills / mcp / tools /
config; this module decides whether to satisfy that locally (run the
`hermes` CLI in-process) or remotely (HTTP-proxy to the host bridge that
already exposes the same data).

Local agents reuse `host_mode._run_hermes_cli` so the command surface
stays in one place. Remote agents are reached via `httpx` against the
host URL derived from `transport_config.url`.
"""

from __future__ import annotations

import os
from typing import Optional

import httpx
from fastapi import HTTPException

from agents.remote_acp import _http_base_from_ws
import host_mode


# Subcommand catalog mirrors `host_mode` so the two stay in lockstep.
_LOCAL_ARGS = {
    "skills": ["skills", "list"],
    "mcp": ["mcp", "list"],
    "tools": ["tools", "--summary"],
    "config": ["config", "show"],
}


def _resolve_token(raw: str) -> str:
    """Mirrors agent_bridge._resolve_token; duplicated to avoid a cycle."""
    if raw.startswith("env:"):
        return os.environ.get(raw[len("env:"):], "")
    return raw


async def inspect_agent(agent: dict, kind: str) -> dict:
    """Return `{stdout, stderr, exit_code}` for one inspection subcommand.

    `agent` is a row from `agent_instances`. Raises HTTPException for
    transport-level failures so FastAPI routes can let it propagate.
    """
    if kind not in _LOCAL_ARGS:
        raise HTTPException(status_code=400, detail=f"unknown inspection: {kind!r}")

    transport = agent.get("transport")
    if transport == "local-acp":
        result = await host_mode._run_hermes_cli(_LOCAL_ARGS[kind])
        if result["exit_code"] != 0:
            raise HTTPException(status_code=502, detail=result)
        return result

    if transport == "remote-acp":
        cfg = agent.get("transport_config") or {}
        ws_url = cfg.get("url", "")
        if not ws_url:
            raise HTTPException(status_code=400, detail="remote agent has no url")
        base = _http_base_from_ws(ws_url)
        token = _resolve_token(cfg.get("token", ""))
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{base}/api/host/{kind}",
                headers={"Authorization": f"Bearer {token}"},
            )
        if resp.is_success:
            return resp.json()
        try:
            detail: object = resp.json()
        except Exception:
            detail = resp.text
        raise HTTPException(status_code=502, detail=detail)

    raise HTTPException(
        status_code=400,
        detail=f"unsupported transport for inspection: {transport!r}",
    )


def set_system_prompt(agent_id: str, prompt: Optional[str]) -> Optional[dict]:
    """Persist `system_prompt_override` for the agent (AC-W1-U5 backend).

    Empty/whitespace string is stored as an empty string — Local/Remote
    backends already treat falsy/whitespace as "no override", so the
    runtime effect is the same as clearing. The change takes effect on
    the NEXT turn because `_resolve_backend` re-reads the row each call.
    Returns the updated row, or None if no such agent.
    """
    from database import update_agent_instance

    value = prompt.strip() if prompt else ""
    return update_agent_instance(agent_id, system_prompt_override=value)
