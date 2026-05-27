# hermes-companion

Voice + chat shell on OpenAI Realtime with a pluggable external agent. FastAPI backend, SQLite, Vite + React + Tailwind v4 frontend (built to `frontend/static/next/`, served at `/`).

## Bash commands you'll need

- **Setup a fresh clone:** `python3 -m venv venv && ./venv/bin/pip install -r backend/requirements.txt && cp config.yaml.example config.yaml && cp .env.example .env`
- **Run the server:** `./start.sh` (port 8000; HTTPS if `./certs/*.crt`+`.key` are present)
- **Smoke test:** `curl http://localhost:8000/api/health` → `{"status":"ok",...}`
- **Backend tests:** `./venv/bin/pytest -q` (runs unit + integration, excludes E2E)
- **Frontend tests:** `pnpm --dir frontend test --run` (Vitest, jsdom)
- **E2E tests:** `pnpm --dir frontend test:e2e` (Playwright; spawns backend on a free port)
- **Optional vision:** `./install_face_recognition.sh` (5-10 min dlib compile)

Voice / Realtime cannot be unit-tested today — exercise it in a browser via the `/verify` skill and say so explicitly when you ship voice work. See "SDD workflow" below for the discipline that governs everything else.

## What's editable without touching code

`config.yaml` (assistant name, company, team, agent command, prompt overrides) and `.env` (OpenAI key, model overrides, TLS paths). Never hardcode identity, prompts, or team data in Python — it goes in `config.yaml`.

## SDD workflow (mandatory)

Specification-driven development: every behavioural change is described as an acceptance criterion **before** it is implemented, and the criterion is exercised by a failing test before the code that satisfies it is written.

**Source of truth.** The full list of acceptance criteria (AC) lives in `docs/acceptance-criteria.md`. The roadmap that produces those AC is `docs/PRD-multi-agent.md`. Neither file is generated — both are authored and maintained by hand.

**The cycle.** For every AC you touch:

1. **Red.** Write the test the AC describes. Run it. Confirm it fails for the right reason (not for an unrelated import error). Commit the failing test on its own if the work is non-trivial.
2. **Green.** Write the minimum code that makes the test pass. Nothing else. No "while I'm here" cleanups, no anticipatory abstractions.
3. **Refactor.** With the test green, improve names, structure, or duplication. The test must stay green throughout.

**Test stack.**

- Backend: **pytest** + `pytest-asyncio` + FastAPI's `TestClient` (`httpx`). Use sqlite tempfiles for integration tests, never the real `companion.db`.
- Frontend: **Vitest** + `@testing-library/react` + `jsdom`. Component tests live next to the component in `__tests__/`.
- End-to-end: **Playwright**. Specs live in `tests/e2e/`. The runner spawns the backend on a random free port and seeds a tempfile DB.
- Voice / Realtime: **no automation.** Exercised manually via the `/verify` skill. AC for those flows are explicitly tagged "manual /verify" in `docs/acceptance-criteria.md`. This is the only standing exception to the test-first rule.

**Discipline rules.**

- A PR that changes user-observable behaviour and does **not** add or update at least one AC + test is incomplete. Reviewers should reject it.
- When scope changes mid-PR, update `docs/acceptance-criteria.md` in the same PR. AC IDs are append-only; mark obsolete ones, do not silently rewrite history.
- Tests live under `tests/backend/`, `frontend/src/**/__tests__/`, and `tests/e2e/`. The path on each AC's "Owner test file" line is where the test belongs — do not scatter.
- "No new deps without discussion" still applies. The test runners (`pytest`, `vitest`, `@playwright/test`) were added together as the SDD baseline; further test deps need an explicit ask.
- Coverage targets are deliberately not set. Write the tests the AC asks for, no more, no less. Coverage chasing produces noise.

**For Claude specifically.** Before you write or modify a backend module or React component, open `docs/acceptance-criteria.md` and find the AC(s) you're working under. If none exists, write one first (in the same branch, before the code), get user sign-off, then proceed. If the AC is "manual /verify", say so in your end-of-turn summary and follow up with the `/verify` skill.

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
