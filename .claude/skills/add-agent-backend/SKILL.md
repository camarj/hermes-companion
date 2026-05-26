---
name: add-agent-backend
description: Wire up a custom external agent (not Hermes) so call_agent routes live-data requests to it. Use when the user wants to plug their own CLI, script, or service into the assistant.
disable-model-invocation: true
---

# Adding a custom agent backend

The Realtime model has one tool, `call_agent`. When it decides a question needs live data or real-world action, the backend runs whatever subprocess is configured under `agent.command` in `config.yaml` and pipes the stdout back as the answer.

## Interview the user

Before editing anything, ask them:

1. **What's the agent's entry command?** Examples: `my-agent`, `python /path/to/agent.py`, `./bin/run`, `node ./dist/agent.js`.
2. **How does it accept the query?** Positional argv (preferred), flag like `--query "..."`, stdin (not great — there's no TTY), or HTTP (in which case wrap it in a tiny shell script).
3. **Does it print plain text to stdout?** If it writes to a file or returns structured JSON, we'll need a wrapper.
4. **Auth?** If the agent needs API keys or a token, are those already in the user's environment or do they need to go in `.env`?
5. **Latency?** Typical response time. The default timeout is 180s.

## Edit `config.yaml`

```yaml
agent:
  label: "MyAgent"                # shown in UI ("Querying MyAgent…")
  command:
    - my-agent
    - --query
    - "{query}"
  timeout_seconds: 180
  description: >
    One or two sentences telling the model what this agent can do. Goes into
    the system prompt so the model knows when to route to it.
```

`{query}` is substituted at runtime with the user's question. `{user_id}` is also substituted if you need it. Identity also flows via env: `AGENT_REQUESTER_ID`, `AGENT_REQUESTER_NAME`, `AGENT_REQUESTER_ROLE`.

## Test the subprocess directly first

Before bouncing the server, prove the command works in isolation:

```bash
AGENT_REQUESTER_ID=alice \
AGENT_REQUESTER_NAME=Alice \
my-agent --query "what's the time?"
```

Confirm:
- It prints a plain-text answer to stdout
- It exits 0 (or at least prints something even if it exits non-zero — `agent_bridge.py` tolerates that as long as stdout is non-empty)
- It does NOT read from stdin (there's no TTY in subprocess mode)

## Restart and verify

```bash
./start.sh
```

Trigger a query that should route to the agent (e.g., "what's on my calendar today?") and watch `/tmp/companion.log` for `[realtime/agent]` lines confirming the spawn + answer.

If the model never invokes the tool, make `agent.description` more specific. The model uses that text to decide when the tool is relevant.

## Common pitfalls

- **Subprocess hangs forever.** Usually it's reading stdin. Make sure the agent doesn't block on input.
- **Output is too verbose for voice.** The voice variant flattens bullets/headings into a single line, but markdown tables and code fences still sound awkward. Have the agent respond conversationally.
- **Permission errors.** The subprocess inherits the parent process's env and cwd. Check file/network permissions when running it directly first.
- **Long-running agents.** Bump `timeout_seconds`. Also be aware: while the tool runs, the assistant's voice is silent (the model said its filler line and is now waiting). Past ~60s users get impatient.

## Disabling the tool entirely

Set `agent.command: []` (empty list). The assistant runs in voice-only mode with no external tool — useful for demos or privacy-sensitive deployments.

## Wrapping a non-CLI agent

If the agent runs as an HTTP service or library, write a tiny shell script that bridges it:

```bash
#!/usr/bin/env bash
# scripts/my-agent.sh — bridges an HTTP service to the call_agent CLI contract
curl -fsS -X POST "https://my-service.example.com/query" \
  -H "Authorization: Bearer $MY_TOKEN" \
  -H "X-Requester: $AGENT_REQUESTER_NAME" \
  -d "{\"query\": $(jq -Rs . <<< "$1")}" \
  | jq -r .answer
```

Then in `config.yaml`:

```yaml
agent:
  command: ["./scripts/my-agent.sh", "{query}"]
```

Same contract — argv in, stdout out.
