# Acceptance criteria

> **Companion doc:** [PRD-multi-agent.md](./PRD-multi-agent.md) (the "what + why").
> This file is the verifiable "how do we know it works" — each criterion below
> maps to one or more tests. Wave 1 is detailed; Waves 2 and 3 are drafts.

Each criterion is written as Given / When / Then and tagged with a test type:

- **pytest unit** — pure function, no I/O.
- **pytest integration** — touches SQLite, FastAPI TestClient, or a subprocess.
- **Vitest** — React component or hook in jsdom.
- **Playwright E2E** — real browser against a real backend.
- **manual /verify** — voice / Realtime; not automatable today.

Tests are written **before** the code that satisfies the AC. See `CLAUDE.md` → "SDD workflow".

---

## Wave 1 — Multi-Hermes (local + remote)

### Architecture & contract

#### AC-W1-A1: AgentBackend defines the polymorphic contract

- **Maps to:** PRD §3.3.
- **Given** the abstract base class `backend.agents.base.AgentBackend`,
- **When** a subclass omits the `stream` method,
- **Then** instantiating it raises `TypeError`,
- **And** the `stream` signature is `(query: str, context: TurnContext, *, image_paths: list[str] | None = None) -> AsyncIterator[AgentEvent]`.
- **Test:** pytest unit — `tests/backend/agents/test_base.py`.

#### AC-W1-A2: AgentEvent is the discriminated union the frontend already consumes

- **Maps to:** PRD §3.3, §3.4.
- **Given** any subclass of `AgentBackend`,
- **When** `stream` yields events during a turn,
- **Then** every event matches `("text", str)`, `("reasoning", str)`, `("tool", dict)`, `("session", str)`, or `("done", None)`.
- **Note:** `("session", str)` was added in the AC-W1-D4 PR for native session-id propagation; consumed by the facade and stripped before reaching the SSE frontend stream.
- **Test:** pytest unit — `tests/backend/agents/test_event_shape.py`.

#### AC-W1-A3: Hermes banner regex parser is removed

- **Maps to:** PRD §3.1.
- **Given** the codebase after Wave 1 ships,
- **When** searching `backend/` for `_BANNER_OPEN_RE`, `_BANNER_CLOSE_RE`, or `_parse_hermes_output`,
- **Then** zero matches are returned.
- **Test:** pytest unit — `tests/backend/test_no_legacy_parser.py`.

#### AC-W1-A4: ACP client speaks JSON-RPC over stdio and maps events

- **Maps to:** PRD §3.1, Plan Fase 0 (spike). Prerequisite for AC-W1-L1.
- **Given** an `AcpClient` instantiated with fake stdin/stdout streams that emit canned `agent_thought_chunk` and `agent_message_chunk` notifications,
- **When** `prompt(session_id, "ping")` is iterated to completion,
- **Then** at least one `("reasoning", str)` event is yielded for every `agent_thought_chunk`,
- **And** at least one `("text", str)` event is yielded for every `agent_message_chunk`,
- **And** a final `("done", None)` event is yielded when the `session/prompt` response arrives.
- **Test:** pytest integration — `tests/backend/agents/test_acp_client.py`.

### Data model & migration

#### AC-W1-D1: First boot creates the new tables idempotently

- **Maps to:** PRD §4.6.
- **Given** a fresh `companion.db`,
- **When** the backend starts twice in a row,
- **Then** tables `agent_instances` and `host_tokens` exist with the documented columns,
- **And** the second boot does not raise or duplicate rows.
- **Test:** pytest integration — `tests/backend/test_db_migrations.py`.

#### AC-W1-D2: Legacy `agent:` config migrates to a single default instance

- **Maps to:** PRD §4.3 (decision 1), §4.6.
- **Given** a `config.yaml` with only the legacy `agent:` block,
- **When** the backend starts on a fresh `companion.db`,
- **Then** `agent_instances` contains exactly one row with `id="local-default"`, `transport="local-acp"`, `created_via="config"`,
- **And** `transport_config_json` reflects the legacy `agent.command` argv.
- **Test:** pytest integration — `tests/backend/test_legacy_config_migration.py`.

#### AC-W1-D3: Conversations are bound to an agent instance via FK

- **Maps to:** PRD §4.6.
- **Given** an empty database with one default instance,
- **When** `POST /api/conversations` is called without an `agent_id`,
- **Then** the row is created with `agent_id` set to the default instance,
- **And** an unknown `agent_id` returns HTTP 400.
- **Test:** pytest integration — `tests/backend/api/test_conversations.py`.

#### AC-W1-D4: `hermes_session_id` is persisted after the first turn

- **Maps to:** PRD §3.5, §4.6.
- **Given** a conversation with `hermes_session_id IS NULL`,
- **When** the agent emits its session id on the first turn,
- **Then** the column is updated within the same request lifecycle,
- **And** subsequent turns reuse that id.
- **Test:** pytest integration — `tests/backend/agents/test_session_persistence.py`.

### Local agent (LocalAcpBackend)

#### AC-W1-L1: LocalAcpBackend round-trips a query with streaming

- **Maps to:** PRD §3.4, §4.3 (decision 2).
- **Given** a `LocalAcpBackend` connected to a fake ACP subprocess,
- **When** `stream("ping", context)` is iterated,
- **Then** at least one `("text", str)` event is yielded before `("done", None)`,
- **And** events arrive incrementally (no full-response buffering).
- **Test:** pytest integration — `tests/backend/agents/test_local_acp.py`.

#### AC-W1-L2: Requester identity is propagated to the agent session

- **Given** a turn with `context.user_id="alice"`, `user_name="Alice"`, `user_role="CEO"`,
- **When** the fake ACP server records its inbound session metadata,
- **Then** all three fields are present (whether as ACP session params or env vars, decided by the spike).
- **Test:** pytest integration — `tests/backend/agents/test_local_acp.py`.

#### AC-W1-L3: Local image attachments are inlined as ACP content blocks

- **Maps to:** PRD §4.1 item 5. Original wording assumed file paths cross the wire; the Fase 0 spike showed ACP only accepts content blocks (`{type:"image", data, mimeType}`), so this AC was revised in PR for AC-W1-L3 to match the actual protocol shape.
- **Given** `image_paths=["/tmp/a.png"]` on a local turn,
- **When** the ACP `session/prompt` request is sent,
- **Then** the `prompt` array contains the user text block followed by `{type:"image", data:<base64 of /tmp/a.png>, mimeType:<detected>}`,
- **And** no separate upload request is made (this is what distinguishes local from remote — see AC-W1-R4).
- **Test:** pytest integration — `tests/backend/agents/test_local_acp.py`.

### Remote agent + host mode

#### AC-W1-R1: Host mode exposes only host endpoints

- **Maps to:** PRD §3.2.
- **Given** the app started with `HERMES_COMPANION_MODE=host`,
- **When** `GET /api/agents` is called,
- **Then** the response is HTTP 404,
- **And** `GET /api/host/skills` returns 200 with the local Hermes' skills.
- **Test:** pytest integration — `tests/backend/host_mode/test_routing.py`.

#### AC-W1-R2: `/api/host/acp` requires a valid bearer token

- **Maps to:** PRD §4.3 (decision 2), §4.4.
- **Given** the host running with one configured token `T1`,
- **When** a WebSocket connects without an `Authorization` header,
- **Then** the connection is rejected (HTTP 401 or WS close 4401),
- **And** `Bearer T1` succeeds while `Bearer wrong` is rejected.
- **Test:** pytest integration — `tests/backend/host_mode/test_auth.py`.

#### AC-W1-R3: RemoteAcpBackend round-trips a query through the host

- **Maps to:** PRD §4.1 item 2.
- **Given** a `RemoteAcpBackend` pointed at a local host instance on `ws://localhost:PORT/api/host/acp`,
- **When** `stream("ping", context)` is iterated,
- **Then** the observable events are identical (modulo timing) to `LocalAcpBackend` against the same Hermes.
- **Test:** pytest integration — `tests/backend/agents/test_remote_acp_e2e.py`.

#### AC-W1-R4: Remote vision uploads the frame before forwarding

- **Maps to:** PRD §4.1 item 5, §4.4.
- **Given** a remote turn with `image_paths=["/tmp/a.png"]`,
- **When** the request is dispatched,
- **Then** `POST /api/host/upload` precedes the ACP turn,
- **And** the ACP message references the upload handle, not the local path.
- **Test:** pytest integration — `tests/backend/agents/test_remote_acp_vision.py`.

#### AC-W1-R5: WS disconnect mid-stream terminates cleanly

- **Given** a `RemoteAcpBackend` mid-stream,
- **When** the host process is killed,
- **Then** the iterator yields a final `("text", "[connection lost — retry]")` and `("done", None)`,
- **And** no exception escapes to the FastAPI route.
- **Test:** pytest integration — `tests/backend/agents/test_remote_acp_failure.py`.

### UI / multi-session UX

#### AC-W1-U1: `/api/agents` CRUD works

- **Maps to:** PRD §4.1 item 1.
- **Given** an empty agent registry,
- **When** the client POSTs a remote instance,
- **Then** GET lists it, PUT updates it, DELETE removes it,
- **And** DELETE refuses if any conversation references the instance.
- **Test:** pytest integration — `tests/backend/api/test_agents.py`.

#### AC-W1-U2: Sidebar groups conversations by agent with color badge

- **Maps to:** PRD §4.3 (decision 4).
- **Given** 3 conversations across 2 instances,
- **When** the sidebar renders,
- **Then** two group headers appear (one per instance),
- **And** each conversation row shows a colored badge keyed to its instance id.
- **Test:** Vitest — `frontend/src/components/__tests__/sidebar.test.tsx`.

#### AC-W1-U3: New conversation dialog shows agent selector when >1 instance

- **Maps to:** PRD §4.1 item 3.
- **Given** the user clicks "New conversation",
- **When** more than one enabled instance exists,
- **Then** the dialog renders a select listing all instances,
- **And** when only one exists, the dialog skips the select and creates immediately.
- **Test:** Vitest — `frontend/src/components/__tests__/new-conversation-dialog.test.tsx`.

#### AC-W1-U4: Settings page lists native config read-only

- **Maps to:** PRD §4.1 item 6.
- **Given** the user navigates to `/settings/agents/<id>`,
- **When** the page loads,
- **Then** sections for skills, tools, and MCP servers render with data from the `/api/host/*` (or local equivalent) endpoints,
- **And** no edit controls appear for those sections.
- **Test:** Vitest — `frontend/src/pages/settings/__tests__/agent-detail.test.tsx`.

#### AC-W1-U5: System prompt editor persists and the next turn honors it

- **Maps to:** PRD §4.1 item 7.
- **Given** the user edits the system prompt for `local-default` and saves,
- **When** the next turn is sent against that instance,
- **Then** the agent receives the new system prompt at session creation (verified via fake ACP server recording).
- **Test:** Playwright E2E — `tests/e2e/system-prompt-edit.spec.ts`.

### Voice / Realtime (manual)

#### AC-W1-V1: Voice in a remote-bound conversation routes to the remote agent

- **Maps to:** PRD §4.1 item 4, §4.3 (decision 3).
- **Given** the active conversation is bound to a remote instance,
- **When** the user activates voice and asks a question that triggers `call_agent`,
- **Then** logs on the host machine show the inbound ACP turn,
- **And** the spoken response reflects data from the remote agent.
- **Test:** manual `/verify`.

#### AC-W1-V1a: Voice connects on the active conversation, not a fresh local one

- **Maps to:** PRD §4.3 (decision 3); regression found during V1 manual smoke.
- **Given** an active conversation bound to a non-default agent,
- **When** voice connects,
- **Then** it reuses that conversation's id (so the turn routes to its bound
  agent); and when there is no active conversation it creates one bound to the
  currently selected agent — never silently defaulting to `local-default`.
- **Test:** Vitest — `frontend/src/hooks/__tests__/resolveVoiceConversationId.test.ts`.

#### AC-W1-V2: An image sent to a remote conversation uploads to the host

- **Maps to:** PRD §4.1 item 5, §4.4 (remote-vision risk).
- **Given** a chat conversation bound to a remote instance,
- **When** the user attaches an image and sends the turn,
- **Then** host logs show `POST /api/host/upload` followed by an ACP turn
  referencing the returned handle.
- **Test:** manual `/verify`; the upload + content-block mechanism is also
  covered by the `RemoteAcpBackend` image-upload unit test.
- **Design note (revised after the Fase 6 smoke):** voice + vision frames are
  injected into the **OpenAI Realtime** model and are **not** forwarded to the
  agent. The voice `call_agent` path (`call_agent_for_voice`) carries no image —
  by design: OpenAI's model is already multimodal and sees the frame, so
  re-uploading it to the agent would double-process and add latency. Raw images
  reach a remote agent only through **chat attachments** (which is what this
  criterion now verifies). The original wording assumed voice+vision uploaded to
  the host; the code routes voice vision through OpenAI instead.

### Back-compat

#### AC-W1-B1: Existing single-Hermes setup is unchanged in UX

- **Maps to:** PRD §4.5.
- **Given** a clone with the legacy `config.yaml` shape (no `agents:` block),
- **When** the user opens the UI and uses chat / voice / vision / attachments,
- **Then** the experience is identical to `main` pre-Wave 1.
- **Test:** manual `/verify` smoke checklist.

#### AC-W1-B1a: hermes acp is spawned with shell-hook auto-approval

- **Maps to:** PRD §4.5; regression found during the B1 smoke.
- **Given** a turn whose agent needs to run a tool guarded by a shell-hook
  prompt (the legacy `hermes chat --yolo` auto-approved these),
- **When** `hermes acp` is spawned for the turn (local or host),
- **Then** the subprocess env sets `HERMES_ACCEPT_HOOKS=1`, so it does not block
  forever on the (TTY-less) approval prompt.
- **Test:** pytest unit — `tests/backend/test_acp_accept_hooks.py`.

---

## Wave 2 — Omniagent (DRAFT)

Refined when Wave 1 merges.

- **AC-W2-A1 (draft):** Adding a new agent type requires implementing only `AgentBackend`; no other module changes.
- **AC-W2-A2 (draft):** `OpenClawBackend` round-trips a query with streaming, emitting the same `AgentEvent` shapes as Hermes backends.
- **AC-W2-U1 (draft):** Instance creation UI exposes a type selector (`hermes`, `openclaw`, `custom`).
- **AC-W2-D1 (draft):** Multiple instances of different types coexist and resume correctly.
- **AC-W2-H1 (draft):** Host mode supports `openclaw` runners alongside `hermes acp`.
- **AC-W2-DOC1 (draft):** `/add-agent-backend` Claude skill produces a working backend for a new agent type in one session.

---

## Wave 3 — Orchestrator + artifacts (DRAFT)

Refined when Wave 2 merges.

- **AC-W3-T1 (draft):** Tasks can be created from the UI, assigned to an agent, and their lifecycle is reflected in real time.
- **AC-W3-T2 (draft):** An agent can delegate a sub-task to another agent via `AgentBackend.delegate(...)`; the result flows back.
- **AC-W3-A1 (draft):** Agents emit artifacts (files, code, documents) via a documented convention; artifacts are persisted, previewable, downloadable.
- **AC-W3-U1 (draft):** UI supports tabs / split-view for parallel conversations.
- **AC-W3-U2 (draft):** A task DAG view shows dependencies and progress.
