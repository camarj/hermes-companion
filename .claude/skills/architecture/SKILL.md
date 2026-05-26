---
name: architecture
description: Deep architectural details of hermes-companion — Realtime WebSocket event flow, the call_agent subprocess contract, half-duplex echo suppression in LOCAL playback mode, vision frame injection, conversation persistence, and the cookie auth model. Load this when modifying backend/realtime.py, backend/agent_bridge.py, or any voice/audio code path.
---

# hermes-companion — architecture deep-dive

## Realtime WebSocket flow

The browser opens a WS to `/api/realtime`. The backend (`backend/realtime.py`) connects to OpenAI's `wss://api.openai.com/v1/realtime?model=gpt-realtime-2` and runs two `asyncio` tasks in parallel:

- **`browser_to_openai`** — forwards every browser message to OpenAI, but intercepts custom `companion.*` control messages (playback mode toggle, vision mode toggle) without forwarding them. Also enforces the half-duplex mic filter in LOCAL mode (see below).
- **`openai_to_browser`** — forwards every OpenAI event to the browser. It intercepts:
  - `response.function_call_arguments.done` for `call_agent` (runs the agent subprocess as a background task; **never await in the recv loop**).
  - `conversation.item.input_audio_transcription.completed` → persists the user transcript to SQLite.
  - `response.output_audio_transcript.delta` / `.done` → accumulates and flushes the assistant transcript.
  - `response.output_audio.delta` → pipes raw PCM16 to `aplay` when in LOCAL mode.

Session config is sent on connect via `session.update` with `instructions: build_instructions(user_id)`, `turn_detection: server_vad`, audio I/O format, voice/speed. **GA requires `session.type: "realtime"` on every `session.update`, including partial ones** — missing it is silently ignored by OpenAI.

## The `call_agent` subprocess contract

When the Realtime model emits `call_agent`, the backend (`backend/agent_bridge.py`):

1. Sends `companion.tool_started` to the browser (UI shows "Querying $LABEL…" and auto-mutes the mic).
2. Resolves the configured `agent.command` argv list, substituting the literal strings `{query}` and `{user_id}`.
3. Spawns the subprocess with three identity env vars: `AGENT_REQUESTER_ID`, `AGENT_REQUESTER_NAME`, `AGENT_REQUESTER_ROLE` (in addition to the parent env).
4. Waits up to `agent.timeout_seconds` for stdout.
5. Cleans the answer: strips fenced code blocks; for the voice variant additionally flattens bullets/headings into a single line so TTS doesn't stutter on punctuation.
6. Sends the answer back to OpenAI as `conversation.item.create` with a `function_call_output` item (JSON-stringified `{"answer": "..."}`), then `response.create`.
7. Sends `companion.tool_finished` to the browser.

If `agent.command` is empty/null, the tool is omitted from the session entirely — the model won't see it.

**Why background tasks?** If you `await` the subprocess in the recv loop, the WS keepalive ping/pong stops and OpenAI closes the connection with code 1011 after ~30s. `_spawn_bg` keeps the task tracked so it can be cancelled cleanly on session end.

## Half-duplex echo suppression (LOCAL playback)

In LOCAL mode, the assistant plays through the host's speakers (via `aplay`). The browser's mic picks up that audio and would loop it back to OpenAI, causing self-triggered turns. The mitigation:

1. The first `response.output_audio.delta` flips `local_playback_active = true`. From this moment, `browser_to_openai` drops `input_audio_buffer.append` messages.
2. The same chunk is piped to a server-side `aplay` subprocess (PCM16 mono 24kHz).
3. When `output_audio.done` fires, OpenAI is done **sending** but `aplay` is still **draining** — audio takes 6-8s real time but the bytes arrive in ~500ms.
4. Compute the tail: `max(0, audio_duration - elapsed_since_first_chunk) + LOCAL_TAIL_SAFETY_S` (clamped to `LOCAL_TAIL_MAX_S`). `audio_duration` = `bytes_written / 48000` (24kHz mono PCM16 = 48000 bytes/sec).
5. After the tail, send `input_audio_buffer.clear` to OpenAI to discard any echo bytes that slipped through the mic filter — belt-and-suspenders.

Switching back to PRIVATE mid-session must reset `local_playback_active`, cancel the pending unmute task, and re-tune VAD.

## Vision frame injection

The frontend in VISION mode polls the camera every ~5s. When the user stops speaking (or a known person enters the frame), the frontend POSTs `/api/vision/snapshot` with a `data:image/jpeg;base64,...` URL.

The HTTP handler in `backend/main.py`:

1. Optionally runs `face_recognition.compare_faces` against enrolled embeddings (skipped silently if the library isn't installed). Recognized names are prepended to the prompt as `[System context: in this image: <names>]`.
2. Looks up the user's active OpenAI WebSocket from `_active_sessions` (a per-user dict registered on connect, evicted on disconnect — and evicted only if the entry still points at this socket, so a newer session in another tab isn't accidentally cleared).
3. Sends `conversation.item.create` with `input_text` + `input_image` content parts, then `response.create`.

**Critical:** in VISION mode, `turn_detection.create_response` must be `false`. Otherwise OpenAI auto-responds on `speech_stopped` *before* the image lands, and the response can't reference the frame. The toggle is handled in `realtime.py`'s `companion.vision_mode` interceptor, which sends a partial `session.update`.

## Conversation persistence (SQLite)

`backend/database.py`. WAL mode. Tables:

- **`users`** — seeded from `config.yaml` `team` at first boot. Existing rows are never updated; delete `companion.db` to re-seed. `is_shared_space: 1` means a "meeting" account visible to all logged-in users.
- **`conversations`** — owned by a user_id. Title auto-generated from the first user message (truncated to 60 chars). Access control: owner can read/write; if owner is a shared-space user, any logged-in user can read/write.
- **`messages`** — FK with cascade delete. Roles: `user`, `assistant`, `system`. Inserted from:
  - User turns: `conversation.item.input_audio_transcription.completed` in voice mode, or directly in text chat.
  - Assistant turns: accumulated from `response.output_audio_transcript.delta`, flushed on `.done`.
- **`known_faces`** — face embeddings (128-D float64 BLOBs) for the optional vision recognition. Multiple rows per name are allowed for multi-angle matching.

## Cookie auth model

Simple — no auth provider. Cookie `companion_user` maps to a user_id; the user_id must exist in the `users` table. The WS proxy validates the cookie before connecting upstream; query params are explicitly ignored to prevent spoofing.

This is fine for personal/team use on a trusted network. For public deployments, put a real auth proxy (oauth2-proxy, Cloudflare Access, etc.) in front.

## Where customization seams live

| What you want to change | Where to change it |
|---|---|
| Assistant name, company, team, prompt | `config.yaml` |
| External agent command | `config.yaml` → `agent.command` |
| OpenAI key, model, voice, VAD tuning | `.env` |
| TLS certs | `./certs/*.crt` + matching `.key`, or `COMPANION_CERT`/`COMPANION_KEY` env |
| Database location | `backend/database.py` → `DB_PATH` (currently fixed; not env-configurable) |

If you're tempted to hardcode a name, prompt fragment, or behavior in Python — stop and add it to `config.yaml` instead.
