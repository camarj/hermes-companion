"""
hermes-companion — FastAPI backend.

Multi-user voice + chat assistant. Voice goes through the OpenAI Realtime
API (WebSocket proxy in `realtime.py`); text chat goes through a generic
OpenAI-compatible Chat Completions endpoint. Both can optionally route
heavy/live-data requests to an external agent (see `agent_bridge.py`).
"""

import os
import json
import asyncio
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, WebSocket, UploadFile, File, Form, HTTPException, Response, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse, StreamingResponse, JSONResponse
from openai import OpenAI

import config
from config import load_dotenv_if_present
from database import (
    init_db,
    get_user, list_users,
    create_conversation, get_conversation, list_conversations,
    update_conversation_title, touch_conversation, delete_conversation,
    add_message, get_messages, get_conversation_context,
)
from agent_bridge import call_agent

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

load_dotenv_if_present()

LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")
LLM_API_KEY = os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")

COOKIE_NAME = "companion_user"

# Tool definition exposed to the text LLM. Same shape OpenAI / compatible
# endpoints expect for function calling. Only included if an agent is
# configured — otherwise the chat runs without tools.
CHAT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "call_agent",
            "description": (
                "Invoke the external agent for tasks that require live data, "
                "real-world actions, or memory of past conversations "
                "(calendar, email, files, web search, automations, scheduled "
                "tasks, etc.). Don't use it for chitchat or general knowledge."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": (
                            "Self-contained query for the agent. Include any "
                            "relevant context from the conversation."
                        ),
                    }
                },
                "required": ["query"],
            },
        },
    }
] if config.agent_enabled() else []

# ---------------------------------------------------------------------------
# LLM Client
# ---------------------------------------------------------------------------

llm_client = OpenAI(
    api_key=LLM_API_KEY if LLM_API_KEY else "dummy",
    base_url=LLM_BASE_URL,
)


def _system_messages(user_context: str = "") -> list[dict]:
    content = config.system_prompt_core()
    if user_context:
        content += f"\n\n═══ SESSION CONTEXT ═══\n{user_context}"
    return [{"role": "system", "content": content}]


async def chat_completion(messages: list[dict], user_context: str = "") -> str:
    all_messages = _system_messages(user_context) + messages
    response = llm_client.chat.completions.create(
        model=LLM_MODEL,
        messages=all_messages,
        temperature=0.7,
        max_tokens=500,
    )
    return response.choices[0].message.content


async def chat_completion_stream(messages: list[dict], user_context: str = ""):
    """Stream LLM response as a sequence of ('text', str), ('tool_call', dict),
    and ('error', str) events. The caller translates each into SSE.
    """
    all_messages = _system_messages(user_context) + messages
    queue: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_event_loop()

    def _sync_stream():
        try:
            kwargs = dict(
                model=LLM_MODEL,
                messages=all_messages,
                temperature=0.7,
                max_tokens=600,
                stream=True,
            )
            if CHAT_TOOLS:
                kwargs["tools"] = CHAT_TOOLS
                kwargs["tool_choice"] = "auto"
            stream = llm_client.chat.completions.create(**kwargs)
            partial_calls: dict[int, dict] = {}
            for chunk in stream:
                if not chunk.choices:
                    continue
                choice = chunk.choices[0]
                delta = choice.delta

                if getattr(delta, "content", None):
                    loop.call_soon_threadsafe(
                        queue.put_nowait, ("text", delta.content)
                    )

                if getattr(delta, "tool_calls", None):
                    for tc in delta.tool_calls:
                        idx = tc.index if tc.index is not None else 0
                        slot = partial_calls.setdefault(
                            idx, {"id": None, "name": "", "args": ""}
                        )
                        if tc.id:
                            slot["id"] = tc.id
                        fn = getattr(tc, "function", None)
                        if fn:
                            if fn.name:
                                slot["name"] += fn.name
                            if fn.arguments:
                                slot["args"] += fn.arguments

                if choice.finish_reason and partial_calls:
                    for slot in partial_calls.values():
                        loop.call_soon_threadsafe(
                            queue.put_nowait, ("tool_call", slot)
                        )
                    partial_calls = {}
        except Exception as exc:
            loop.call_soon_threadsafe(
                queue.put_nowait, ("error", f"{type(exc).__name__}: {exc}")
            )
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, None)

    import threading
    threading.Thread(target=_sync_stream, daemon=True).start()

    while True:
        item = await queue.get()
        if item is None:
            break
        yield item


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

frontend_path = Path(__file__).parent.parent / "frontend" / "static"


def get_current_user(request: Request) -> Optional[dict]:
    user_id = request.cookies.get(COOKIE_NAME)
    if not user_id:
        return None
    return get_user(user_id)


def _user_context_string(user: dict) -> str:
    if user["is_shared_space"]:
        return (
            f"You are in a SHARED conversation ({user['name']}). Multiple team "
            f"members may be reading. Address the group in plural when natural; "
            f"don't assume which person is speaking unless they identify themselves."
        )
    if user.get("role"):
        return f"You are talking with {user['name']} ({user['role']}). It's a private conversation."
    return f"You are talking with {user['name']}. It's a private conversation."


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
    return create_conversation(user["id"])


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

    context_msgs = get_conversation_context(conversation_id, max_messages=20)
    llm_messages = [{"role": m["role"], "content": m["content"]} for m in context_msgs]
    user_context = _user_context_string(user)

    try:
        response_text = await chat_completion(llm_messages, user_context)
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


@app.post("/api/chat/stream")
async def api_chat_stream(
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

    context_msgs = get_conversation_context(conversation_id, max_messages=20)
    llm_messages = [{"role": m["role"], "content": m["content"]} for m in context_msgs]
    user_context = _user_context_string(user)

    async def generate():
        full_response = ""

        async for event in chat_completion_stream(llm_messages, user_context):
            kind, payload = event

            if kind == "text":
                full_response += payload
                yield f"data: {json.dumps({'type': 'text', 'content': payload})}\n\n"

            elif kind == "tool_call":
                tool_name = payload.get("name") or "call_agent"
                try:
                    args = json.loads(payload.get("args") or "{}")
                except json.JSONDecodeError:
                    args = {}
                query = args.get("query") or message

                yield f"data: {json.dumps({'type': 'tool_started', 'tool': tool_name, 'query': query})}\n\n"
                try:
                    agent_answer = await call_agent(
                        query,
                        user_name=user["name"],
                        user_id=user["id"],
                        user_role=user.get("role", ""),
                    )
                except Exception as exc:
                    agent_answer = f"(Error querying agent: {exc})"
                yield f"data: {json.dumps({'type': 'tool_finished', 'tool': tool_name})}\n\n"

                full_response += agent_answer
                yield f"data: {json.dumps({'type': 'text', 'content': agent_answer})}\n\n"

            elif kind == "error":
                yield f"data: {json.dumps({'type': 'error', 'message': payload})}\n\n"

        if full_response.strip():
            add_message(conversation_id, "assistant", full_response.strip())
            touch_conversation(conversation_id)
        conv = get_conversation(conversation_id)

        yield f"data: {json.dumps({'type': 'done', 'conversation_id': conversation_id, 'title': conv['title'] if conv else None})}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------------------
# Root / health
# ---------------------------------------------------------------------------

@app.get("/")
async def root():
    index_path = frontend_path / "index.html"
    if index_path.exists():
        return FileResponse(str(index_path))
    return HTMLResponse(f"<h1>{config.assistant_name()} — frontend not found</h1>")


@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "llm_model": LLM_MODEL,
        "realtime": True,
        "agent_enabled": config.agent_enabled(),
    }


if frontend_path.exists():
    app.mount("/static", StaticFiles(directory=str(frontend_path)), name="static")


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
            f"the image unless explicitly asked.]"
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
