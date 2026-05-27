"""Host mode — `/api/host/*` endpoints (Wave 1, Fase 3).

A `hermes-companion` instance switched into host mode exposes the local
`hermes acp` subprocess to remote `RemoteAcpBackend` clients over an
authenticated WebSocket. The same binary runs both roles; see
`docs/PRD-multi-agent.md` §3.2.

This module currently provides the WebSocket bridge at
`/api/host/acp`. Inspection (`/api/host/skills`, etc.) and upload land
in a follow-up PR.
"""

from __future__ import annotations

import asyncio
import os
from typing import Optional

from fastapi import APIRouter, WebSocket
from starlette.websockets import WebSocketDisconnect

from database import verify_host_token


router = APIRouter()


async def _spawn_acp(env: dict[str, str]) -> asyncio.subprocess.Process:
    """Production spawn point — tests monkeypatch this with a fake."""
    proc_env = os.environ.copy()
    proc_env.update(env)
    return await asyncio.create_subprocess_exec(
        "hermes", "acp",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=proc_env,
    )


def _extract_bearer(headers) -> Optional[str]:
    auth = headers.get("authorization", "")
    if not auth.startswith("Bearer "):
        return None
    return auth[len("Bearer "):].strip() or None


def _identity_env_from_headers(headers) -> dict[str, str]:
    """Translate X-Requester-* WS headers into the AGENT_REQUESTER_* env
    contract Hermes already understands."""
    env: dict[str, str] = {"PYTHONUNBUFFERED": "1"}
    rid = headers.get("x-requester-id")
    if rid:
        env["AGENT_REQUESTER_ID"] = rid
    rname = headers.get("x-requester-name")
    if rname:
        env["AGENT_REQUESTER_NAME"] = rname
    role = headers.get("x-requester-role")
    if role:
        env["AGENT_REQUESTER_ROLE"] = role
    return env


@router.websocket("/api/host/acp")
async def host_acp(ws: WebSocket) -> None:
    """Bidirectional bridge: WS text frames ↔ `hermes acp` stdio.

    Auth: `Authorization: Bearer <token>` header where `<token>` matches
    a row in `host_tokens`. Anything else closes with WS code 4401.
    """
    token = _extract_bearer(ws.headers)
    if not token or not verify_host_token(token):
        await ws.close(code=4401)
        return

    await ws.accept()
    env = _identity_env_from_headers(ws.headers)
    proc = await _spawn_acp(env)

    async def _ws_to_proc() -> None:
        try:
            while True:
                msg = await ws.receive_text()
                proc.stdin.write((msg + "\n").encode("utf-8"))
                await proc.stdin.drain()
        except WebSocketDisconnect:
            return
        except Exception:
            return

    async def _proc_to_ws() -> None:
        try:
            while True:
                line = await proc.stdout.readline()
                if not line:
                    return
                text = line.decode("utf-8", errors="replace").rstrip("\r\n")
                if not text:
                    continue
                await ws.send_text(text)
        except Exception:
            return

    pump_in = asyncio.create_task(_ws_to_proc())
    pump_out = asyncio.create_task(_proc_to_ws())
    try:
        await asyncio.wait(
            [pump_in, pump_out],
            return_when=asyncio.FIRST_COMPLETED,
        )
    finally:
        pump_in.cancel()
        pump_out.cancel()
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        except Exception:
            pass
        try:
            await proc.wait()
        except Exception:
            pass
        try:
            await ws.close()
        except Exception:
            pass
