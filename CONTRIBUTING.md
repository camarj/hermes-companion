# Contributing

Thanks for your interest! `hermes-companion` is small enough that contributions
are easy to land — here's how to make them painless.

## Quick start (dev)

```bash
git clone https://github.com/YOUR-USERNAME/hermes-companion.git
cd hermes-companion
python3 -m venv venv
./venv/bin/pip install -r backend/requirements.txt
cp config.yaml.example config.yaml      # edit the assistant name, team, agent command
cp .env.example .env                    # add your OPENAI_API_KEY
./start.sh
```

Open `http://localhost:8000` (HTTPS-only mic access? See README → "HTTPS").

## Using Claude Code

This repo ships with [Claude Code](https://claude.com/claude-code) configuration
in [`CLAUDE.md`](./CLAUDE.md) and the [`.claude/`](./.claude) folder. If you
have Claude Code installed, the workflows below work out of the box:

- **`/setup`** — bootstraps a fresh clone (venv, deps, config files, smoke test).
- **`/dev`** — common day-to-day dev tasks (start the server in the background,
  tail logs, hit endpoints).
- **`/add-agent-backend`** — interactive walkthrough for plugging your own CLI
  or service into `call_agent` instead of Hermes.
- **`/architecture`** *(auto-loaded when relevant)* — deep architectural
  knowledge about the Realtime event flow, the agent subprocess contract, the
  and vision frame injection. Claude
  pulls it in when you're modifying voice/audio code.

There's also a `realtime-reviewer` subagent that reviews voice-related diffs for
known correctness pitfalls — invoke it after modifying `backend/realtime.py`:
*"Use the realtime-reviewer subagent to review the diff."*

Permissions are pre-allowlisted for safe project commands (the start script,
the project's venv, localhost curls, read-only git/gh) so you won't get spammed
with approval prompts.

## What to send

- **Bug reports** — open an issue with steps to reproduce and the relevant log
  lines from stdout. Saying "voice mode breaks" is harder to act on than
  "voice mode fails after ~60min with a `session_expired` error".
- **Pull requests** — small, focused diffs land fastest. Open an issue first if
  the change is structural (new modes, new endpoints, etc.).
- **Plug-ins** — sharing how you wired up a non-Hermes agent (an OpenAI Agents
  SDK app, a CrewAI flow, a plain bash script) as a documentation PR is very
  welcome. The `agent.command` mechanism in `config.yaml` is the seam.

## Style

- Python: keep functions small, prefer `asyncio` over threads where the rest of
  the code is async. No new heavy deps without discussion (we keep the base
  `requirements.txt` lean so `pip install` stays fast).
- TS/React: the React app lives in `frontend/src/` (Vite + React 19 +
  Tailwind v4). The build output goes to `frontend/static/next/` and is
  served at `/`.
- Don't add features behind feature flags — either it's in or it isn't.

## SDD / TDD discipline

The project follows specification-driven development:

1. Every user-observable behaviour is described as an **acceptance criterion** in [`docs/acceptance-criteria.md`](./docs/acceptance-criteria.md), mapped back to the [PRD](./docs/PRD-multi-agent.md).
2. The corresponding **test is written before the code** that satisfies it (red → green → refactor).
3. Test stack: `pytest` (backend), `Vitest` (frontend), `Playwright` (E2E). Voice / Realtime is the documented exception — verified manually.

PRs that change behaviour without touching `docs/acceptance-criteria.md` and a corresponding test will be sent back. If your change introduces a new behaviour, add the AC first (it's a one-paragraph diff) and we'll align on it before you write code. See [`CLAUDE.md`](./CLAUDE.md) → "SDD workflow" for the full rule set.

## Scope and direction

The product is evolving from a single-agent shell into a polymorphic,
multi-agent platform. Before proposing a structural change, please read
[**docs/PRD-multi-agent.md**](./docs/PRD-multi-agent.md) — it records the
three-wave roadmap and the architectural decisions that constrain new
work (e.g. ACP as the universal transport, `AgentBackend` as the only
polymorphism seam, no feature flags).

Features that belong inside the agent itself (memory, integrations,
scheduling) should live in whatever you wire up under `agent.command`,
not in this repo.

## License

By contributing you agree your changes are released under the MIT license
(see [LICENSE](./LICENSE)).
