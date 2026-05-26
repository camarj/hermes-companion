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
- JS: the frontend is intentionally single-file (`frontend/static/index.html`).
  Don't introduce a build step.
- Don't add features behind feature flags — either it's in or it isn't.

## Scope

`hermes-companion` is meant to stay a **thin voice + chat shell** over OpenAI
Realtime, with one pluggable external agent for "real-world" work. Features
that belong in the agent (memory, integrations, scheduling) should live in
whatever you wire up under `agent.command`, not in this repo.

## License

By contributing you agree your changes are released under the MIT license
(see [LICENSE](./LICENSE)).
