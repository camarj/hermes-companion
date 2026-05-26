# hermes-companion

Voice + chat shell on OpenAI Realtime with a pluggable external agent. FastAPI backend, SQLite, single-file vanilla JS frontend (no build step).

## Bash commands you'll need

- **Setup a fresh clone:** `python3 -m venv venv && ./venv/bin/pip install -r backend/requirements.txt && cp config.yaml.example config.yaml && cp .env.example .env`
- **Run the server:** `./start.sh` (port 8000; HTTPS if `./certs/*.crt`+`.key` are present)
- **Smoke test:** `curl http://localhost:8000/api/health` → `{"status":"ok",...}`
- **Optional vision:** `./install_face_recognition.sh` (5-10 min dlib compile)

There are no tests. Backend changes get smoke-tested via the REST endpoints. Voice / Realtime changes can only be verified in a browser — say so explicitly when you ship voice work.

## What's editable without touching code

`config.yaml` (assistant name, company, team, agent command, prompt overrides) and `.env` (OpenAI key, model overrides, TLS paths). Never hardcode identity, prompts, or team data in Python — it goes in `config.yaml`.

## Code style

- **No new deps without discussion.** Keep `requirements.txt` lean.
- **Frontend stays one file** (`frontend/static/index.html`). No bundler, no framework.
- **Default to no comments.** Only add one when the *why* is non-obvious (a hidden constraint, a subtle workaround). Never narrate what the code does.
- Backend↔browser custom events use the `companion.*` prefix. Native OpenAI Realtime events keep their original names.
- Tool name exposed to the model: `call_agent`. Pluggable backend lives in `backend/agent_bridge.py`.

## Gotchas

- **OpenAI Realtime sessions cap at ~60 min.** No auto-reconnect is implemented.
- **`face_recognition` is optional.** `backend/face_service.py` already degrades gracefully — don't add hard imports anywhere else.
- **`session.update` requires `session.type: "realtime"` on EVERY message**, including partial updates (VAD retune, etc). Missing it is silently ignored by OpenAI.
- **Don't `await` long-running work in the recv loop** of `realtime.py`. Spawn it as `asyncio.create_task` and track in `pending_tasks`, or OpenAI's keepalive kills the WS with code 1011.
- **DB file (`backend/companion.db`) is gitignored.** Delete it to re-seed users from `config.yaml`.

## Deeper architecture

For details on the Realtime event flow, the `call_agent` subprocess contract, the half-duplex echo-suppression algorithm in LOCAL playback mode, and the vision frame injection bridge — load `.claude/skills/architecture/SKILL.md` on demand. Don't pull it into context unless you're modifying voice/realtime code.

## Repo etiquette

- Branches: `feature/<name>`, `fix/<name>`, `docs/<name>`.
- One logical change per commit; subject line under 70 chars.
- See @CONTRIBUTING.md for the full PR flow.
- Never commit `config.yaml`, `.env`, `certs/`, or `*.db` (already gitignored).
