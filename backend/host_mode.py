"""Host mode — `/api/host/*` endpoints (Wave 1, Fase 3).

A `hermes-companion` instance switched into host mode exposes the local
`hermes acp` subprocess to remote `RemoteAcpBackend` clients over an
authenticated WebSocket. The same binary runs both roles; see
`docs/PRD-multi-agent.md` §3.2.

Endpoints:
  - `WS  /api/host/acp`     — bidirectional ACP bridge (PR #22).
  - `GET /api/host/skills`  — wraps `hermes skills list` (AC-W1-U4).
  - `GET /api/host/mcp`     — wraps `hermes mcp list` (AC-W1-U4).
  - `GET /api/host/tools`   — wraps `hermes tools --summary` (AC-W1-U4).
  - `GET /api/host/config`  — wraps `hermes config show` (AC-W1-U4).
"""

from __future__ import annotations

import asyncio
import mimetypes
import os
import tempfile
import uuid
from pathlib import Path
from typing import Optional

from fastapi import (
    APIRouter, Depends, File, HTTPException, Request, UploadFile, WebSocket,
)
from pydantic import BaseModel
from starlette.websockets import WebSocketDisconnect


class _SystemPromptBody(BaseModel):
    system_prompt: str

from database import verify_host_token


router = APIRouter()

_UPLOAD_MAX_BYTES = 16 * 1024 * 1024  # 16MB cap; vision frames are well below.


def _upload_dir() -> Path:
    """Where uploaded payloads live. Override in tests via monkeypatch.

    Production uses ``$HERMES_COMPANION_UPLOAD_DIR`` if set, else
    ``$TMPDIR/hermes-companion-uploads``. The directory is created on
    demand and reused across uploads.
    """
    override = os.environ.get("HERMES_COMPANION_UPLOAD_DIR")
    base = Path(override) if override else Path(tempfile.gettempdir()) / "hermes-companion-uploads"
    base.mkdir(parents=True, exist_ok=True)
    return base


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


async def _run_hermes_cli(args: list[str]) -> dict:
    """Production runner — tests monkeypatch this with a fake.

    Returns ``{"stdout": str, "stderr": str, "exit_code": int}``. Never
    raises for non-zero exit — the caller decides how to surface failure
    (we want to forward the CLI's own error text to the UI).
    """
    proc = await asyncio.create_subprocess_exec(
        "hermes", *args,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout_b, stderr_b = await proc.communicate()
    return {
        "stdout": stdout_b.decode("utf-8", errors="replace"),
        "stderr": stderr_b.decode("utf-8", errors="replace"),
        "exit_code": proc.returncode if proc.returncode is not None else -1,
    }


def _require_bearer(request: Request) -> None:
    token = _extract_bearer(request.headers)
    if not token or not verify_host_token(token):
        raise HTTPException(status_code=401, detail="invalid host token")


async def _wrapped_cli(args: list[str]) -> dict:
    """Run a CLI command; raise 502 on non-zero exit so the UI sees it."""
    result = await _run_hermes_cli(args)
    if result["exit_code"] != 0:
        raise HTTPException(status_code=502, detail=result)
    return result


@router.get("/api/host/skills", dependencies=[Depends(_require_bearer)])
async def host_skills() -> dict:
    return await _wrapped_cli(["skills", "list"])


@router.get("/api/host/mcp", dependencies=[Depends(_require_bearer)])
async def host_mcp() -> dict:
    return await _wrapped_cli(["mcp", "list"])


@router.get("/api/host/tools", dependencies=[Depends(_require_bearer)])
async def host_tools() -> dict:
    return await _wrapped_cli(["tools", "--summary"])


@router.get("/api/host/config", dependencies=[Depends(_require_bearer)])
async def host_config() -> dict:
    return await _wrapped_cli(["config", "show"])


@router.post("/api/host/upload", dependencies=[Depends(_require_bearer)])
async def host_upload(file: UploadFile = File(...)) -> dict:
    """Stash a payload server-side and return a handle the next ACP turn
    can reference (AC-W1-R4 precondition).

    Reads in fixed-size chunks so an oversize payload short-circuits
    without buffering the whole body. Mime type is taken from the upload
    metadata, falling back to a filename guess.
    """
    suffix = Path(file.filename or "").suffix
    target = _upload_dir() / f"{uuid.uuid4().hex}{suffix}"

    total = 0
    chunk_size = 64 * 1024
    try:
        with target.open("wb") as out:
            while True:
                chunk = await file.read(chunk_size)
                if not chunk:
                    break
                total += len(chunk)
                if total > _UPLOAD_MAX_BYTES:
                    out.close()
                    target.unlink(missing_ok=True)
                    raise HTTPException(
                        status_code=413,
                        detail=f"upload exceeds {_UPLOAD_MAX_BYTES} byte cap",
                    )
                out.write(chunk)
    finally:
        await file.close()

    mime_type = file.content_type or mimetypes.guess_type(file.filename or "")[0] or "application/octet-stream"
    return {
        "handle": str(target),
        "size": total,
        "mime_type": mime_type,
        "filename": file.filename,
    }


@router.post(
    "/api/host/config/system-prompt",
    dependencies=[Depends(_require_bearer)],
)
async def host_set_system_prompt(body: _SystemPromptBody) -> dict:
    """Materialise a per-call ``AGENTS.md`` Hermes will read at session
    creation, and return the cwd the client must pass to ``session/new``.

    This is the only knob Hermes' prompt builder respects from outside the
    process — there is no documented CLI flag for the system prompt. The
    cwd is ephemeral and disposable; cleanup is the remote backend's job
    once the session is closed.
    """
    prompt = body.system_prompt.strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="system_prompt must not be empty")

    session_dir = _upload_dir() / f"sp-{uuid.uuid4().hex}"
    session_dir.mkdir(parents=True, exist_ok=False)
    (session_dir / "AGENTS.md").write_text(body.system_prompt, encoding="utf-8")
    return {"cwd": str(session_dir)}


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
