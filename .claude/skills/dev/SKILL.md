---
name: dev
description: Common day-to-day dev tasks for hermes-companion — start/stop the server in the background, tail logs, smoke-test endpoints, verify frontend changes. Use when iterating on backend or frontend code.
disable-model-invocation: true
---

# Development workflow

## Start the server in the background

```bash
cd backend && ../venv/bin/python -m uvicorn main:app --port 8000 --reload > /tmp/companion.log 2>&1 &
echo $! > /tmp/companion.pid
```

Wait for boot before hitting endpoints — the server takes a second or two:

```bash
for i in 1 2 3 4 5; do
  if curl -fsS http://127.0.0.1:8000/api/health >/dev/null 2>&1; then break; fi
  sleep 1
done
```

`--reload` watches Python files in `backend/`. The frontend has no build step — reload the browser tab to pick up `frontend/static/index.html` changes.

## Smoke-test endpoints

```bash
curl -s http://localhost:8000/api/health
curl -s http://localhost:8000/api/config
curl -s http://localhost:8000/api/users
```

`/api/config` is what the frontend reads on boot to set the assistant name, company, and agent label.

## Tail logs

```bash
tail -f /tmp/companion.log
```

Useful prefixes to watch for:
- `[realtime]` — Realtime WebSocket proxy events
- `[realtime/agent]` — external agent subprocess calls
- `[vision]` — face recognition and snapshot endpoints
- `[config]` — config.yaml loading

## Stop the server

```bash
kill $(cat /tmp/companion.pid) 2>/dev/null
```

## Verifying voice / vision changes

There's no automated test for the WebSocket/audio pipeline. You must verify in a browser:

1. Open `http://localhost:8000/` (or your HTTPS URL).
2. Log in as a configured user.
3. Toggle `VOICE` or `VISION` mode at the top.
4. Exercise the path that changed.
5. Watch `/tmp/companion.log` for `[realtime]` lines confirming the expected event flow.

If you can't run a browser, **say so** in your final report. Don't claim voice work "works" based on type checks alone.

## Common iteration patterns

- **Renaming a custom event** (`companion.foo`): grep both `backend/realtime.py` and `frontend/static/index.html` — the protocol is symmetric.
- **Changing the system prompt**: edit `backend/config.py` (template) or `config.yaml` (override). Restart the server; the prompt is built per-session at connect time.
- **Tweaking VAD or voice**: env vars in `.env` (`VAD_THRESHOLD`, `REALTIME_VOICE`, etc.). No code change needed.
- **Adding a new REST endpoint**: pattern is `backend/main.py` with `get_current_user(request)` for auth.
