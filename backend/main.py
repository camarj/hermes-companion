"""
hermes-companion — FastAPI backend.

Multi-user voice + chat assistant. Voice/vision go through the OpenAI Realtime
API (WebSocket proxy in `realtime.py`); text chat is a direct passthrough to
the external agent (see `agent_bridge.py`).
"""

import json
import os
import uuid
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, WebSocket, UploadFile, File, Form, HTTPException, Response, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse, StreamingResponse, JSONResponse

import config
from config import load_dotenv_if_present
from database import (
    init_db,
    get_user, list_users,
    create_conversation, get_conversation, list_conversations,
    update_conversation_title, touch_conversation, delete_conversation,
    add_message, get_messages,
    list_agent_instances, get_agent_instance,
    create_agent_instance, update_agent_instance, delete_agent_instance,
    count_conversations_for_agent,
)
from agent_bridge import call_agent, call_agent_stream
from host_mode import router as host_router

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

load_dotenv_if_present()

COOKIE_NAME = "companion_user"


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

init_db()

app = FastAPI(title=f"{config.assistant_name()} — Voice", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(host_router)


def _is_host_mode() -> bool:
    """True when this process should serve ONLY /api/host/* and /api/health."""
    return os.environ.get("HERMES_COMPANION_MODE", "").lower() == "host"


_HOST_MODE_ALLOWLIST = ("/api/host", "/api/health")


@app.middleware("http")
async def host_mode_filter(request: Request, call_next):
    """In host mode (HERMES_COMPANION_MODE=host) 404 every client-facing
    HTTP route. WebSocket routes are handled individually inside their
    handlers since middleware doesn't intercept WS upgrades."""
    if _is_host_mode():
        path = request.url.path
        if not any(path.startswith(p) for p in _HOST_MODE_ALLOWLIST):
            return JSONResponse(
                status_code=404,
                content={"detail": "endpoint disabled in host mode"},
            )
    return await call_next(request)

frontend_path = Path(__file__).parent.parent / "frontend" / "static"
react_build_path = frontend_path / "next"


def get_current_user(request: Request) -> Optional[dict]:
    user_id = request.cookies.get(COOKIE_NAME)
    if not user_id:
        return None
    return get_user(user_id)


# ---------------------------------------------------------------------------
# Public config (frontend reads this to render branding + users)
# ---------------------------------------------------------------------------

@app.get("/api/config")
async def api_config():
    return {
        "assistant_name": config.assistant_name(),
        "company_name": config.company_name(),
        "company_url": config.company_url(),
        "language": config.default_language(),
        "agent_enabled": config.agent_enabled(),
        "agent_label": config.agent_label(),
    }


# ---------------------------------------------------------------------------
# Auth & users
# ---------------------------------------------------------------------------

@app.get("/api/users")
async def api_list_users():
    return {"users": list_users()}


@app.post("/api/login")
async def api_login(user_id: str = Form(...), response: Response = None):
    user = get_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    resp = JSONResponse({"success": True, "user": user})
    resp.set_cookie(
        key=COOKIE_NAME,
        value=user_id,
        httponly=False,
        max_age=60 * 60 * 24 * 365,
        samesite="lax",
    )
    return resp


@app.post("/api/logout")
async def api_logout():
    resp = JSONResponse({"success": True})
    resp.delete_cookie(key=COOKIE_NAME)
    return resp


@app.get("/api/me")
async def api_me(request: Request):
    user = get_current_user(request)
    if not user:
        return {"authenticated": False}
    return {"authenticated": True, "user": user}


# ---------------------------------------------------------------------------
# Conversation endpoints
# ---------------------------------------------------------------------------

@app.get("/api/conversations")
async def api_list_conversations(request: Request):
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return {"conversations": list_conversations(user["id"])}


@app.post("/api/conversations")
async def api_create_conversation(request: Request):
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        body = await request.json()
    except Exception:
        body = {}
    agent_id = body.get("agent_id") if isinstance(body, dict) else None
    try:
        return create_conversation(user["id"], agent_id=agent_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


def _require_conversation_access(user: dict, conv_id: str) -> dict:
    conv = get_conversation(conv_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if conv["user_id"] == user["id"]:
        return conv
    owner = get_user(conv["user_id"])
    if owner and owner.get("is_shared_space"):
        return conv
    raise HTTPException(status_code=403, detail="Access denied")


@app.get("/api/conversations/{conv_id}")
async def api_get_conversation(conv_id: str, request: Request):
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    conv = _require_conversation_access(user, conv_id)
    return {"conversation": conv, "messages": get_messages(conv_id)}


@app.patch("/api/conversations/{conv_id}")
async def api_update_conversation(conv_id: str, request: Request):
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    body = await request.json()
    title = body.get("title")
    if not title:
        raise HTTPException(status_code=400, detail="Title required")
    _require_conversation_access(user, conv_id)
    update_conversation_title(conv_id, title)
    return {"success": True}


@app.delete("/api/conversations/{conv_id}")
async def api_delete_conversation(conv_id: str, request: Request):
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    _require_conversation_access(user, conv_id)
    delete_conversation(conv_id)
    return {"success": True}


# ---------------------------------------------------------------------------
# Agents registry (Wave 1, Fase 2)
# ---------------------------------------------------------------------------


@app.get("/api/agents")
async def api_list_agents(request: Request):
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return {"agents": list_agent_instances()}


@app.post("/api/agents", status_code=201)
async def api_create_agent(request: Request):
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    body = await request.json()
    if not isinstance(body, dict):
        raise HTTPException(status_code=422, detail="JSON object required")

    agent_id = body.get("id")
    label = body.get("label")
    if not isinstance(agent_id, str) or not agent_id.strip():
        raise HTTPException(status_code=422, detail="`id` is required")
    if not isinstance(label, str) or not label.strip():
        raise HTTPException(status_code=422, detail="`label` is required")

    if get_agent_instance(agent_id):
        raise HTTPException(status_code=409, detail=f"agent_id {agent_id!r} already exists")

    return create_agent_instance(
        id=agent_id,
        label=label,
        type=body.get("type", "hermes"),
        transport=body.get("transport", "local-acp"),
        transport_config=body.get("transport_config") or {},
        system_prompt_override=body.get("system_prompt_override"),
        enabled=bool(body.get("enabled", True)),
        created_via="user",
    )


@app.put("/api/agents/{agent_id}")
async def api_update_agent(agent_id: str, request: Request):
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    body = await request.json()
    if not isinstance(body, dict):
        raise HTTPException(status_code=422, detail="JSON object required")

    updated = update_agent_instance(
        agent_id,
        label=body.get("label"),
        transport_config=body.get("transport_config"),
        system_prompt_override=body.get("system_prompt_override"),
        enabled=body.get("enabled"),
    )
    if not updated:
        raise HTTPException(status_code=404, detail=f"agent_id {agent_id!r} not found")
    return updated


@app.delete("/api/agents/{agent_id}", status_code=204)
async def api_delete_agent(agent_id: str, request: Request):
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    if not get_agent_instance(agent_id):
        raise HTTPException(status_code=404, detail=f"agent_id {agent_id!r} not found")
    if count_conversations_for_agent(agent_id) > 0:
        raise HTTPException(
            status_code=409,
            detail=f"agent_id {agent_id!r} has conversations; reassign or delete them first",
        )
    delete_agent_instance(agent_id)
    return Response(status_code=204)
    return {"success": True}


# ---------------------------------------------------------------------------
# Text chat
# ---------------------------------------------------------------------------

@app.post("/api/chat")
async def api_chat(
    request: Request,
    message: str = Form(...),
    conversation_id: Optional[str] = Form(None),
):
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    if conversation_id:
        _require_conversation_access(user, conversation_id)
    else:
        conv = create_conversation(user["id"])
        conversation_id = conv["id"]

    add_message(conversation_id, "user", message)

    try:
        response_text = await call_agent(
            message,
            user_name=user["name"],
            user_id=user["id"],
            user_role=user.get("role", ""),
            conversation_id=conversation_id,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    add_message(conversation_id, "assistant", response_text)
    touch_conversation(conversation_id)
    conv = get_conversation(conversation_id)

    return {
        "success": True,
        "response": response_text,
        "conversation_id": conversation_id,
        "title": conv["title"] if conv else None,
    }


def _chunk_for_streaming(text: str, chunk_chars: int = 40):
    """Split text into smaller chunks on word boundaries so the frontend
    animates the answer streaming in instead of rendering it as one blob.
    Hermes -z returns a single payload, so chunking happens on our side."""
    if not text:
        return
    pos = 0
    n = len(text)
    while pos < n:
        end = min(pos + chunk_chars, n)
        if end < n:
            space_idx = text.rfind(" ", pos, end)
            if space_idx > pos:
                end = space_idx + 1
        yield text[pos:end]
        pos = end


def _extract_latest_user_text(messages: list[dict]) -> str:
    """Pull the most recent user message's text out of an AI SDK UIMessage
    array. Each message has a `parts: [{type, text}, ...]` shape; we
    concatenate all text parts on the last user message."""
    if not messages:
        return ""
    for msg in reversed(messages):
        if msg.get("role") != "user":
            continue
        parts = msg.get("parts") or []
        chunks = [p.get("text", "") for p in parts if p.get("type") == "text"]
        return "".join(chunks).strip()
    return ""


# Per-file and per-turn caps mirror the frontend (chat-input.tsx). Defense in
# depth — the browser is the source of truth for UX but we re-check here so a
# crafted request can't blow past the agent's context.
_ATT_MAX_FILE_BYTES = 1_000_000           # 1 MB raw (text/pdf/image bytes)
_ATT_MAX_TOTAL_BYTES = 2_000_000          # 2 MB inline text per turn (images don't count)
_ATT_MAX_FILES = 5
_IMAGE_EXTS = {"png", "jpg", "jpeg", "webp", "gif"}


def _ext_of(name: str) -> str:
    name = name.lower()
    i = name.rfind(".")
    return name[i + 1:] if i >= 0 else ""


def _is_image_name(name: str) -> bool:
    return _ext_of(name) in _IMAGE_EXTS


def _extract_pdf_text(b64_data: str) -> str:
    """Decode a base64-encoded PDF and return its extracted text. Raises on
    malformed/encrypted PDFs so the caller can surface a useful error."""
    import base64
    import io
    from pypdf import PdfReader

    pdf_bytes = base64.b64decode(b64_data, validate=True)
    reader = PdfReader(io.BytesIO(pdf_bytes))
    if reader.is_encrypted:
        raise ValueError("PDF is password-protected")
    pages: list[str] = []
    for i, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception as e:
            text = f"[Could not extract page {i}: {e}]"
        pages.append(text.strip())
    return "\n\n".join(p for p in pages if p)


def _sanitize_attachments(raw: object) -> list[dict]:
    """Validate the `attachments` field from the chat request body.

    Returns a list of `{name, content, kind}` dicts.
    - kind="text": content is the file's text (passed inline to the agent query)
    - kind="pdf":  content is extracted text (treated like text downstream)
    - kind="image": content stays base64; images go to the agent via `--image`
      argv, not inlined in the query.

    Drops malformed entries; surfaces PDF extraction failures inline so the
    user/agent sees a useful placeholder instead of mysterious silence.
    """
    if not isinstance(raw, list):
        return []
    out: list[dict] = []
    total_text = 0
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip() or "attachment"
        content = item.get("content")
        if not isinstance(content, str):
            continue

        is_pdf = name.lower().endswith(".pdf")
        is_image = _is_image_name(name)

        if is_image:
            # Cap on the decoded image size, not the base64 wire size.
            img_bytes_len = (len(content) * 3) // 4
            if img_bytes_len > _ATT_MAX_FILE_BYTES:
                continue
            out.append({"name": name, "content": content, "kind": "image"})
        elif is_pdf:
            try:
                pdf_bytes_len = (len(content) * 3) // 4
                if pdf_bytes_len > _ATT_MAX_FILE_BYTES:
                    continue
                extracted = _extract_pdf_text(content) or "[PDF contained no extractable text]"
            except Exception as e:
                extracted = f"[Could not parse PDF: {e}]"
            text_len = len(extracted.encode("utf-8", errors="replace"))
            if text_len > _ATT_MAX_FILE_BYTES:
                continue
            if total_text + text_len > _ATT_MAX_TOTAL_BYTES:
                break
            out.append({"name": name, "content": extracted, "kind": "pdf"})
            total_text += text_len
        else:
            text_len = len(content.encode("utf-8", errors="replace"))
            if text_len > _ATT_MAX_FILE_BYTES:
                continue
            if total_text + text_len > _ATT_MAX_TOTAL_BYTES:
                break
            out.append({"name": name, "content": content, "kind": "text"})
            total_text += text_len

        if len(out) >= _ATT_MAX_FILES:
            break
    return out


def _compose_query_with_attachments(message: str, attachments: list[dict]) -> str:
    """Inline text/pdf attachments into the query; images are noted by name
    only (their content goes to the agent via `--image` argv)."""
    text_atts = [a for a in attachments if a.get("kind") != "image"]
    image_atts = [a for a in attachments if a.get("kind") == "image"]
    if not text_atts and not image_atts:
        return message
    parts: list[str] = []
    for att in text_atts:
        parts.append(f"[Adjunto: {att['name']}]")
        parts.append(att["content"].rstrip())
        parts.append("---")
    if image_atts:
        names = ", ".join(a["name"] for a in image_atts)
        parts.append(f"[Imágenes adjuntas: {names}]")
    parts.append(message)
    return "\n".join(p for p in parts if p)


def _materialize_image_attachments(attachments: list[dict]) -> tuple[list[str], "str | None"]:
    """Write image attachments to a fresh temp dir; return (paths, dir).
    Caller is responsible for cleaning up the temp dir after the request."""
    import base64
    import os
    import tempfile

    images = [a for a in attachments if a.get("kind") == "image"]
    if not images:
        return [], None
    temp_dir = tempfile.mkdtemp(prefix="companion-att-")
    paths: list[str] = []
    for idx, att in enumerate(images):
        ext = _ext_of(att["name"]) or "bin"
        safe = f"img_{idx}.{ext}"
        path = os.path.join(temp_dir, safe)
        try:
            with open(path, "wb") as f:
                f.write(base64.b64decode(att["content"], validate=True))
            paths.append(path)
        except Exception as e:
            print(f"[attachments] failed to write image {att['name']}: {e}")
    return paths, temp_dir


@app.post("/api/chat/stream")
async def api_chat_stream(request: Request):
    """Vercel AI SDK 6 UI Message Stream Protocol.

    Accepts a JSON body shaped like `useChat` from `@ai-sdk/react` sends:
        {
          "id": "<chat-id>",
          "messages": [{ "id", "role", "parts": [{"type":"text","text":"..."}] }],
          "trigger": "submit-user-message",
          "conversation_id": "..."   // custom body field from useChat({ body })
        }

    Returns an SSE stream of AI SDK 6 part frames (text-*, reasoning-*,
    tool-input-*, tool-output-*, data-conversation, finish, [DONE]).
    """
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Body must be JSON")

    message = _extract_latest_user_text(body.get("messages") or [])
    attachments = _sanitize_attachments(body.get("attachments"))
    if not message and not attachments:
        raise HTTPException(status_code=400, detail="No user message in body")

    conversation_id = body.get("conversation_id") or None
    if conversation_id:
        _require_conversation_access(user, conversation_id)
    else:
        conv = create_conversation(user["id"])
        conversation_id = conv["id"]

    agent_query = _compose_query_with_attachments(message, attachments)
    image_paths, image_temp_dir = _materialize_image_attachments(attachments)
    add_message(conversation_id, "user", message or " ".join(f"[{a['name']}]" for a in attachments))
    tool_call_id = f"call_{uuid.uuid4().hex[:12]}"
    message_id = f"msg_{uuid.uuid4().hex[:12]}"
    text_id = f"t_{uuid.uuid4().hex[:8]}"

    def frame(obj: dict) -> str:
        return f"data: {json.dumps(obj)}\n\n"

    async def generate():
        import shutil

        full_answer_parts: list[str] = []
        text_started = False
        reasoning_index = 0

        yield frame({"type": "start", "messageId": message_id})
        yield frame({
            "type": "tool-input-start",
            "toolCallId": tool_call_id,
            "toolName": "call_agent",
        })
        yield frame({
            "type": "tool-input-available",
            "toolCallId": tool_call_id,
            "toolName": "call_agent",
            "input": {"query": message},
        })

        try:
            async for kind, content in call_agent_stream(
                agent_query,
                user_name=user["name"],
                user_id=user["id"],
                user_role=user.get("role", ""),
                image_paths=image_paths,
                conversation_id=conversation_id,
            ):
                if kind == "reasoning":
                    reasoning_index += 1
                    rid = f"r_{reasoning_index}_{uuid.uuid4().hex[:6]}"
                    yield frame({"type": "reasoning-start", "id": rid})
                    yield frame({"type": "reasoning-delta", "id": rid, "delta": content})
                    yield frame({"type": "reasoning-end", "id": rid})
                else:  # "text"
                    if not text_started:
                        yield frame({
                            "type": "tool-output-available",
                            "toolCallId": tool_call_id,
                            "output": {"ok": True},
                        })
                        yield frame({"type": "text-start", "id": text_id})
                        text_started = True
                    for chunk in _chunk_for_streaming(content):
                        full_answer_parts.append(chunk)
                        yield frame({
                            "type": "text-delta",
                            "id": text_id,
                            "delta": chunk,
                        })
        except Exception as exc:
            yield frame({
                "type": "error",
                "errorText": f"{type(exc).__name__}: {exc}",
            })
            yield "data: [DONE]\n\n"
            return
        finally:
            if image_temp_dir:
                shutil.rmtree(image_temp_dir, ignore_errors=True)

        if text_started:
            yield frame({"type": "text-end", "id": text_id})

        full_text = "".join(full_answer_parts).strip()
        if full_text:
            add_message(conversation_id, "assistant", full_text)
            touch_conversation(conversation_id)
        conv = get_conversation(conversation_id)

        yield frame({
            "type": "data-conversation",
            "data": {
                "id": conversation_id,
                "title": conv["title"] if conv else None,
            },
        })
        yield frame({"type": "finish"})
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "x-vercel-ai-ui-message-stream": "v1",
        },
    )


# ---------------------------------------------------------------------------
# Root / health
# ---------------------------------------------------------------------------

@app.get("/")
async def root():
    """Serve the React build. start.sh auto-builds it on first launch."""
    index_path = react_build_path / "index.html"
    if index_path.exists():
        return FileResponse(str(index_path))
    return HTMLResponse(
        f"<h1>{config.assistant_name()} — React build missing</h1>"
        "<p>Run <code>cd frontend && npm run build</code> "
        "(or restart with <code>./start.sh</code>).</p>"
    )


@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "realtime": True,
        "agent_enabled": config.agent_enabled(),
        "agent_label": config.agent_label(),
    }


# /static serves the React build's hashed assets (CSS/JS) at /static/next/...
# html=True lets /static/next/ resolve to index.html for direct navigation.
if frontend_path.exists():
    app.mount(
        "/static",
        StaticFiles(directory=str(frontend_path), html=True),
        name="static",
    )


# ---------------------------------------------------------------------------
# Vision (face recognition + camera frame injection into Realtime session)
# ---------------------------------------------------------------------------
import base64 as _b64
from realtime import realtime_proxy, inject_vision_message
from face_service import enroll_face, recognize_people_in_image
from database import (
    list_known_faces,
    delete_known_face,
    delete_known_faces_by_name,
)


@app.post("/api/vision/snapshot")
async def api_vision_snapshot(request: Request):
    """Inject a camera snapshot into the user's active Realtime session.

    Body (JSON):
      - image: data URL ("data:image/jpeg;base64,...") from the browser canvas
      - prompt (optional): caption / question attached to the frame
    """
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    image = (body.get("image") or "").strip()
    if not image.startswith("data:image/"):
        raise HTTPException(status_code=400, detail="image must be a data:image/... URL")

    prompt = body.get("prompt")
    if prompt is not None:
        prompt = str(prompt).strip() or None

    recognized: list[str] = []
    try:
        _, b64data = image.split(",", 1)
        image_bytes = _b64.b64decode(b64data)
        recognized = await recognize_people_in_image(image_bytes)
    except Exception as e:
        print(f"[vision] recognition failed (continuing): {e}")

    augmented_prompt = prompt
    if recognized:
        names_str = ", ".join(recognized)
        prefix = (
            f"[System context (do NOT read aloud): the people visible in this image are: "
            f"{names_str}. Address them by name when you speak, but do not describe "
            f"the image unless explicitly asked. Respond in {config.language_name()}.]"
        )
        augmented_prompt = f"{prefix} {augmented_prompt}" if augmented_prompt else prefix

    ok = await inject_vision_message(user["id"], image, augmented_prompt)
    if not ok:
        raise HTTPException(
            status_code=409,
            detail="No active Realtime session. Enable vision + voice mode before sending a snapshot.",
        )
    return {"success": True, "recognized": recognized}


@app.post("/api/vision/recognize")
async def api_vision_recognize(request: Request):
    """Run face recognition only — do NOT inject the frame into the Realtime
    session. Used by the silent polling that detects when a known person
    enters the camera so we can fire a targeted greeting."""
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")
    image = (body.get("image") or "").strip()
    if not image.startswith("data:image/"):
        raise HTTPException(status_code=400, detail="image must be a data:image/... URL")
    try:
        _, b64data = image.split(",", 1)
        image_bytes = _b64.b64decode(b64data)
        names = await recognize_people_in_image(image_bytes)
    except Exception as e:
        print(f"[vision] recognize-only failed: {e}")
        names = []
    return {"recognized": names}


# ── People (face enrollment) ────────────────────────────────────────────────

@app.post("/api/people/enroll")
async def api_enroll_person(
    request: Request,
    name: str = Form(...),
    photo: UploadFile = File(...),
):
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    name_clean = (name or "").strip()
    if not name_clean:
        raise HTTPException(status_code=400, detail="name required")
    contents = await photo.read()
    if not contents:
        raise HTTPException(status_code=400, detail="empty photo")
    try:
        result = await enroll_face(user["id"], name_clean, contents)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        print(f"[vision] enroll error: {e}")
        raise HTTPException(status_code=500, detail="Error processing the photo")
    return {"success": True, "id": result["id"], "name": result["name"]}


@app.get("/api/people")
async def api_list_people(request: Request):
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    rows = list_known_faces(include_embeddings=False)
    grouped: dict[str, list[dict]] = {}
    for r in rows:
        grouped.setdefault(r["name"], []).append(r)
    summary = [
        {"name": n, "count": len(items), "ids": [it["id"] for it in items]}
        for n, items in sorted(grouped.items(), key=lambda kv: kv[0].lower())
    ]
    return {"people": summary}


@app.delete("/api/people/by-name/{name}")
async def api_delete_person_by_name(name: str, request: Request):
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    count = delete_known_faces_by_name(name)
    return {"success": True, "deleted": count}


@app.delete("/api/people/{face_id}")
async def api_delete_face(face_id: int, request: Request):
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    if not delete_known_face(face_id):
        raise HTTPException(status_code=404, detail="not found")
    return {"success": True}


# ---------------------------------------------------------------------------
# Realtime API WebSocket proxy
# ---------------------------------------------------------------------------

@app.websocket("/api/realtime")
async def ws_realtime(websocket: WebSocket):
    """WebSocket proxy to OpenAI Realtime API with optional agent tool calling.

    The user is taken from the `companion_user` cookie — query params are
    ignored so a client cannot spoof identity. Query params: conversation_id
    (optional — created if missing, ownership checked).
    """
    cookie_user_id = websocket.cookies.get(COOKIE_NAME)
    user = get_user(cookie_user_id) if cookie_user_id else None
    if not user:
        await websocket.close(code=4401, reason="not authenticated")
        return

    conversation_id = websocket.query_params.get("conversation_id") or None
    if conversation_id:
        conv = get_conversation(conversation_id)
        if not conv or (conv["user_id"] != user["id"] and not user["is_shared_space"]):
            await websocket.close(code=4403, reason="conversation not owned by user")
            return

    await realtime_proxy(websocket, user_id=user["id"], conversation_id=conversation_id)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
