import { useState } from "react"
import { Settings as SettingsIcon } from "lucide-react"
import { Sidebar } from "@/components/sidebar"
import { SettingsPanel } from "@/components/settings-panel"
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
  const { conversations, create, remove } = useConversations(true)

  const handleNew = async () => {
    const conv = await create()
    setActiveId(conv.id)
  }

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
        <header className="flex items-center gap-3 border-b border-border bg-card px-8 py-3">
          <span className="flex-1 font-mono text-xs tracking-widest text-muted-foreground uppercase">
            {activeId ? "Active" : "No conversation selected"}
          </span>
          <button
            type="button"
            onClick={() => setSettingsOpen(true)}
            className="rounded p-1 text-muted-foreground hover:text-foreground"
            aria-label="Settings"
          >
            <SettingsIcon className="h-5 w-5" />
          </button>
        </header>

        <section className="flex flex-1 flex-col items-center justify-center px-6 text-center">
          <p className="font-serif text-2xl text-foreground">
            {activeId ? "Conversation ready" : `Hi ${user.name.split(" ")[0]}.`}
          </p>
          <p className="mt-2 max-w-md text-sm text-muted-foreground">
            {activeId
              ? "The chat UI lands in migration PR 4. Right now this is just the shell — the sidebar can create, list, switch, and delete conversations against the real backend."
              : "Click + New conversation in the sidebar to spin one up. The chat UI itself ships in migration PR 4."}
          </p>
        </section>
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
