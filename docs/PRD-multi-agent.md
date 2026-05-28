# PRD — Multi-agent evolution

> **Status:** approved roadmap, Wave 1 in implementation.
> **Last updated:** 2026-05-27.
> **Audience:** maintainers, contributors, and anyone evaluating whether to fork or extend this project.

This document captures the full multi-wave evolution of `hermes-companion`
from a single-agent voice/chat shell into a polymorphic, multi-agent
platform. It is intentionally durable — the implementation plan for each
wave lives in PRs and tracked issues; this document records **why** we are
heading where we are heading.

---

## 1. Problem statement

`hermes-companion` today is a thin voice + chat shell over the OpenAI
Realtime API, hard-wired to **one** external agent process declared in
`config.yaml` (defaults to the [Hermes](https://github.com/) CLI). Several
users can log in and the shared agent can recognize them, but everyone
talks to the same agent instance.

The product covers a narrow real-world problem (a private, multi-user voice
front-end for a personal assistant). To grow it into something that solves
broader problems — a desk where a person can fluidly switch between, and
eventually coordinate, several different agents — three structural gaps
need to be closed:

1. **Locality.** There is no way to talk to a Hermes running anywhere
   other than the same machine as `hermes-companion`.
2. **Heterogeneity.** The bridge to the agent is implemented as a
   Hermes-specific subprocess + banner-regex parser. Plugging in a
   different agent type (OpenClaw, Claude Agent SDK, custom) means
   re-implementing the streaming layer.
3. **Concurrency.** The data model assumes a single active conversation
   per user. There is no notion of "two parallel sessions with different
   agents".

The goal of the multi-agent evolution is to close those gaps without
compromising the values that made the project worth using in the first
place: easy to self-host, lean dependencies, transparent codebase, and a
short distance from "first clone" to "first message".

---

## 2. Vision in three waves

| Wave | Theme | What changes |
|---|---|---|
| **1 — Multi-Hermes** *(current)* | One agent type, many instances. Pick which Hermes to talk to (local or remote VPS). | Polymorphic agent backend, agent registry, multi-session UX, host mode for remote Hermes, read-only native config inspection + system prompt editing. |
| **2 — Omniagent** | Many agent types, many instances. | Add `OpenClawBackend` (and document the contract for others). Per-instance type selector. CLI-wrapping pattern is the same; the differences live behind the `AgentBackend` interface. |
| **3 — Orchestrator + artifacts** | Agents collaborate. | Tasks as first-class entities, agent-to-agent delegation, artifact generation/preview/download, tabs/split-view for parallel conversations. |

Each wave is shippable on its own. Wave 1 produces a usable multi-Hermes
product. Wave 2 makes the architecture polymorphic-in-practice (not just
in theory). Wave 3 turns the UI into an orchestration surface.

---

## 3. Architectural foundations (used across all waves)

These decisions are intentionally made up front because they are expensive
to revisit later. They are the bedrock for Waves 2 and 3.

### 3.1. Agent Client Protocol (ACP) as the universal transport

Hermes already ships an ACP mode (`hermes acp`). ACP is a JSON-RPC-based
protocol designed by Anthropic + Zed to standardize how editors and
clients talk to coding/conversational agents. Locally it runs over stdio;
remotely the spec defines HTTP/WebSocket (currently work-in-progress in
the reference implementation).

**Decision:** every agent backend in `hermes-companion`, starting in
Wave 1, talks ACP. The current Hermes-specific banner parsing in
`backend/agent_bridge.py` is retired.

**Why:**
- Eliminates a fragile regex parser tied to Hermes' terminal formatting.
- Any future ACP-compatible agent gets a backend nearly for free.
- It is the closest thing the agent ecosystem has to LSP — betting on a
  standard reduces lock-in.

**Trade-off:** Hermes' ACP mode targets code editors (VS Code, Zed,
JetBrains). It may not surface the same reasoning/tool-preview events
that the current banner-parsing path captures. This is the single biggest
implementation risk in Wave 1 and is gated by a mandatory spike
(see Wave 1 §4.4).

### 3.2. Sidecar = the same binary in host mode

Remote Hermes instances are reached by deploying **another copy of
`hermes-companion`** on the remote machine, switched into a host mode
that exposes the local `hermes acp` process over an authenticated
WebSocket.

**Decision:** rather than a separate sidecar package, `hermes-companion`
itself ships a `HERMES_COMPANION_MODE=host` mode that activates only the
host-side endpoints. One binary, two roles.

**Why:**
- Open-source friendliness: contributors learn one codebase.
- Reuses the existing FastAPI app, uvicorn launch, TLS handling, and
  authentication primitives.
- No second repo, no second release process.

**Trade-off:** the host install pulls in the React UI assets it does not
use. The cost is bytes on disk, not runtime overhead.

#### 3.2.1. Open requirement: friendly host-mode provisioning (deferred)

The sidecar model is sound, but the *deployment ergonomics* are not yet
solved. Today, standing up a remote host means a human SSHes into the box,
clones the repo, builds a venv, installs `requirements.txt`, writes a
`config.yaml` with `host_tokens:`, and launches with
`HERMES_COMPANION_MODE=host`. That friction undermines the whole remote-agent
value proposition — if deploying a remote is painful, nobody runs one.

**Requirement:** a one-command install path that provisions the host-mode
sidecar on a machine that *already* runs the `hermes` agent. The envisioned
shape is an **install script that pulls the `hermes-companion` package from
the repository onto the Hermes server**, sets it up in host mode, and seeds a
bearer token — so the operator goes from "I have a `hermes` box" to "I have a
reachable remote agent" in a single step.

**Scope notes:**
- This provisions the **companion sidecar**, not `hermes` itself — `hermes`
  ships its own installer and is assumed present on the target.
- Candidate forms (to be evaluated when this is picked up): a `curl | bash`
  bootstrap script, a published install script in the repo, or a Docker image
  for the host role. The script form (clone/pull + setup + token seed) is the
  current front-runner per the maintainer.
- **Deferred — not Wave 1.** Wave 1 only requires that a remote declared in
  `config.yaml` works; manual deployment is acceptable for that milestone.
  This is a usability deliverable for a later wave.

### 3.3. Polymorphism via a documented `AgentBackend` interface

A small Python abstract base class — `backend/agents/base.py` —
describes the contract that every backend implements. The shape:

```python
class AgentBackend(ABC):
    async def stream(
        self,
        query: str,
        context: TurnContext,
        *,
        image_paths: list[str] | None = None,
    ) -> AsyncIterator[AgentEvent]: ...
```

`AgentEvent` is a discriminated union of `("text", str)`,
`("reasoning", str)`, `("tool", dict)`, and `("done", None)` — the same
shape the SSE chat stream already produces, so the frontend contract is
preserved.

**Why:** the existence of this interface is what makes Waves 2 and 3
possible without rewrites. Wave 1 ships two implementations
(`LocalAcpBackend`, `RemoteAcpBackend`); Wave 2 adds `OpenClawBackend`;
Wave 3 adds composite backends that delegate.

### 3.4. Streaming is non-negotiable

Every backend must deliver tokens as they arrive. No "wait for completion,
then emit" implementations. The current chat SSE contract
(`kind: "text" | "reasoning"`) is preserved verbatim so frontend code does
not change.

### 3.5. Sessions: companion owns the UI history, agent owns its native session

`hermes-companion` already persists conversations and messages in SQLite.
Hermes has its own session store (`hermes sessions`). We do not merge or
mirror them. Instead:

- A `conversations` row stores `hermes_session_id` (nullable) after the
  agent emits its session id on the first turn.
- Resume uses the native mechanism (e.g. `hermes --resume <id>` or its
  ACP equivalent).
- Other agent types (Wave 2+) store their native session id in the same
  column with a small discriminator (`agent_session_id` is the proper
  name; rename if needed when generalizing).

This avoids losing native agent features (memory, checkpoints) while
keeping the polymorphism intact.

---

## 4. Wave 1 — Multi-Hermes (local + remote)

### 4.1. Scope

A single user, on a single browser, can:

1. Define multiple Hermes instances (some local, some remote VPS) in
   `config.yaml` or via the UI.
2. Open conversations against any instance. The sidebar groups
   conversations by instance with a color badge.
3. Switch between conversations without losing per-agent context
   (Hermes resumes its native session).
4. Use voice mode against any instance, including remote ones (with
   transparent image upload for vision).
5. Inspect each instance's native configuration (skills, tools, MCP
   servers) read-only from the UI.
6. Edit each instance's system prompt / personality from the UI.

### 4.2. Out of scope (Wave 1, deferred to later waves)

- Non-Hermes agent types — Wave 2.
- Agent-to-agent task delegation — Wave 3.
- Artifact entities — Wave 3.
- Editing skills / tools / MCP via UI — Wave 2 (requires either an HTTP
  config API in Hermes, or extending the host sidecar to wrap more CLI
  surfaces).
- Automatic reconnect / offline queue for downed remotes — future
  improvement.
- Friendly host-mode provisioning (an install script that deploys the
  companion sidecar onto a Hermes server) — deferred usability deliverable,
  see §3.2.1.

### 4.3. Key design decisions

| # | Decision | Rationale |
|---|---|---|
| 1 | Agent registry lives in `config.yaml` (declarative default) **and** in SQLite (UI-created instances). | Lowest friction for open-source users (declare in yaml, deploy). UI CRUD is additive. |
| 2 | Remote transport is ACP-over-WebSocket through a `hermes-companion` host instance, authenticated by per-token bearer. | Avoids depending on ACP-over-WS support inside Hermes (still WIP); we control framing and auth. |
| 3 | Voice/vision routes to the instance bound to the active conversation. The OpenAI Realtime model answers trivial requests it can satisfy from the system prompt (greetings, small talk) and interprets vision frames itself; complex requests and tool calls are sent to the agent. Vision frames are **not** re-uploaded to the agent in voice — raw images reach a remote agent only via chat attachments (`POST /api/host/upload`). | Avoids "voice goes to a different agent than chat" surprises, and avoids double-processing the frame — the Realtime model is already multimodal, so the agent is invoked only when the request truly needs it. |
| 4 | UI is sidebar-grouped with one active conversation at a time (no tabs). | Preserves the current mental model. Tabs/split-view belong to Wave 3 (orchestration). |
| 5 | Native config management is read-only for skills/tools/MCP, editable for system prompt only. | Hermes exposes no HTTP config API today; we wrap its CLI. Read-only first keeps the surface small and trustworthy. |

### 4.4. Risks (Wave 1)

| Risk | Mitigation |
|---|---|
| Hermes ACP does not emit reasoning / tool-preview events as discrete frames. | **Mandatory spike** before any architectural change. If unrecoverable, we choose between: (a) augmenting via stderr scrape, (b) accepting regression of the "thinking" UI, (c) upstreaming a PR. |
| ACP-over-WebSocket support inside Hermes is WIP. | Sidecar pattern means we never depend on it — we wrap the stdio process locally and expose our own WS. |
| Hermes CLI changes between versions. | Pin to `hermes >= 0.14.0` in docs; `hermes acp --check` for setup validation. |
| Existing installs break on the DB migration. | First-boot seed migrates the legacy `agent:` block to `agents: [{id: "local-default", ...}]` with `created_via = "config"`. |
| Remote vision requires uploading frames. | Host sidecar exposes `POST /api/host/upload`; backend falls back to "remote chat-only, no image" with a warning if upload fails. |
| Bearer tokens for the host sidecar are leaked. | Tokens are scoped per instance and per creating user, rotatable from the UI, and stored only on the backend side. |

### 4.5. Success metrics

- The existing single-Hermes setup keeps working **with no visible UX
  change** and no regression in streaming, voice, or vision.
- A fresh setup with one local Hermes and one remote Hermes declared in
  `config.yaml` can send a message to the remote and receive streaming
  tokens with no perceptible degradation versus local.
- Time from a logged-in user adding a new instance in the UI to sending
  their first message: under 30 seconds.

### 4.6. Data model changes (Wave 1)

```sql
CREATE TABLE agent_instances (
  id                       TEXT PRIMARY KEY,
  label                    TEXT NOT NULL,
  type                     TEXT NOT NULL,           -- "hermes" (only value in Wave 1)
  transport                TEXT NOT NULL,           -- "local-acp" | "remote-acp"
  transport_config_json    TEXT NOT NULL,           -- argv (local) or {url, token_ref} (remote)
  system_prompt_override   TEXT,
  enabled                  INTEGER NOT NULL DEFAULT 1,
  created_via              TEXT NOT NULL,           -- "config" | "user"
  created_at               TEXT NOT NULL,
  updated_at               TEXT NOT NULL
);

CREATE TABLE host_tokens (
  token                    TEXT PRIMARY KEY,
  label                    TEXT NOT NULL,
  created_at               TEXT NOT NULL,
  last_used_at             TEXT
);

ALTER TABLE conversations ADD COLUMN agent_id           TEXT REFERENCES agent_instances(id);
ALTER TABLE conversations ADD COLUMN hermes_session_id  TEXT;
```

`config.yaml` gains:

```yaml
agents:
  - id: local-default
    label: "Hermes (local)"
    transport: local-acp
  - id: vps-prod
    label: "Hermes (VPS prod)"
    transport: remote-acp
    url: wss://vps.example.com/api/host/acp
    token: env:HERMES_VPS_TOKEN
```

The legacy `agent:` block is auto-migrated to a single `agents` entry on
first boot for back-compat.

---

## 5. Wave 2 — Omniagent

### 5.1. Goal

The same UI, multi-session model, and configuration surface, but with
**more than one agent type**. The first non-Hermes target is
[OpenClaw](https://openclaw.ai/), an open-source local agent installable
via `npm i -g openclaw`.

### 5.2. Approach

1. Add `OpenClawBackend(AgentBackend)`. If OpenClaw supports ACP, reuse
   the existing ACP client; otherwise, write a thin event mapper that
   yields the same `AgentEvent` shapes.
2. Surface "agent type" in the UI when creating an instance (`hermes` /
   `openclaw` / `custom`).
3. Leverage `hermes claw` (already present in Hermes' CLI) for config
   migration between the two ecosystems where useful.
4. Update the `/add-agent-backend` Claude skill to use OpenClaw as the
   canonical worked example for contributors who want to add a third
   type.

### 5.3. Open questions for Wave 2

- Does OpenClaw expose streaming over a stable interface? If not, how do
  we keep the "no buffered responses" contract?
- Is there a host-side equivalent (a way to expose a remote OpenClaw via
  the same sidecar pattern), or do we narrow Wave 2 to local-only
  OpenClaw and revisit remote later?
- How do we surface per-agent capability differences in the UI without
  it becoming noisy (e.g. some agents have skills, some do not)?

These will be re-opened as a Wave 2 PRD revision when Wave 1 ships.

---

## 6. Wave 3 — Orchestrator + artifacts

### 6.1. Goal

Move from "talk to one agent at a time" to "ask multiple agents to
collaborate on a task and produce something concrete".

### 6.2. Approach (sketch)

- **Tasks** become a first-class entity. A task has an owner (a user or
  another agent), a description, a target backend, dependencies on other
  tasks, and a status lifecycle.
- `AgentBackend` gains an optional `delegate(task, target_backend)`
  method. Backends that do not support delegation simply do not advertise
  it; the UI hides the affordance.
- **Artifacts** (files, code, documents) get their own table and
  preview/download surfaces. Agents emit artifacts via a new ACP method
  or convention; the backend persists them and the UI renders previews.
- UI grows tabs / split-view so an operator can watch several
  conversations and a task DAG at the same time.

### 6.3. Why this is its own wave

Orchestration adds three orthogonal axes (tasks, delegation, artifacts)
that each touch data model, UI, and protocol. Bundling it with Waves 1–2
would inflate the smallest shippable unit. Better to validate that
multi-agent foundations are solid first.

---

## 7. Cross-wave principles

These constrain every wave; PRs that violate them should be rejected or
explicitly waived.

1. **Stay lean.** No heavy dependencies without explicit discussion.
   The `requirements.txt` should stay small enough that `pip install`
   is fast on a fresh machine.
2. **One pluggable seam, not many.** The `AgentBackend` interface is the
   only seam for agent heterogeneity. Resist adding parallel seams
   (e.g. provider-specific options leaking into FastAPI routes).
3. **The frontend stays in the existing React app.** No second SPA, no
   micro-frontends.
4. **No feature flags.** Each wave either ships or does not. If a
   sub-feature is risky enough to need a flag, it goes in its own
   smaller wave.
5. **Self-hostable end-to-end.** No required SaaS dependency for any
   feature in this PRD. (Optional integrations are fine.)
6. **Voice and chat stay parity.** Anything a user can do in chat with
   an instance, they should be able to do in voice with the same
   instance (modulo the inherent constraints of audio).
7. **Open-source extension is a first-class consumer.** New abstractions
   ship with documentation and (where applicable) an updated
   `/add-agent-backend` Claude skill so contributors can add backends
   on a Saturday afternoon.

---

## 8. Glossary

- **Agent.** A subprocess or remote service that handles "real work" on
  behalf of the assistant (memory, integrations, actions). Hermes is the
  default agent today; OpenClaw is the second target in Wave 2.
- **Agent backend.** A Python class implementing `AgentBackend` — the
  polymorphic adapter to a specific agent type and transport.
- **Agent instance.** A concrete deployment of an agent reachable via a
  specific transport (e.g. "Hermes on my laptop", "Hermes on
  vps-prod"). Persisted in `agent_instances`.
- **ACP (Agent Client Protocol).** JSON-RPC-based protocol standardizing
  agent ↔ client communication. Hermes exposes it via `hermes acp`.
- **Host mode.** A `hermes-companion` instance configured to expose its
  local Hermes via an authenticated WebSocket, used by another
  `hermes-companion` running in client mode to reach it.
- **Sidecar.** The host-mode `hermes-companion` deployed alongside a
  remote Hermes.
- **Companion conversation.** A conversation row in `companion.db`,
  owned by a user, bound to one agent instance.
- **Agent session.** The native session inside the agent (e.g. a Hermes
  session). One-to-one with a companion conversation when supported by
  the agent.

---

## 9. Document conventions

- This file is the durable PRD. The verifiable counterpart is
  [`acceptance-criteria.md`](./acceptance-criteria.md) — every
  requirement here maps to one or more AC there. See `CLAUDE.md` →
  "SDD workflow" for how AC become tests.
- Update the **Status** and **Last updated** lines at the top whenever a
  wave changes state.
- Decisions are recorded in §3 (cross-wave) and §4.3 / §5 / §6 (per
  wave). Reversing a recorded decision requires updating this document
  in the same PR, alongside the corresponding AC.
