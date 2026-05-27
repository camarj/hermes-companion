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
  created_at: string
  updated_at: string
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

export type PlaybackMode = "private" | "local"

export type VoiceMode = "chat" | "voice" | "vision"

export type Settings = {
  theme: ThemeMode
  language: string
  playback: PlaybackMode
}

export type KnownPerson = {
  name: string
  count: number
}
