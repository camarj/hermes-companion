import { useCallback, useState } from "react"
import { Settings as SettingsIcon } from "lucide-react"
import { toast } from "sonner"
import { Sidebar } from "@/components/sidebar"
import { SettingsPanel } from "@/components/settings-panel"
import { ChatView } from "@/components/chat/chat-view"
import { CameraPanel } from "@/components/voice/camera-panel"
import { ModeBar } from "@/components/voice/mode-bar"
import { RealtimeIndicator } from "@/components/voice/realtime-indicator"
import { useConversations } from "@/hooks/useConversations"
import { useHealth } from "@/hooks/useHealth"
import { useRealtime } from "@/hooks/useRealtime"
import { t } from "@/lib/i18n"
import type {
  AppConfig,
  Settings,
  ThemeMode,
  User,
} from "@/lib/types"
import { cn } from "@/lib/utils"

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
  const lang = settings.language
  const i = t(lang)
  const online = useHealth()

  const agentLabel = config?.agent_label ?? "agent"

  const handleNew = useCallback(() => {
    setActiveId(null)
  }, [])

  const handleConversationUpdated = useCallback(
    (conv: { id: string; title: string | null }) => {
      if (conv.id !== activeId) {
        setActiveId(conv.id)
      }
      void refresh()
    },
    [activeId, refresh],
  )

  const realtime = useRealtime({
    user,
    onError: (msg) => toast.error(msg),
    onConversationCreated: (id) => {
      setActiveId(id)
      void refresh()
    },
  })

  const statusLabel = online === false ? i.offline : i.online
  const statusClass =
    online === false
      ? "text-destructive"
      : online === true
        ? "text-muted-foreground"
        : "text-muted-foreground/60"

  return (
    <div className="flex h-dvh w-full">
      <Sidebar
        config={config}
        user={user}
        conversations={conversations}
        activeId={activeId}
        lang={lang}
        onSelect={(id) => {
          if (realtime.mode !== "chat") void realtime.setMode("chat")
          setActiveId(id)
        }}
        onNew={() => {
          if (realtime.mode !== "chat") void realtime.setMode("chat")
          handleNew()
        }}
        onDelete={async (id) => {
          await remove(id)
          if (activeId === id) setActiveId(null)
        }}
        onLogout={onLogout}
      />

      <main className="flex min-w-0 flex-1 flex-col">
        {/* Slim header: status on left, settings on right */}
        <header className="flex items-center gap-3 border-b border-border bg-card px-6 py-3">
          <span
            className={cn(
              "font-mono text-[11px] uppercase tracking-[0.12em]",
              statusClass,
            )}
          >
            {statusLabel}
          </span>
          <div className="flex-1" />
          <RealtimeIndicator
            connecting={realtime.connecting}
            connected={realtime.connected}
            autoMuted={realtime.autoMuted}
            userMuted={realtime.userMuted}
          />
          <button
            type="button"
            onClick={() => setSettingsOpen(true)}
            className="rounded-full p-2 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
            aria-label={i.settingsAria}
          >
            <SettingsIcon className="h-4 w-4" />
          </button>
        </header>

        {/* Mode bar: TEMA / REPRODUCCIÓN / MODO */}
        <ModeBar
          lang={lang}
          theme={settings.theme}
          mode={realtime.mode}
          autoMuted={realtime.autoMuted}
          userMuted={realtime.userMuted}
          modeDisabled={realtime.connecting}
          onThemeChange={onThemeChange}
          onModeChange={(m) => void realtime.setMode(m)}
          onToggleMute={realtime.toggleMute}
        />

        <ChatView
          key={activeId ?? "new"}
          config={config}
          conversationId={activeId}
          currentUser={user}
          agentLabel={agentLabel}
          lang={lang}
          onConversationUpdated={handleConversationUpdated}
          realtime={{
            mode: realtime.mode,
            liveMessages: realtime.liveMessages,
            thinking: realtime.thinking,
          }}
        />
      </main>

      <CameraPanel
        videoRef={realtime.attachCameraVideo}
        visible={realtime.mode === "vision" && realtime.cameraActive}
      />

      <SettingsPanel
        open={settingsOpen}
        onOpenChange={setSettingsOpen}
        settings={settings}
        lang={lang}
        onLanguageChange={onLanguageChange}
      />
    </div>
  )
}
