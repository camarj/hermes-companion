# hermes-companion

A voice + chat shell on top of the **OpenAI Realtime API** with a pluggable
external "agent" backend. Casual questions are answered straight from the
Realtime model with near-zero latency; anything that needs real data, memory,
or actions is routed to whatever agent CLI you plug in (Hermes by default, but
any subprocess works).

> Open source, MIT. Built so you can run your own private voice assistant for
> your team without forking out for a SaaS chat tool or stitching together
> half a dozen libraries.

## Features

- **OpenAI Realtime voice** (`gpt-realtime-2`) — sub-second mic-to-speaker
  latency, server-side VAD, configurable voice.
- **Pluggable agent backend** — one tool, `call_agent`, runs any subprocess
  you configure. Default points at [Hermes](https://github.com/) but works
  with any CLI that takes a query and prints an answer.
- **Vision mode (optional)** — webcam frames injected into the Realtime
  session; optional local face recognition so the assistant greets people by
  name. 100% local — frames go to OpenAI only when you're in vision mode, no
  faces leave the box for recognition.
- **Multi-user** — pick from a configurable team on the login screen. Mark
  one entry as `shared_space: true` for a "meeting" account everyone shares.
- **SQLite persistence** — conversations + messages stored locally.
- **Text chat fallback** — full chat UI with SSE streaming when you don't
  want voice.
- **Single-file frontend** — no Node, no bundler, just one `index.html`.

## Quick start

```bash
git clone https://github.com/YOUR-USERNAME/hermes-companion.git
cd hermes-companion

python3 -m venv venv
./venv/bin/pip install -r backend/requirements.txt

cp config.yaml.example config.yaml      # edit assistant name, team, agent command
cp .env.example .env                    # add your OPENAI_API_KEY

./start.sh                              # listens on :8000 by default
```

Open `http://localhost:8000`. Pick a team member from the login screen and
start chatting. Toggle `VOICE` (or `VISION`) at the top to switch from text
to live voice.

> Browsers require HTTPS for microphone access on anything other than
> `localhost`. See [HTTPS](#https) below.

## How the agent plug-in works

The Realtime model has exactly one tool, `call_agent`. When the model decides
a question needs live data, scheduling, or any kind of real-world action, it
emits a function call with a `query` argument. The backend runs your
configured command as a subprocess and pipes the agent's stdout back as the
tool result.

In `config.yaml`:

```yaml
agent:
  label: "Hermes"               # shown in the UI ("Querying Hermes…")
  command:                      # argv list — {query} and {user_id} get substituted
    - hermes
    - -z
    - "{query}"
    - --yolo
  timeout_seconds: 180
  description: >
    Hermes has access to live integrations (calendar, email, files, web
    search, scheduled tasks, persistent memory). Use it whenever the user
    asks about real data or wants something done.
```

Want to use something other than Hermes? Anything that reads a query from
argv and writes the answer to stdout works:

```yaml
# Plain Python script
agent:
  command: ["python3", "/path/to/my_agent.py", "{query}"]

# Bash script
agent:
  command: ["./scripts/agent.sh", "{query}"]

# An OpenAI Agents SDK app, CrewAI flow, etc. — wrap it in a CLI and point here.
```

The subprocess gets three env vars so it knows who's asking:
`AGENT_REQUESTER_ID`, `AGENT_REQUESTER_NAME`, `AGENT_REQUESTER_ROLE`.

If you set `agent.command:` to an empty list, the tool is disabled and the
assistant runs in voice-only mode (no live data, no actions).

## Personalize

Everything user-facing is in **`config.yaml`** at the repo root:

| Field | What it controls |
|---|---|
| `assistant_name` | The name the model uses for itself; appears in the UI title and login screen |
| `company_name` / `company_url` | Optional context injected into the system prompt + UI eyebrow |
| `default_language` | ISO code for the Realtime transcriber and default greetings |
| `personality` | Free-form blurb appended to the system prompt |
| `team` | Login users (id, name, role, optional `shared_space: true`) |
| `agent.*` | External agent command, label, timeout, description |
| `system_prompt` *(optional)* | Replace the entire default prompt if you want full control |

The default system prompt has sensible routing rules (DIRECT mode vs AGENT
mode). Override `system_prompt:` directly if you'd rather write the whole
thing yourself.

## Architecture

```
   Browser                   Backend (FastAPI)         OpenAI Realtime
   ───────                   ─────────────────         ───────────────
   mic 24kHz PCM16   ──>     WS /api/realtime    ──>   wss://api.openai.com
                                    │                          │
                                    │  intercepts tool_call    │
                                    ├─ subprocess(your-agent ─ {query}) ──> stdout
                                    │
   audio.delta      <──      forward                   <──     audio.delta
   transcripts      <──      forward + SQLite          <──     transcript.delta
```

| File | What it does |
|---|---|
| `backend/main.py` | FastAPI app: auth cookie, CRUD, text chat (direct agent passthrough via SSE) |
| `backend/realtime.py` | WebSocket proxy to OpenAI Realtime — VAD config, vision frame injection |
| `backend/agent_bridge.py` | Runs your configured `agent.command` as a subprocess |
| `backend/config.py` | Loads `config.yaml`, builds the system prompt |
| `backend/database.py` | SQLite (`companion.db`) — users seeded from config |
| `backend/face_service.py` | Optional face recognition via `face_recognition`/dlib |
| `frontend/src/` | React + Vite app (chat, voice, vision, settings). Built to `frontend/static/next/` and served at `/` |

## Modes

**CHAT** — text only. Every message is a direct passthrough to your configured
agent (no OpenAI in the loop). No mic needed.

**VOICE** — full Realtime. Speak, get audio back. The model can call your
agent mid-turn (it'll utter a brief "one moment" before doing so).

**VISION** — VOICE plus your webcam. Each time you stop speaking, a single
frame is injected into the session as silent context. If `face_recognition`
is installed and you've enrolled known people via Settings → "Known people",
the assistant gets a system-context hint with the recognized names and
greets them.

## HTTPS

Browsers require HTTPS for `getUserMedia` (mic + camera) on anything other
than `http://localhost`. To run on the network (a LAN box, a Tailscale node,
a VPS):

- Drop a cert pair into `./certs/` (any `*.crt` + matching `*.key`). The
  start script picks them up automatically.
- Or set `COMPANION_CERT` / `COMPANION_KEY` to explicit paths.

For Tailscale users: `tailscale cert <hostname>` generates a valid TLS pair
in seconds.

## Face recognition (optional)

The vision mode works without face recognition — it just won't know names.
To enable name-by-face:

```bash
./install_face_recognition.sh
```

This pulls `face_recognition` (and dlib). On CPUs without AVX it compiles
from source — expect 5-10 minutes. Once installed, restart the server and
the Settings → "Known people" panel becomes functional.

## Limits

- **Realtime sessions cap at ~60 min.** OpenAI closes with `session_expired`
  and there's no auto-reconnect implemented — the client shows the error
  and you reconnect manually.
- **Subprocess output is the only return channel from your agent.** No
  streaming partials back to the model — the agent runs, prints, exits. For
  voice this is fine because the model utters a filler while waiting.
- **No auth provider** — the login is a cookie name → user mapping over a
  configured team list. Fine for personal/team use on a trusted network; if
  you expose it to the open internet, put a reverse proxy with real auth in
  front.

## Roadmap

The project is evolving from a single-agent shell into a polymorphic,
multi-agent platform. See [**docs/PRD-multi-agent.md**](./docs/PRD-multi-agent.md)
for the full three-wave vision (multi-Hermes → omniagent → orchestrator)
and the architectural decisions driving it. Wave 1 (multi-Hermes, local +
remote) is currently in implementation.

## Claude Code

This repo ships with [Claude Code](https://claude.com/claude-code) configuration
out of the box: a project [`CLAUDE.md`](./CLAUDE.md) with conventions and
gotchas, plus a [`.claude/`](./.claude) folder with skills (`/setup`, `/dev`,
`/add-agent-backend`, `/architecture`), a `realtime-reviewer` subagent for
voice/audio reviews, and a permission allowlist so common project commands
don't trigger approval prompts. If you don't use Claude Code, you can safely
ignore those files.

## License

MIT — see [LICENSE](./LICENSE).
