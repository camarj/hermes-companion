---
name: add-agent-backend
description: Wire up an external agent so conversations route to it instead of the default local Hermes. Use when the user wants to plug in their own Hermes/OpenClaw instance (local or remote VPS) or implement a brand-new agent type.
disable-model-invocation: true
---

# Adding an agent backend

Hermes-companion is a polymorphic multi-agent shell. Every chat/voice turn is
served by an `AgentBackend` — the single seam in `backend/agents/base.py`.
Three concrete backends ship today:

- **`LocalAcpBackend`** — spawns `hermes acp` as a local subprocess (ACP).
- **`RemoteAcpBackend`** — talks to another hermes-companion running in host
  mode over a WebSocket bridge (ACP).
- **`OpenClawBackend`** — spawns `openclaw acp`, the first non-Hermes type.
  OpenClaw also speaks ACP over stdio, so it reuses the same `acp_client`.

A conversation is bound to an *agent instance*. Two orthogonal fields on the
instance decide which backend serves it:

- **`transport`** — *where* it runs. `remote-acp` → `RemoteAcpBackend`.
  Anything else (`local-acp`, default) → resolved locally by type.
- **`type`** — *which* CLI + event mapping. For local transports the **backend
  registry** (`backend/agents/registry.py`) maps `type → backend`. `hermes` and
  `openclaw` are registered out of the box; an unknown/absent type falls back
  to the local Hermes backend (AC-W1-B1 back-compat).

`_resolve_backend()` in `backend/agent_bridge.py` is the dispatcher. It handles
the remote case, then delegates the local case to `build_local_backend(agent)`.
**Adding a new type does not touch the dispatcher** — that is the whole point of
the registry (AC-W2-A1).

> The old `agent.command` subprocess contract is gone. Pointing an entry at an
> arbitrary CLI expecting stdout to be piped back is **silently ignored** —
> execution is always an ACP backend unless you register a new one (Scenario B).

## First: which scenario?

1. **Another instance of an existing type** (a second Hermes, a remote VPS, or
   an OpenClaw pointed at a Gateway) → config only, no Python. **Scenario A.**
2. **A genuinely new agent type** (a different CLI/service) → implement an
   `AgentBackend` subclass and register it. **Scenario B.** OpenClaw is the
   canonical worked example.

Ask the user which one they want before editing anything.

---

## Scenario A — register an instance (config only)

Add an entry to the `agents:` list in `config.yaml`. Schema:

| field | required | meaning |
|---|---|---|
| `id` | yes | Stable unique id; PK in `agent_instances`, referenced by conversations |
| `label` | no (defaults to `id`) | Display name in the UI |
| `type` | no (defaults to `hermes`) | Selects the local backend via the registry (`hermes`, `openclaw`, …) |
| `transport` | no (defaults to `local-acp`) | `local-acp` or `remote-acp` |
| `transport_config` | no (defaults to `{}`) | Transport/gateway params (see below) |
| `system_prompt_override` | no | Custom system prompt (honored per-type — see note) |
| `enabled` | no (defaults to `true`) | `false` seeds the instance but keeps it unusable |

### A local Hermes

```yaml
agents:
  - id: local-default
    label: "Hermes (local)"
    type: hermes
    transport: local-acp
```

### A remote Hermes (a VPS in host mode)

```yaml
agents:
  - id: vps-prod
    label: "Hermes VPS"
    type: hermes
    transport: remote-acp
    transport_config:
      url: "wss://my-host.example.com/api/host/acp"
      token: "env:VPS_HOST_TOKEN"
```

- `token` accepts a literal or `env:VAR_NAME` (resolved at runtime by
  `resolve_token()` in `agents/registry.py`). Prefer `env:` so secrets stay out
  of `config.yaml`.
- The remote box must run with `HERMES_COMPANION_MODE=host` and list the
  matching token under `host_tokens:`. See README → "Deploy a remote Hermes"
  (and `install-host.sh` for one-command provisioning).

### An OpenClaw instance

```yaml
agents:
  - id: openclaw-local
    label: "OpenClaw"
    type: openclaw
    transport: local-acp
    # transport_config:           # optional — only for a remote Gateway
    #   url: "wss://gateway-host:18789"
    #   token: "env:OPENCLAW_GATEWAY_TOKEN"
```

- Preconditions: `npm install -g openclaw@latest` and a running Gateway daemon
  (`openclaw onboard --install-daemon`, local default `http://127.0.0.1:18789`).
- With no `transport_config`, the bridge talks to the local Gateway. A `url` +
  `token` point `openclaw acp` at a remote Gateway natively — so a "remote"
  OpenClaw is still a *local* `openclaw acp` subprocess (transport stays
  `local-acp`); no host sidecar needed.
- **Know its limits** (confirmed, PRD §5.3): OpenClaw emits no reasoning frames,
  ignores `system_prompt_override`, and its stdio bridge cannot headlessly
  auto-approve exec/mutating tools. See "Document capability limits" below.

### System prompt override

Honored per-type. Hermes has no system-prompt flag, so the override is
materialized as an `AGENTS.md` in the session cwd (local) or POSTed to
`/api/host/config/system-prompt` (remote). **OpenClaw ignores it** — its
workspace is gateway-configured and separate from the ACP session cwd.

### Apply

The DB seeds new entries on startup (`database._seed_agents()`), keyed
by `id`. Restart the server; in the UI, the "Add agent" dialog can also create
instances at runtime. The first enabled agent is the default for new
conversations.

```bash
./start.sh
```

Confirm in `/tmp/companion.log`: a local turn shows the `hermes acp` /
`openclaw acp` spawn; a remote turn shows the outbound WS connection.

---

## Scenario B — implement a new agent type

Two edits: write the backend, register it. The dispatcher is **not** touched —
that is enforced by AC-W2-A1. `OpenClawBackend` (`backend/agents/openclaw.py`)
is the reference implementation; read it alongside this.

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
them for identity propagation and native-session resume.

**If your agent speaks ACP over stdio** (like OpenClaw), you barely write
anything: add a `spawn_<agent>_acp` to `acp_client.py` and reuse the existing
client + `_build_env` / `_build_prompt_blocks` helpers — see `OpenClawBackend`.
**If it does not**, your `stream()` maps your agent's native output to the
`AgentEvent` shapes yourself.

### 2. Register it in the backend registry

In `backend/agents/registry.py`, add ONE line so a `type` resolves to your
backend:

```python
register_local_backend("mytype", lambda agent: MyBackend(
    # pull whatever you need off the instance dict / transport_config
    gateway_url=(agent.get("transport_config") or {}).get("url") or None,
    system_prompt_override=agent.get("system_prompt_override"),
))
```

That's it — no change to `agent_bridge._resolve_backend()`. A conversation bound
to `type: mytype` (local transport) now routes to `MyBackend`.

### 3. Register an instance in `config.yaml`

```yaml
agents:
  - id: my-agent
    label: "My Agent"
    type: mytype
    transport: local-acp
    transport_config: { ... }
```

### Test it (TDD)

Per the SDD workflow, write the test first. Backends are tested with injected
fakes — see `tests/backend/agents/test_openclaw.py` and `test_local_acp.py`
(spawn paths use a `client_factory` so no real subprocess is needed), and
`test_registry.py` for the registry contract. Assert your `stream()` emits the
right `AgentEvent` sequence, always closes with `("done", None)`, and that a
freshly registered type is built by `build_local_backend({"type": "mytype"})`.

### Document capability limits (the OpenClaw lesson)

A backend that wraps a CLI inherits that CLI's limits — and they are rarely a
clean superset of Hermes'. When something the UI expects is **not** available,
say so explicitly rather than letting it fail silently:

- Accept the field but leave it inert, with a docstring + AC note explaining
  *why* and a citation. (`OpenClawBackend` accepts `system_prompt_override` but
  cannot apply it — documented, not dropped.)
- Record the limitation in `docs/acceptance-criteria.md` and PRD §5.3 so it is
  discoverable, not folklore.
- Capability differences surface in the UI by *absence* (e.g. no thinking block
  when a backend emits no `("reasoning", …)`), not by extra chrome.

---

## Common pitfalls

- **Pointing an entry at a random CLI.** Won't work — `command` is dead. Use a
  real ACP agent (Scenario A) or register a backend (Scenario B).
- **Editing the dispatcher to add a type.** Unnecessary and discouraged — use
  `register_local_backend(...)`. The dispatcher only special-cases `remote-acp`.
- **Remote/gateway token not resolving.** Check the `env:` var is exported in
  the process that runs `./start.sh`.
- **Output too verbose for voice.** The voice path flattens bullets/headings;
  tables and code fences still sound awkward. Have the agent answer
  conversationally.
- **Missing `("done", None)`.** The facade and SSE layer rely on it to close the
  turn. A backend that never yields it hangs the UI.

## Disabling agents entirely

Set `enabled: false` on every entry (or leave `agents:` empty and drop the
legacy `agent:` block). Conversations then fall back to the local default only
if a Hermes is installed; otherwise the tool surface reports no agent available.
