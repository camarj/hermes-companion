"""
Realtime API proxy.

WebSocket proxy between the browser and OpenAI's Realtime API. Trivial
conversations are handled directly by the Realtime model; complex tasks
(live data, memory, automations) are routed to the external agent via the
`call_agent` function-call tool.

Messages are persisted to SQLite for conversation history.
"""

import os
import json
import time
import base64
import asyncio
import websockets
from fastapi import WebSocket, WebSocketDisconnect

import config
from agent_bridge import call_agent_for_voice
from database import (
    add_message, touch_conversation,
    create_conversation, get_conversation,
    get_user,
)

# Env vars loaded by main.py via config.load_dotenv_if_present() before this
# module is imported, so os.getenv reads the right values here too.

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY") or os.getenv("VOICE_TOOLS_OPENAI_KEY", "")
REALTIME_MODEL = os.getenv("REALTIME_MODEL", "gpt-realtime-2")
REALTIME_VOICE = os.getenv("REALTIME_VOICE", "marin")

# Server-side audio playback ("local" mode, for in-room meetings): raw PCM16
# 24kHz mono piped to aplay's stdin — no extra deps.
APLAY_BIN = os.getenv("APLAY_BIN", "/usr/bin/aplay")

# OpenAI server-side VAD config. In LOCAL mode the backend half-duplex stops
# mic chunks from reaching OpenAI while the assistant is speaking, so we don't
# need the harsher LOCAL tuning that used to live here.
VAD_THRESHOLD = float(os.getenv("VAD_THRESHOLD", "0.5"))
VAD_SILENCE_MS = int(os.getenv("VAD_SILENCE_MS", "500"))
VAD_PREFIX_PADDING_MS = int(os.getenv("VAD_PREFIX_PADDING_MS", "300"))


def turn_detection_for(mode: str, vision_mode: bool = False) -> dict:
    """Return the server_vad config.

    `vision_mode=True` disables `create_response` so the backend can inject the
    camera frame as an extra `conversation.item.create` and then explicitly
    fire `response.create`. Without this, OpenAI would auto-respond right after
    speech ends and the image would arrive too late to influence the turn.
    """
    return {
        "type": "server_vad",
        "threshold": VAD_THRESHOLD,
        "prefix_padding_ms": VAD_PREFIX_PADDING_MS,
        "silence_duration_ms": VAD_SILENCE_MS,
        "create_response": not vision_mode,
        "interrupt_response": True,
    }


OPENAI_REALTIME_URL = f"wss://api.openai.com/v1/realtime?model={REALTIME_MODEL}"


# ── Registry of active Realtime sessions (by user_id) ────────────────────────
# The HTTP /api/vision/snapshot endpoint needs to reach into the WebSocket of
# an in-flight Realtime session to inject an image. We keep a per-user pointer
# to the OpenAI-side websocket; the proxy registers itself on connect and
# clears the pointer on disconnect (only if it still owns the entry, so a
# newer session in another tab isn't accidentally evicted).
_active_sessions: dict[str, "websockets.WebSocketClientProtocol"] = {}


def _register_session(user_id: str, openai_ws) -> None:
    _active_sessions[user_id] = openai_ws


def _unregister_session(user_id: str, openai_ws) -> None:
    if _active_sessions.get(user_id) is openai_ws:
        _active_sessions.pop(user_id, None)


async def inject_vision_message(
    user_id: str,
    image_data_url: str,
    prompt_text: str | None = None,
) -> bool:
    """Inject an image (and optional caption) into the user's active Realtime
    session and trigger a spoken response.

    `image_data_url` must be a `data:image/...;base64,...` URL produced by the
    browser's canvas.toDataURL(). The GA Realtime API accepts it as the
    `image_url` field of an `input_image` content part.
    """
    openai_ws = _active_sessions.get(user_id)
    if openai_ws is None:
        return False

    lang_hint = f" Respond in {config.language_name()}."
    content: list[dict] = []
    if prompt_text:
        content.append({"type": "input_text", "text": prompt_text + lang_hint})
    else:
        content.append({
            "type": "input_text",
            "text": (
                "Here's an image of what I'm seeing right now. Use it as silent context."
                + lang_hint
            ),
        })
    content.append({"type": "input_image", "image_url": image_data_url})

    item_msg = {
        "type": "conversation.item.create",
        "item": {
            "type": "message",
            "role": "user",
            "content": content,
        },
    }
    try:
        await openai_ws.send(json.dumps(item_msg))
        await openai_ws.send(json.dumps({"type": "response.create"}))
        print(f"[realtime] Vision frame injected for user={user_id} (prompt={'yes' if prompt_text else 'default'})")
        return True
    except Exception as e:
        print(f"[realtime] inject_vision_message error: {e}")
        return False


class ServerSpeakers:
    """Lazy wrapper around an aplay subprocess that consumes PCM16 24kHz mono.

    Spawns aplay only when the first audio chunk arrives in local mode, and
    tears it down on stop() or when the session ends. write() is fire-and-forget:
    if the pipe breaks we drop the chunk and reset so the next chunk respawns.
    """

    def __init__(self) -> None:
        self.proc: asyncio.subprocess.Process | None = None
        self._lock = asyncio.Lock()

    async def _ensure_started(self) -> None:
        if self.proc is not None and self.proc.returncode is None:
            return
        try:
            self.proc = await asyncio.create_subprocess_exec(
                APLAY_BIN, "-q", "-f", "S16_LE", "-r", "24000", "-c", "1", "-t", "raw",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            print("[realtime] aplay started (local playback)")
        except FileNotFoundError:
            print(f"[realtime] aplay not found at {APLAY_BIN}; cannot play locally")
            self.proc = None
        except Exception as e:
            print(f"[realtime] aplay spawn error: {e}")
            self.proc = None

    async def write(self, pcm_bytes: bytes) -> None:
        if not pcm_bytes:
            return
        async with self._lock:
            await self._ensure_started()
            if self.proc is None or self.proc.stdin is None:
                return
            try:
                self.proc.stdin.write(pcm_bytes)
                await self.proc.stdin.drain()
            except (BrokenPipeError, ConnectionResetError, OSError) as e:
                print(f"[realtime] aplay pipe broken: {e}; will respawn next chunk")
                try:
                    self.proc.kill()
                except Exception:
                    pass
                self.proc = None

    async def stop(self) -> None:
        async with self._lock:
            if self.proc is None:
                return
            try:
                if self.proc.stdin is not None:
                    self.proc.stdin.close()
            except Exception:
                pass
            try:
                await asyncio.wait_for(self.proc.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                try:
                    self.proc.kill()
                except Exception:
                    pass
            self.proc = None
            print("[realtime] aplay stopped")


def build_instructions(user_id: str) -> str:
    """System prompt for the Realtime session: core identity + per-session ctx."""
    user = get_user(user_id) if user_id else None
    if user and user.get("is_shared_space"):
        session_ctx = (
            f"This is a SHARED conversation ({user['name']}). Multiple team members "
            f"may be present in the room. Address the group in plural (e.g. \"hi team\") "
            f"and don't assume which person is speaking unless someone identifies themselves."
        )
    elif user:
        role_part = f" ({user['role']})" if user.get("role") else ""
        session_ctx = (
            f"You are talking with {user['name']}{role_part}. It's a private "
            f"conversation. Address {user['name']} by name when natural."
        )
    else:
        session_ctx = (
            "We don't know who is talking with you. Ask their name early before "
            "assuming context."
        )
    return f"{config.system_prompt_core()}\n\n═══ SESSION CONTEXT ═══\n{session_ctx}\n"


REALTIME_TOOLS = [
    {
        "type": "function",
        "name": "call_agent",
        "description": (
            "Invoke the external agent for tasks that require live data, "
            "real-world action, persistent memory, or any integration "
            "(calendar, email, files, web search, automations, scheduled tasks)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "Self-contained query for the agent. Include relevant "
                        "context from the conversation."
                    ),
                },
            },
            "required": ["query"],
        },
    }
] if config.agent_enabled() else []


async def realtime_proxy(websocket: WebSocket, user_id: str = "", conversation_id: str = None):
    """Proxy between browser WebSocket and OpenAI Realtime API."""
    await websocket.accept()

    user_record = get_user(user_id) or {}
    user_display_name = user_record.get("name") or (user_id.capitalize() if user_id else "User")
    user_display_role = user_record.get("role") or ""

    if conversation_id:
        conv = get_conversation(conversation_id)
        if not conv:
            conv = create_conversation(user_id)
            conversation_id = conv["id"]
    else:
        conv = create_conversation(user_id)
        conversation_id = conv["id"]

    assistant_text_buffer = ""

    # Playback mode: "private" (browser) or "local" (server speakers).
    playback_mode = "private"
    server_speakers = ServerSpeakers()

    # Vision mode: True while the user is in the "VISION + VOICE" mode. When on,
    # we disable server_vad's create_response so the backend (not OpenAI) decides
    # when to fire response.create — that lets us inject the camera frame on
    # speech_stopped and only then ask for the answer.
    vision_mode = False

    # Half-duplex in LOCAL. While the server speakers are playing the
    # assistant (or within the post-audio tail), we drop mic chunks BEFORE
    # forwarding them to OpenAI — so acoustic echo never reaches the model.
    #
    # KEY: `output_audio.done` means OpenAI finished SENDING audio, not that
    # aplay finished PLAYING it. For long audio (6-8s), bytes arrive in
    # ~500ms but aplay takes the real 6-8s. So tail = (audio_duration -
    # elapsed_since_first_chunk) + safety, instead of a fixed value.
    local_playback_active = False
    local_unmute_task: asyncio.Task | None = None
    playback_bytes_written = 0
    playback_first_chunk_time: float | None = None
    LOCAL_TAIL_SAFETY_S = float(os.getenv("LOCAL_TAIL_SAFETY_S", "1.0"))
    LOCAL_TAIL_MAX_S = float(os.getenv("LOCAL_TAIL_MAX_S", "30.0"))

    pending_tasks: set[asyncio.Task] = set()
    def _spawn_bg(coro):
        t = asyncio.create_task(coro)
        pending_tasks.add(t)
        t.add_done_callback(pending_tasks.discard)
        return t

    openai_headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "OpenAI-Safety-Identifier": f"companion-{user_id}",
    }

    try:
        async with websockets.connect(
            OPENAI_REALTIME_URL,
            additional_headers=openai_headers,
        ) as openai_ws:
            session_update = {
                "type": "session.update",
                "session": {
                    "type": "realtime",
                    "model": REALTIME_MODEL,
                    "output_modalities": ["audio"],
                    "instructions": build_instructions(user_id),
                    "audio": {
                        "input": {
                            "format": {"type": "audio/pcm", "rate": 24000},
                            "transcription": {
                                "model": "whisper-1",
                                "language": config.default_language(),
                            },
                            "turn_detection": turn_detection_for(playback_mode, vision_mode),
                        },
                        "output": {
                            "format": {"type": "audio/pcm", "rate": 24000},
                            "voice": REALTIME_VOICE,
                            "speed": 1.0,
                        },
                    },
                    "tools": REALTIME_TOOLS,
                    "tool_choice": "auto" if REALTIME_TOOLS else "none",
                },
            }
            await openai_ws.send(json.dumps(session_update))

            _register_session(user_id, openai_ws)
            print(f"[realtime] Session configured for user: {user_id}, conv: {conversation_id}")

            async def _run_call_agent(call_id: str, query: str):
                """Background tool runner — keeps the recv loop free during the wait."""
                print(f"[realtime] call_agent (bg): {query[:80]}")
                try:
                    await websocket.send_text(json.dumps({
                        "type": "companion.tool_started",
                        "tool": "call_agent",
                        "query": query,
                    }))
                except Exception as e:
                    print(f"[realtime] tool_started notify error: {e}")

                try:
                    result = await call_agent_for_voice(
                        query,
                        user_name=user_display_name,
                        user_id=user_id,
                        user_role=user_display_role,
                    )
                except asyncio.CancelledError:
                    print("[realtime] call_agent cancelled")
                    raise
                except Exception as e:
                    print(f"[realtime] call_agent exception: {e}")
                    result = "There was a problem reaching the agent."
                finally:
                    try:
                        await websocket.send_text(json.dumps({
                            "type": "companion.tool_finished",
                            "tool": "call_agent",
                        }))
                    except Exception as e:
                        print(f"[realtime] tool_finished notify error: {e}")

                function_output = {
                    "type": "conversation.item.create",
                    "item": {
                        "type": "function_call_output",
                        "call_id": call_id,
                        "output": json.dumps({"answer": result}, ensure_ascii=False),
                    },
                }
                try:
                    await openai_ws.send(json.dumps(function_output))
                    await openai_ws.send(json.dumps({"type": "response.create"}))
                except Exception as e:
                    print(f"[realtime] send function_output error: {e}")

            async def browser_to_openai():
                """Forward browser messages to OpenAI. Intercept companion control messages."""
                nonlocal playback_mode, local_playback_active, local_unmute_task
                nonlocal playback_bytes_written, playback_first_chunk_time
                nonlocal vision_mode
                audio_buffers_received = 0
                try:
                    while True:
                        raw_data = await websocket.receive_text()
                        msg = json.loads(raw_data)
                        msg_type = msg.get("type", "")

                        if msg_type == "companion.playback_mode":
                            new_mode = msg.get("mode", "private")
                            if new_mode not in ("private", "local"):
                                new_mode = "private"
                            if new_mode != playback_mode:
                                print(f"[realtime] playback_mode: {playback_mode} -> {new_mode}")
                                playback_mode = new_mode
                                if new_mode == "private":
                                    await server_speakers.stop()
                                    local_playback_active = False
                                    if local_unmute_task is not None and not local_unmute_task.done():
                                        local_unmute_task.cancel()
                                    local_unmute_task = None
                                    playback_bytes_written = 0
                                    playback_first_chunk_time = None
                                # GA requires session.type on EVERY session.update
                                try:
                                    await openai_ws.send(json.dumps({
                                        "type": "session.update",
                                        "session": {
                                            "type": "realtime",
                                            "audio": {"input": {
                                                "turn_detection": turn_detection_for(new_mode),
                                            }},
                                        },
                                    }))
                                    print(f"[realtime] VAD re-tuned for {new_mode}")
                                except Exception as e:
                                    print(f"[realtime] VAD retune error: {e}")
                            continue

                        if msg_type == "companion.vision_mode":
                            new_vision = bool(msg.get("enabled", False))
                            if new_vision != vision_mode:
                                print(f"[realtime] vision_mode: {vision_mode} -> {new_vision}")
                                vision_mode = new_vision
                                try:
                                    await openai_ws.send(json.dumps({
                                        "type": "session.update",
                                        "session": {
                                            "type": "realtime",
                                            "audio": {"input": {
                                                "turn_detection": turn_detection_for(playback_mode, vision_mode),
                                            }},
                                        },
                                    }))
                                    print(f"[realtime] VAD re-tuned (vision={vision_mode})")
                                except Exception as e:
                                    print(f"[realtime] VAD retune error: {e}")
                            continue

                        if msg_type == "input_audio_buffer.append":
                            audio_buffers_received += 1
                            if audio_buffers_received == 1:
                                print(f"[realtime] First audio buffer received from browser ({len(msg.get('audio',''))} chars base64)")
                            if audio_buffers_received % 100 == 0:
                                print(f"[realtime] Audio buffers received: {audio_buffers_received}")
                            if playback_mode == "local" and local_playback_active:
                                continue
                            await openai_ws.send(raw_data)
                        else:
                            print(f"[realtime] Browser -> OpenAI: {msg_type}")
                            await openai_ws.send(raw_data)

                except WebSocketDisconnect:
                    print(f"[realtime] Browser disconnected normally")
                except Exception as e:
                    print(f"[realtime] Browser error: {e}")

            async def openai_to_browser():
                """Forward OpenAI messages to browser, intercept function calls, persist to DB."""
                nonlocal assistant_text_buffer, local_playback_active, local_unmute_task
                nonlocal playback_bytes_written, playback_first_chunk_time

                try:
                    async for raw_msg in openai_ws:
                        msg = json.loads(raw_msg)
                        msg_type = msg.get("type", "")

                        noisy = (
                            "response.output_audio.delta",
                            "response.output_audio_transcript.delta",
                            "response.audio.delta",
                            "response.audio_transcript.delta",
                            "input_audio_buffer.speech_started",
                            "input_audio_buffer.speech_stopped",
                        )
                        if msg_type not in noisy:
                            print(f"[realtime] OpenAI -> Browser: {msg_type}")

                        if msg_type == "conversation.item.input_audio_transcription.completed":
                            transcript = msg.get("transcript", "")
                            if transcript and conversation_id:
                                try:
                                    add_message(conversation_id, "user", transcript)
                                    touch_conversation(conversation_id)
                                    print(f"[realtime] Saved user msg: {transcript[:60]}...")
                                except Exception as e:
                                    print(f"[realtime] DB error (user msg): {e}")

                        if (
                            playback_mode == "local"
                            and msg_type in ("response.output_audio.delta", "response.audio.delta")
                        ):
                            local_playback_active = True
                            if local_unmute_task is not None and not local_unmute_task.done():
                                local_unmute_task.cancel()
                            local_unmute_task = None

                            delta_b64 = msg.get("delta", "")
                            if delta_b64:
                                try:
                                    pcm_bytes = base64.b64decode(delta_b64)
                                    if playback_first_chunk_time is None:
                                        playback_first_chunk_time = time.time()
                                    playback_bytes_written += len(pcm_bytes)
                                    await server_speakers.write(pcm_bytes)
                                except Exception as e:
                                    print(f"[realtime] local playback error: {e}")

                        if (
                            playback_mode == "local"
                            and msg_type in ("response.output_audio.done", "response.audio.done")
                        ):
                            if local_unmute_task is not None and not local_unmute_task.done():
                                local_unmute_task.cancel()

                            audio_duration_s = playback_bytes_written / 48000.0
                            elapsed_s = (
                                time.time() - playback_first_chunk_time
                                if playback_first_chunk_time is not None else 0.0
                            )
                            drain_remaining = max(0.0, audio_duration_s - elapsed_s)
                            tail_total = min(
                                LOCAL_TAIL_MAX_S,
                                drain_remaining + LOCAL_TAIL_SAFETY_S,
                            )
                            tail_secs = tail_total
                            audio_dur_secs = audio_duration_s
                            elapsed_secs = elapsed_s

                            async def _release_local_playback():
                                try:
                                    await asyncio.sleep(tail_secs)
                                except asyncio.CancelledError:
                                    return
                                nonlocal local_playback_active
                                nonlocal playback_bytes_written, playback_first_chunk_time
                                local_playback_active = False
                                playback_bytes_written = 0
                                playback_first_chunk_time = None
                                try:
                                    await openai_ws.send(json.dumps({
                                        "type": "input_audio_buffer.clear",
                                    }))
                                    print(
                                        f"[realtime] LOCAL playback released "
                                        f"(audio={audio_dur_secs:.2f}s, elapsed={elapsed_secs:.2f}s, "
                                        f"tail={tail_secs:.2f}s), buffer cleared"
                                    )
                                except Exception as e:
                                    print(f"[realtime] LOCAL release send error: {e}")

                            local_unmute_task = _spawn_bg(_release_local_playback())

                        if msg_type in ("response.output_audio_transcript.delta", "response.audio_transcript.delta"):
                            assistant_text_buffer += msg.get("delta", "")

                        if msg_type in ("response.output_audio_transcript.done", "response.audio_transcript.done"):
                            if assistant_text_buffer.strip() and conversation_id:
                                try:
                                    add_message(conversation_id, "assistant", assistant_text_buffer.strip())
                                    touch_conversation(conversation_id)
                                    print(f"[realtime] Saved assistant msg: {assistant_text_buffer[:60]}...")
                                except Exception as e:
                                    print(f"[realtime] DB error (assistant msg): {e}")
                            assistant_text_buffer = ""

                        if msg_type == "response.done" and conversation_id:
                            try:
                                touch_conversation(conversation_id)
                            except Exception as e:
                                print(f"[realtime] DB error (touch): {e}")

                        if msg_type in (
                            "response.function_call_arguments.done",
                            "response.output_function_call_arguments.done",
                        ):
                            func_name = msg.get("name", "")
                            call_id = msg.get("call_id", "")

                            if func_name == "call_agent":
                                try:
                                    args = json.loads(msg.get("arguments", "{}"))
                                except json.JSONDecodeError:
                                    args = {}
                                query = args.get("query", "")
                                # Spawn the long-running tool call as a background
                                # task. Awaiting it here would block the recv loop
                                # and OpenAI's keepalive would kill the WS.
                                _spawn_bg(_run_call_agent(call_id, query))
                            continue

                        if msg_type == "error":
                            error_detail = msg.get("error", {})
                            print(f"[realtime] OpenAI error: type={error_detail.get('type')}, code={error_detail.get('code')}, message={error_detail.get('message')}")
                            await websocket.send_text(raw_msg)
                            continue

                        await websocket.send_text(raw_msg)

                except (websockets.exceptions.ConnectionClosed, Exception) as e:
                    print(f"[realtime] OpenAI disconnected: {e}")

            await websocket.send_text(json.dumps({
                "type": "realtime.conversation_ready",
                "conversation_id": conversation_id,
            }))

            await asyncio.gather(
                browser_to_openai(),
                openai_to_browser(),
            )

    except websockets.exceptions.ConnectionClosed as e:
        print(f"[realtime] OpenAI connection closed: {e}")
    except Exception as e:
        print(f"[realtime] Error: {e}")
        import traceback
        traceback.print_exc()
        try:
            await websocket.send_text(json.dumps({
                "type": "error",
                "message": str(e),
            }))
        except Exception:
            pass
    finally:
        try:
            _unregister_session(user_id, openai_ws)  # type: ignore[name-defined]
        except Exception:
            pass
        for t in list(pending_tasks):
            if not t.done():
                t.cancel()
        if pending_tasks:
            try:
                await asyncio.gather(*pending_tasks, return_exceptions=True)
            except Exception:
                pass
        try:
            await server_speakers.stop()
        except Exception as e:
            print(f"[realtime] server_speakers cleanup error: {e}")
        if local_unmute_task is not None and not local_unmute_task.done():
            local_unmute_task.cancel()
        try:
            await websocket.close()
        except Exception:
            pass
