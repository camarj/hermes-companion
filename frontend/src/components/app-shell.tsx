import { useCallback, useMemo, useState } from "react"
import { Settings as SettingsIcon } from "lucide-react"
import { Sidebar } from "@/components/sidebar"
import { SettingsPanel } from "@/components/settings-panel"
import { ChatView } from "@/components/chat/chat-view"
import { useConversations } from "@/hooks/useConversations"
import type { AppConfig, User } from "@/lib/types"
import type { Settings, ThemeMode } from "@/lib/types"

type AppShellProps = {
  config: AppConfig | null
  user: User
  settings: Settings
  onThemeChange: (theme: ThemeMode) => void
  onLanguageChange: (language: string) => void
  onLogout: () => void
}

export function AppShell({
  config,
  user,
  settings,
  onThemeChange,
  onLanguageChange,
  onLogout,
}: AppShellProps) {
  const [activeId, setActiveId] = useState<string | null>(null)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const { conversations, refresh, remove } = useConversations(true)

  const agentLabel = config?.agent_label ?? "agent"

  const handleNew = useCallback(() => {
    // Don't pre-create on the backend; the first chat message creates the
    // conversation server-side. Clearing activeId puts ChatView in "new
    // conversation" mode.
    setActiveId(null)
  }, [])

  const handleConversationUpdated = useCallback(
    (conv: { id: string; title: string | null }) => {
      if (conv.id !== activeId) {
        setActiveId(conv.id)
      }
      // Title may have been auto-generated server-side from the first message;
      // re-fetch the list so the sidebar shows it.
      void refresh()
    },
    [activeId, refresh],
  )

  const headerLabel = useMemo(() => {
    if (!activeId) return "New conversation"
    const conv = conversations.find((c) => c.id === activeId)
    return conv?.title || "Conversation"
  }, [activeId, conversations])

  return (
    <div className="flex h-dvh w-full">
      <Sidebar
        config={config}
        user={user}
        conversations={conversations}
        activeId={activeId}
        onSelect={setActiveId}
        onNew={handleNew}
        onDelete={async (id) => {
          await remove(id)
          if (activeId === id) setActiveId(null)
        }}
        onLogout={onLogout}
      />

      <main className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center gap-4 border-b border-border bg-card px-8 py-4">
          <div className="flex min-w-0 flex-1 flex-col gap-0.5">
            <span className="eyebrow">
              {activeId ? "Conversation" : "New"}
            </span>
            <span className="truncate text-sm text-foreground">
              {headerLabel}
            </span>
          </div>
          <button
            type="button"
            onClick={() => setSettingsOpen(true)}
            className="rounded-full p-2 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
            aria-label="Settings"
          >
            <SettingsIcon className="h-5 w-5" />
          </button>
        </header>

        <ChatView
          key={activeId ?? "new"}
          conversationId={activeId}
          currentUser={user}
          agentLabel={agentLabel}
          onConversationUpdated={handleConversationUpdated}
        />
      </main>

      <SettingsPanel
        open={settingsOpen}
        onOpenChange={setSettingsOpen}
        settings={settings}
        onThemeChange={onThemeChange}
        onLanguageChange={onLanguageChange}
      />
    </div>
  )
}
