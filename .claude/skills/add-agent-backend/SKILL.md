---
name: add-agent-backend
description: Wire up an external agent so conversations route to it instead of the default local Hermes. Use when the user wants to plug in their own Hermes instance (local or remote VPS) or implement a brand-new backend type.
disable-model-invocation: true
---

# Adding an agent backend

Hermes-companion is a polymorphic multi-agent shell. Every chat/voice turn is
served by an `AgentBackend` — the single seam in `backend/agents/base.py`. Two
concrete backends ship today, both speaking ACP (Agent Client Protocol) to a
Hermes process:

- **`LocalAcpBackend`** — spawns `hermes acp` as a local subprocess.
- **`RemoteAcpBackend`** — talks to another hermes-companion running in host
  mode over a WebSocket bridge.

A conversation is bound to an *agent instance*. The instance's `transport`
field decides which backend serves it. `_resolve_backend()` in
`backend/agent_bridge.py` is the dispatcher. Conversations with no agent bound
(NULL `agent_id`) fall back to a local Hermes — that's the legacy single-agent
behaviour (AC-W1-B1).

> The old `agent.command` subprocess contract is gone. If you point an entry at
> an arbitrary CLI expecting stdout to be piped back, it will be **silently
> ignored** — execution is always `hermes acp` over ACP unless you write a new
> backend (Scenario B below).

## First: which scenario?

1. **Adding another Hermes instance** (local or a remote VPS) → config only,
   no Python. Go to Scenario A.
2. **Adding a genuinely different agent** (an OpenAI Agents SDK app, a CrewAI
   flow, a custom service that does NOT speak ACP) → you must implement an
   `AgentBackend` subclass. Go to Scenario B.

Ask the user which one they want before editing anything.

---

## Scenario A — register another Hermes instance (config only)

Add an entry to the `agents:` list in `config.yaml`. Schema:

| field | required | meaning |
|---|---|---|
| `id` | yes | Stable unique id; becomes the PK in `agent_instances` and is referenced by conversations |
| `label` | no (defaults to `id`) | Display name in the UI |
| `type` | no (defaults to `hermes`) | Agent-type taxonomy; not used for dispatch yet |
| `transport` | no (defaults to `local-acp`) | `local-acp` or `remote-acp` — this is what picks the backend |
| `transport_config` | no (defaults to `{}`) | Transport params; for remote: `url` + `token` |
| `system_prompt_override` | no | Custom system prompt (see note below) |
| `enabled` | no (defaults to `true`) | `false` seeds the instance but keeps it unusable |

### Local instance

```yaml
agents:
  - id: local-default
    label: "Hermes (local)"
    transport: local-acp
```

`transport_config` is empty for local — it always runs `hermes acp` from PATH.

### Remote instance (a VPS in host mode)

```yaml
agents:
  - id: vps-prod
    label: "Hermes VPS"
    transport: remote-acp
    transport_config:
      url: "wss://my-host.example.com/api/host/acp"
      token: "env:VPS_HOST_TOKEN"
```

- `token` accepts a literal or an `env:VAR_NAME` reference (resolved at runtime
  by `_resolve_token()`). Prefer `env:` so secrets stay out of `config.yaml`.
- The remote box must run hermes-companion with `HERMES_COMPANION_MODE=host`
  and list the matching token under `host_tokens:`. See the README →
  "Deploy a remote Hermes".
- Shorthand: top-level `url:` / `token:` keys on the entry are auto-promoted
  into `transport_config` if you omit it.

### System prompt override

`system_prompt_override` is honored by both backends, but Hermes has no
system-prompt flag — the override is materialized as an `AGENTS.md` file in the
session cwd (locally) or POSTed to `/api/host/config/system-prompt` (remotely).

### Apply

The DB seeds new entries on startup (`database._seed_agent_instances()`), keyed
by `id`. Restart the server, then in the UI create or switch a conversation to
the new agent. The first enabled agent is the default for new conversations.

```bash
./start.sh
```

Confirm in `/tmp/companion.log`: a local turn shows the `hermes acp` spawn; a
remote turn shows the outbound WS connection to your host URL.

---

## Scenario B — implement a new backend type

There is no plugin registry yet — adding a non-ACP agent means three edits.

### 1. Subclass `AgentBackend`

In a new file under `backend/agents/`, implement the one abstract method:

```python
from agents.base import AgentBackend, AgentEvent, TurnContext

class MyBackend(AgentBackend):
    async def stream(
        self,
        query: str,
        context: TurnContext,
        *,
        image_paths: list[str] | None = None,
    ) -> AsyncIterator[AgentEvent]:
        ...
```

Yield `AgentEvent` tuples and ALWAYS terminate with `("done", None)`, even on
failure. The five valid shapes:

| event | payload | rendered as |
|---|---|---|
| `("text", str)` | answer chunk | assistant bubble |
| `("reasoning", str)` | thinking chunk | reasoning block |
| `("tool", dict)` | tool-call notice | tool preview |
| `("session", str)` | the agent's native session id | consumed for resume, not shown |
| `("done", None)` | terminator | — |

`TurnContext` carries `user_id`, `user_name`, `user_role`, `session_id` — use
them for identity propagation.

### 2. Add a `transport` constant

Pick a new string, e.g. `"openai-agents"`.

### 3. Extend the dispatcher

In `backend/agent_bridge.py`, add a branch to `_resolve_backend()`:

```python
if transport == "openai-agents":
    cfg = agent.get("transport_config") or {}
    return MyBackend(**cfg)
```

### 4. Register it in `config.yaml`

```yaml
agents:
  - id: my-agent
    label: "My Agent"
    transport: openai-agents
    transport_config: { ... }
```

### Test it (TDD)

Per the SDD workflow, write the test first. Backends are tested with injected
fakes — see `tests/backend/agents/` for the `LocalAcpBackend` /
`RemoteAcpBackend` patterns (spawn paths use `client_factory` / `_spawn_acp`
indirection so no real subprocess or socket is needed). Assert your `stream()`
emits the right `AgentEvent` sequence and always closes with `("done", None)`.

---

## Common pitfalls

- **Pointing an entry at a random CLI.** Won't work — `command` is dead. Use a
  real ACP agent (Scenario A) or write a backend (Scenario B).
- **Remote token not resolving.** Check the `env:` var is exported in the
  process that runs `./start.sh`, and that the host lists the same token.
- **Output too verbose for voice.** The voice path flattens bullets/headings;
  tables and code fences still sound awkward. Have the agent answer
  conversationally.
- **Missing `("done", None)`.** The facade and SSE layer rely on it to close
  the turn. A backend that never yields it hangs the UI.

## Disabling agents entirely

Set `enabled: false` on every entry (or leave `agents:` empty and drop the
legacy `agent:` block). Conversations then fall back to the local default only
if a Hermes is installed; otherwise the tool surface reports no agent
available.
