// Shape mirrors the FastAPI backend in backend/main.py and database.py.

export type User = {
  id: string
  name: string
  role: string
  is_shared_space: boolean
  is_reunion: boolean
}

export type Conversation = {
  id: string
  user_id: string
  title: string
  agent_id?: string | null
  created_at: string
  updated_at: string
}

export type AgentInstance = {
  id: string
  label: string
  type: string
  transport: string
  transport_config: Record<string, unknown>
  system_prompt_override?: string | null
  enabled: boolean
  created_via: string
  created_at: string
  updated_at: string
}

export type CreateAgentPayload = {
  id: string
  label: string
  type: string
  transport: string
  transport_config?: Record<string, unknown>
}

export type Message = {
  id: number
  conversation_id: string
  role: "user" | "assistant" | "system"
  content: string
  created_at: string
}

export type AppConfig = {
  assistant_name: string
  company_name: string
  company_url: string
  language: string
  agent_enabled: boolean
  agent_label: string
}

export type ThemeMode = "dark" | "light" | "system"

export type VoiceMode = "chat" | "voice" | "vision"

export type Settings = {
  theme: ThemeMode
  language: string
}

export type KnownPerson = {
  name: string
  count: number
}

export type ChatAttachment = {
  name: string
  size: number
  content: string
}
