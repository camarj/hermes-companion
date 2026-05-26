---
name: setup
description: Bootstrap a fresh clone of hermes-companion (Python venv, dependencies, config.yaml, .env, OpenAI key). Use whenever the user is installing the project for the first time or after deleting the venv. Walks them through each step interactively.
disable-model-invocation: true
---

# Setting up hermes-companion

A fresh clone needs four things to boot: a Python 3.11+ venv, dependencies installed, a `config.yaml`, and an OpenAI API key in `.env`.

## Step 1 — verify Python

```bash
python3 --version
```

Require 3.11 or newer. If the system `python3` is older, look for `python3.11` or `python3.12` explicitly and use that throughout.

## Step 2 — create the venv

```bash
python3 -m venv venv
```

If the `venv/bin/python3` symlink is broken (some systems link it to `/usr/bin/python3` regardless of which interpreter created the venv), prefer the version-suffixed binary:

```bash
./venv/bin/python3.11 --version
```

## Step 3 — install dependencies

```bash
./venv/bin/pip install -r backend/requirements.txt
```

Don't install `face_recognition` here — it's optional and slow to compile. Save that for after the user has the basic server running.

## Step 4 — seed config files

```bash
[ -f config.yaml ] || cp config.yaml.example config.yaml
[ -f .env ] || cp .env.example .env
```

Then walk the user through editing `config.yaml`:
- `assistant_name`, `company_name` — what shows up in the UI title and login screen
- `team` — list of users for the login screen. Add an entry per person; mark `shared_space: true` for any "meeting" account
- `agent.command` — the external CLI that handles live-data tool calls. Default points at `hermes -z {query} --yolo`. If the user doesn't have Hermes, either point it at their own agent (see [[add-agent-backend]]) or set `command: []` to disable the tool entirely

And `.env`:
- `OPENAI_API_KEY=sk-...` — required. Get one at https://platform.openai.com/api-keys

## Step 5 — smoke test

```bash
./start.sh
```

In another terminal:

```bash
curl http://localhost:8000/api/health
curl http://localhost:8000/api/config
curl http://localhost:8000/api/users
```

Expected: `{"status":"ok","llm_model":"gpt-4o-mini","realtime":true,"agent_enabled":true}` and the team members from `config.yaml`.

Open `http://localhost:8000/` in a browser to confirm the login screen renders with the assistant name and team. If the user is on a remote host, they'll need HTTPS for microphone access — drop a cert pair in `./certs/` (`*.crt` + matching `*.key`) and restart.

## Optional — face recognition

If the user wants the assistant to greet known people by name in vision mode:

```bash
./install_face_recognition.sh
```

Takes 5-10 minutes on CPUs without AVX (compiles dlib from source). After it finishes and the server is restarted, the Settings → "Known people" panel becomes functional.

## Done

Tell the user the project is running, point them at the README for the full feature list, and remind them that `config.yaml` and `.env` are gitignored (so their personalization is local-only).
