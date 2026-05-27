# ACP ↔ AgentEvent mapping

> **Status:** spike findings (Wave 1 Fase 0). Validated against
> `hermes-agent v0.14.0` on 2026-05-27.
> **Companion:** [`backend/acp_client.py`](../backend/acp_client.py) is the
> minimal client built from these findings. AC-W1-A4 in
> [`acceptance-criteria.md`](./acceptance-criteria.md).

The spike answered the question that was the single biggest unknown of
Wave 1 (PRD §4.4): does Hermes ACP surface reasoning / tool-preview
events as discrete frames? **Yes.** This document records the protocol
shape so the rest of Wave 1 can be built without re-discovering it.

---

## 1. Protocol surface (v1)

Hermes ACP is JSON-RPC 2.0 over stdio, one message per line. Three RPCs
are enough for a single turn:

| Method | Direction | Purpose |
|---|---|---|
| `initialize` | client → agent | Handshake. Negotiates protocol version + capabilities. |
| `session/new` | client → agent | Creates a session. Returns the `sessionId` we must reuse for all turns. |
| `session/prompt` | client → agent | Sends one user turn. Streams updates as `session/update` notifications until the response arrives. |

In addition the agent emits notifications:

| Method | Direction | Purpose |
|---|---|---|
| `session/update` | agent → client | All streaming output during a turn, plus session metadata. Discriminated by the `params.update.sessionUpdate` field. |

### `initialize`

**Request:**
```json
{
  "jsonrpc": "2.0", "id": 1, "method": "initialize",
  "params": { "protocolVersion": 1, "clientCapabilities": {} }
}
```

**Response result:**
```json
{
  "protocolVersion": 1,
  "agentInfo": { "name": "hermes-agent", "version": "0.14.0" },
  "agentCapabilities": {
    "loadSession": true,
    "promptCapabilities": { "image": true },
    "sessionCapabilities": { "fork": {}, "list": {}, "resume": {} }
  },
  "authMethods": [/* … */]
}
```

Notable: `promptCapabilities.image: true` confirms ACP carries our
existing `--image` semantics. `loadSession` + `sessionCapabilities.resume`
support the `hermes_session_id` persistence model from PRD §3.5.

### `session/new`

**Request:**
```json
{
  "jsonrpc": "2.0", "id": 2, "method": "session/new",
  "params": { "cwd": "/tmp", "mcpServers": [] }
}
```

**Response result:**
```json
{
  "sessionId": "512e0cce-1d70-41d6-903a-4b7beaf3fd88",
  "models": { "availableModels": [/* provider × model list */] }
}
```

Side effects: Hermes initializes the OpenAI client, auxiliary clients,
and vision adapter at this point (≈2-3 seconds of stderr logs). The
`models` field can be ignored for Wave 1 — model selection stays in
Hermes' own config.

### `session/prompt`

**Request:**
```json
{
  "jsonrpc": "2.0", "id": 3, "method": "session/prompt",
  "params": {
    "sessionId": "<from session/new>",
    "prompt": [{ "type": "text", "text": "reply with one word: hello" }]
  }
}
```

**Response result (arrives last):**
```json
{
  "stopReason": "end_turn",
  "usage": {
    "cachedReadTokens": 15, "inputTokens": 13268,
    "outputTokens": 134, "thoughtTokens": 0, "totalTokens": 13402
  }
}
```

`stopReason` observed so far: `"end_turn"` (normal completion) and
`"refusal"` (rejected). Others probably exist (`max_tokens`,
`tool_use`, etc.) — see §4 follow-ups.

### `session/update` notifications

Emitted between the prompt request and its response. The discriminator
is `params.update.sessionUpdate`:

| `sessionUpdate` | Payload | Meaning |
|---|---|---|
| `available_commands_update` | `{ availableCommands: [...] }` | Initial slash-command catalog. Fires once per session. Noise for our purposes. |
| `usage_update` | `{ size, used }` | Context-window budget. Useful for UI but not part of the turn output. |
| `agent_thought_chunk` | `{ content: { text, type: "text" } }` | **Chain of thought.** One token (or a few) per chunk. → `("reasoning", text)` |
| `agent_message_chunk` | `{ content: { text, type: "text" } }` | **Final answer.** Streamed token-by-token like reasoning. → `("text", text)` |

Tool-call notifications were **not yet observed** in the spike — the
"hello" query didn't trigger any. Probe for them during Fase 1 with a
query that invokes the agent (e.g. "what's on my calendar today?") and
extend the mapping accordingly.

---

## 2. Mapping rule (current)

```
agent_thought_chunk → ("reasoning", payload.content.text)
agent_message_chunk → ("text",      payload.content.text)
session/prompt reply (stopReason: end_turn) → ("done", None)
everything else → ignored
```

This is implemented verbatim in `backend/acp_client.py:_map_update`.
The frontend's existing SSE contract (`kind: "text" | "reasoning"`)
consumes this without change.

---

## 3. Implementation notes (what bit me)

- **Hermes ACP does not exit cleanly when stdin closes.** Killing the
  subprocess hard is necessary on shutdown. `spawn_hermes_acp()` does
  this in its `finally`.
- **Don't trust IDs across requests blindly.** During `initialize` and
  `session/new` no notifications arrive yet, but a defensive client
  should keep reading until it sees the matching `id`. The minimal
  client does this with `_request()`.
- **Startup is slow (≈2 s).** `hermes acp` loads `.env`, initializes the
  OpenAI client, auxiliary clients, etc. Wave 1 should either pool
  connections per agent instance or accept the cold-start latency on
  first turn.
- **Stderr is chatty.** Hermes logs at INFO level on stderr. Drain it
  in a background task or it will eventually block on a full pipe.
- **JSON lines, not bytes.** One message per line; messages are
  newline-terminated JSON. No content-length framing.
- **The `cwd` matters.** `session/new` requires a real-looking working
  directory. `/tmp` works for spikes; Wave 1 should use a per-user
  scratch dir or the project root depending on what the agent expects.

---

## 4. Follow-ups (gated by Fase 1 work, not blocking)

1. **Tool calls.** Trigger a tool-using query and capture the
   notifications that surround it. Expected candidates: a dedicated
   `tool_call_start` / `tool_call_end` pair, or `agent_message_chunk`
   with non-text `content.type`. Map them to `("tool", dict)`.
2. **Image attachments.** Replace the text-only prompt array with one
   containing `{ "type": "image", ... }` entries. Verify against
   `promptCapabilities.image: true` and document the on-wire shape.
3. **Session resume.** Capabilities advertise `loadSession` and
   `sessionCapabilities.resume`. Probe `session/load` (or whatever the
   method is named) to round-trip a `hermes_session_id`.
4. **Error paths.** What does Hermes emit on bad auth, model error,
   protocol violation? Spike found `stopReason: "refusal"` but no
   error response shape. Map errors to a meaningful terminator.
5. **Cancellation.** ACP likely defines `session/cancel` for stopping a
   turn in flight. Worth implementing for Wave 1's UI "stop" button.
6. **Multiple turns in one session.** Confirm that calling
   `session/prompt` repeatedly with the same `sessionId` preserves the
   conversation context (vs. requiring `session/load` between turns).

These are explicitly NOT in the spike scope. They become unit + integration
tests in Fase 1 (LocalAcpBackend) under new AC entries.

---

## 5. Verification recipe

To re-verify the mapping on a new Hermes version:

```bash
# Unit tests against fake stdio — should be instant.
./venv/bin/pytest tests/backend/agents/test_acp_client.py -v

# End-to-end smoke against real hermes acp.
PYTHONPATH=backend ./venv/bin/python -m backend.acp_client \
  "reply with one word: hello"

# Compare to the existing path.
hermes chat -q "reply with one word: hello" --yolo
```

The script should print streamed `[thinking] …` reasoning followed by
the final answer ("hello"). The legacy path prints just the answer
wrapped in a banner.
