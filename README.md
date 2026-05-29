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
a question needs live data, scheduling, or any real-world action, the backend
routes the turn to an **agent backend** — a Hermes process spoken to over ACP
(Agent Client Protocol). The answer streams back as the tool result.

Each conversation is bound to an *agent instance*; instances are declared in
`config.yaml` under `agents:`. An instance's `transport` decides how it's
reached:

```yaml
agents:
  - id: local-default
    label: "Hermes (local)"
    transport: local-acp        # spawns `hermes acp` as a subprocess

  - id: vps-prod
    label: "Hermes VPS"
    transport: remote-acp        # talks to a remote host over a WS bridge
    transport_config:
      url: "wss://my-host.example.com/api/host/acp"
      token: "env:VPS_HOST_TOKEN"
```

If you omit `agents:` entirely, a legacy single `agent:` block is auto-migrated
to one `local-default` instance — so existing setups keep working unchanged.
Conversations with no agent bound fall back to the local Hermes.

Identity flows to the agent via three env vars (local) or `X-Requester-*`
headers (remote): `AGENT_REQUESTER_ID`, `AGENT_REQUESTER_NAME`,
`AGENT_REQUESTER_ROLE`.

Want a different agent, or to wire your own (an OpenAI Agents SDK app, a CrewAI
flow)? That means implementing an `AgentBackend` subclass — the one
polymorphism seam. The `/add-agent-backend` Claude skill walks both paths
(register another Hermes vs. implement a new backend type).

### Deploy a remote Hermes

To serve one hermes-companion's agent from another machine (a VPS, a Tailscale
node), run the remote box in **host mode** — it exposes only the `/api/host/*`
bridge and nothing client-facing.

**One command (on the Hermes box):** `install-host.sh` pulls the repo, builds a
venv, installs the backend deps, seeds a bearer token, and prints the token,
the `wss://…/api/host/acp` URL, and the launch command:

```bash
curl -sSL https://raw.githubusercontent.com/camarj/hermes-companion/main/install-host.sh \
  | bash -s -- --label vps-prod --host my-host.example.com --port 443
```

It provisions the **sidecar only** — `hermes` must already be installed on the
box — and it does not start the server; copy the printed `HERMES_COMPANION_MODE=host`
command to launch. The manual equivalent, step by step:

1. **On the host**, declare one or more bearer tokens in `config.yaml`:

   ```yaml
   host_tokens:
     - token: "a-long-unguessable-random-string"   # 32+ chars
       label: "vps-prod"
   ```

2. **Start the host with host mode on:**

   ```bash
   HERMES_COMPANION_MODE=host ./start.sh
   ```

   In this mode every route except `/api/host/*` and `/api/health` returns 404
   — there is no UI, just the bridge. The host needs `hermes acp` installed and
   on PATH; it runs the agent locally and relays turns over the WebSocket.

3. **On the client**, point a `remote-acp` agent at the host's `/api/host/acp`
   WebSocket and supply the matching token (prefer an `env:` reference so the
   secret stays out of `config.yaml`):

   ```yaml
   agents:
     - id: vps-prod
       label: "Hermes VPS"
       transport: remote-acp
       transport_config:
         url: "wss://my-host.example.com/api/host/acp"
         token: "env:VPS_HOST_TOKEN"
   ```

   Use `wss://` (TLS) for anything off `localhost`. The bridge also backs the
   read-only inspection endpoints (skills / MCP / tools / config), frame upload
   for vision, and the system-prompt override.

To disable the agent tool entirely, leave `agents:` empty (and drop the legacy
`agent:` block). The assistant then runs voice-only, with no live data.

## Personalize

Everything user-facing is in **`config.yaml`** at the repo root:

| Field | What it controls |
|---|---|
| `assistant_name` | The name the model uses for itself; appears in the UI title and login screen |
| `company_name` / `company_url` | Optional context injected into the system prompt + UI eyebrow |
| `default_language` | ISO code for the Realtime transcriber and default greetings |
| `personality` | Free-form blurb appended to the system prompt |
| `team` | Login users (id, name, role, optional `shared_space: true`) |
| `agents[]` | Agent instances: `id`, `label`, `transport` (`local-acp`/`remote-acp`), `transport_config`, `system_prompt_override` |
| `host_tokens[]` | Bearer tokens that authenticate remote clients when this box runs in host mode |
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
                                    ├─ AgentBackend.stream(query) ──> ACP (local or remote)
                                    │
   audio.delta      <──      forward                   <──     audio.delta
   transcripts      <──      forward + SQLite          <──     transcript.delta
```

| File | What it does |
|---|---|
| `backend/main.py` | FastAPI app: auth cookie, CRUD, text chat (SSE), agent registry + host endpoints |
| `backend/realtime.py` | WebSocket proxy to OpenAI Realtime — VAD config, vision frame injection |
| `backend/agent_bridge.py` | Facade that resolves the conversation's `AgentBackend` and streams its turn |
| `backend/agents/` | `AgentBackend` ABC + `LocalAcpBackend` / `RemoteAcpBackend` over ACP |
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
