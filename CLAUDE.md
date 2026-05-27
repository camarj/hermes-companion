# hermes-companion

Voice + chat shell on OpenAI Realtime with a pluggable external agent. FastAPI backend, SQLite, Vite + React + Tailwind v4 frontend (built to `frontend/static/next/`, served at `/`).

## Bash commands you'll need

- **Setup a fresh clone:** `python3 -m venv venv && ./venv/bin/pip install -r backend/requirements.txt && cp config.yaml.example config.yaml && cp .env.example .env`
- **Dev deps (tests):** `./venv/bin/pip install -r backend/requirements-dev.txt` and `pnpm --dir frontend install`
- **Run the server:** `./start.sh` (port 8000; HTTPS if `./certs/*.crt`+`.key` are present)
- **Health smoke:** `curl http://localhost:8000/api/health` → `{"status":"ok",...}`
- **Backend tests:** `./venv/bin/pytest -q`
- **Frontend tests:** `pnpm --dir frontend test --run`
- **E2E tests:** `pnpm --dir frontend exec playwright install chromium` (first time) then `pnpm --dir frontend test:e2e`
- **Optional vision:** `./install_face_recognition.sh` (5-10 min dlib compile)

Voice / Realtime can't be unit-tested today — exercise it in a browser via the `/verify` skill and say so explicitly when you ship voice work. Everything else follows the SDD workflow below.

## SDD workflow

Specification-driven development. Every behavioural change starts as an acceptance criterion in [`docs/acceptance-criteria.md`](./docs/acceptance-criteria.md), and the test that exercises the criterion is written **before** the code that satisfies it (red → green → refactor).

**Stack:** `pytest` + `pytest-asyncio` (backend, tests under `tests/backend/`), `Vitest` + Testing Library (frontend, co-located in `src/**/__tests__/`), `Playwright` (E2E, under `tests/e2e/`). Voice / Realtime is the standing exception — manual `/verify` only.

**For Claude:** before editing a backend module or React component, open `docs/acceptance-criteria.md` and find the AC you're working under. If none exists, write one in the same branch first and confirm with the user before coding.

## What's editable without touching code

`config.yaml` (assistant name, company, team, agent command, prompt overrides) and `.env` (OpenAI key, model overrides, TLS paths). Never hardcode identity, prompts, or team data in Python — it goes in `config.yaml`.

## Code style

- **No new deps without discussion.** Keep `requirements.txt` and `frontend/package.json` lean.
- **Frontend lives in `frontend/src/` (React + TS).** Build output goes to `frontend/static/next/`. The Inteliside editorial CSS tokens live in `frontend/src/index.css` — keep them inside `@layer base` so Tailwind utilities still win.
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

For details on the Realtime event flow, the `call_agent` subprocess contract, and the vision frame injection bridge — load `.claude/skills/architecture/SKILL.md` on demand. Don't pull it into context unless you're modifying voice/realtime code.

## Repo etiquette

- Branches: `feature/<name>`, `fix/<name>`, `docs/<name>`.
- One logical change per commit; subject line under 70 chars.
- See @CONTRIBUTING.md for the full PR flow.
- Never commit `config.yaml`, `.env`, `certs/`, or `*.db` (already gitignored).
