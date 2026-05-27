import type {
  AgentInstance,
  AppConfig,
  Conversation,
  KnownPerson,
  Message,
  User,
} from "./types"

/**
 * Tiny typed wrapper around fetch().
 * Always sends cookies — the backend uses a `companion_user` cookie for auth.
 */
async function request<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const res = await fetch(path, {
    credentials: "include",
    ...init,
    headers: {
      Accept: "application/json",
      ...(init.headers ?? {}),
    },
  })
  if (!res.ok) {
    const detail = await res.text().catch(() => "")
    throw new ApiError(res.status, detail || res.statusText)
  }
  return (await res.json()) as T
}

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.name = "ApiError"
    this.status = status
  }
}

// ── Config + auth ───────────────────────────────────────────────────────────

export const api = {
  getConfig: () => request<AppConfig>("/api/config"),
  listUsers: () => request<{ users: User[] }>("/api/users").then((r) => r.users),

  me: () =>
    request<{ authenticated: boolean; user?: User }>("/api/me").then((r) =>
      r.authenticated ? (r.user ?? null) : null,
    ),

  login: async (userId: string): Promise<User> => {
    const fd = new FormData()
    fd.append("user_id", userId)
    const r = await request<{ user: User }>("/api/login", {
      method: "POST",
      body: fd,
    })
    return r.user
  },

  logout: () => request<{ success: boolean }>("/api/logout", { method: "POST" }),

  // ── Conversations ────────────────────────────────────────────────────────

  listConversations: () =>
    request<{ conversations: Conversation[] }>("/api/conversations").then(
      (r) => r.conversations,
    ),

  createConversation: (agentId?: string) =>
    request<Conversation>("/api/conversations", {
      method: "POST",
      body: JSON.stringify(agentId ? { agent_id: agentId } : {}),
      headers: { "Content-Type": "application/json" },
    }),

  listAgents: () =>
    request<{ agents: AgentInstance[] }>("/api/agents").then((r) => r.agents),

  // ── Per-agent inspection (AC-W1-U4 frontend) ────────────────────────────

  getAgentInspection: (agentId: string, kind: "skills" | "mcp" | "tools" | "config") =>
    request<{ stdout: string; stderr: string; exit_code: number }>(
      `/api/agents/${encodeURIComponent(agentId)}/${kind}`,
    ),

  setAgentSystemPrompt: (agentId: string, prompt: string) =>
    request<AgentInstance>(
      `/api/agents/${encodeURIComponent(agentId)}/system-prompt`,
      {
        method: "PUT",
        body: JSON.stringify({ system_prompt: prompt }),
        headers: { "Content-Type": "application/json" },
      },
    ),

  getConversation: (id: string) =>
    request<{ conversation: Conversation; messages: Message[] }>(
      `/api/conversations/${encodeURIComponent(id)}`,
    ),

  renameConversation: (id: string, title: string) =>
    request<{ success: boolean }>(
      `/api/conversations/${encodeURIComponent(id)}`,
      {
        method: "PATCH",
        body: JSON.stringify({ title }),
        headers: { "Content-Type": "application/json" },
      },
    ),

  deleteConversation: (id: string) =>
    request<{ success: boolean }>(
      `/api/conversations/${encodeURIComponent(id)}`,
      { method: "DELETE" },
    ),

  // ── Vision + known people ────────────────────────────────────────────────

  visionSnapshot: (image: string, prompt: string | null) =>
    request<{ recognized?: string[] }>("/api/vision/snapshot", {
      method: "POST",
      body: JSON.stringify({ image, prompt }),
      headers: { "Content-Type": "application/json" },
    }),

  visionRecognize: (image: string) =>
    request<{ recognized: string[] }>("/api/vision/recognize", {
      method: "POST",
      body: JSON.stringify({ image }),
      headers: { "Content-Type": "application/json" },
    }),

  listPeople: () =>
    request<{ people: KnownPerson[] }>("/api/people").then((r) => r.people),

  enrollPerson: async (name: string, photo: File) => {
    const fd = new FormData()
    fd.append("name", name)
    fd.append("photo", photo)
    return request<{ success: boolean }>("/api/people/enroll", {
      method: "POST",
      body: fd,
    })
  },

  deletePersonByName: (name: string) =>
    request<{ success: boolean }>(
      `/api/people/by-name/${encodeURIComponent(name)}`,
      { method: "DELETE" },
    ),
}
