import { useCallback, useMemo, useState } from "react"
import { Settings as SettingsIcon } from "lucide-react"
import { toast } from "sonner"
import { Sidebar } from "@/components/sidebar"
import { SettingsPanel } from "@/components/settings-panel"
import { ChatView } from "@/components/chat/chat-view"
import { CameraPanel } from "@/components/voice/camera-panel"
import { MuteButton } from "@/components/voice/mute-button"
import { RealtimeIndicator } from "@/components/voice/realtime-indicator"
import { VoiceModeToggle } from "@/components/voice/voice-mode-toggle"
import { useConversations } from "@/hooks/useConversations"
import { useRealtime } from "@/hooks/useRealtime"
import type {
  AppConfig,
  PlaybackMode,
  Settings,
  ThemeMode,
  User,
} from "@/lib/types"

type AppShellProps = {
  config: AppConfig | null
  user: User
  settings: Settings
  onThemeChange: (theme: ThemeMode) => void
  onLanguageChange: (language: string) => void
  onPlaybackChange: (playback: PlaybackMode) => void
  onLogout: () => void
}

export function AppShell({
  config,
  user,
  settings,
  onThemeChange,
  onLanguageChange,
  onPlaybackChange,
  onLogout,
}: AppShellProps) {
  const [activeId, setActiveId] = useState<string | null>(null)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const { conversations, refresh, remove } = useConversations(true)

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
    playback: settings.playback,
    onError: (msg) => toast.error(msg),
    onConversationCreated: (id) => {
      setActiveId(id)
      void refresh()
    },
  })

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
        onSelect={(id) => {
          // Switching conversation while live would be confusing; bail out of
          // voice/vision before loading another conversation's history.
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
        <header className="flex items-center gap-4 border-b border-border bg-card px-8 py-4">
          <div className="flex min-w-0 flex-1 flex-col gap-0.5">
            <span className="eyebrow">
              {activeId ? "Conversation" : "New"}
            </span>
            <span className="truncate text-sm text-foreground">
              {headerLabel}
            </span>
          </div>

          <div className="flex items-center gap-3">
            <RealtimeIndicator
              connecting={realtime.connecting}
              connected={realtime.connected}
              autoMuted={realtime.autoMuted}
              userMuted={realtime.userMuted}
            />
            <VoiceModeToggle
              mode={realtime.mode}
              onChange={(m) => {
                void realtime.setMode(m)
              }}
              disabled={realtime.connecting}
            />
            {realtime.mode !== "chat" && (
              <MuteButton
                autoMuted={realtime.autoMuted}
                userMuted={realtime.userMuted}
                onClick={realtime.toggleMute}
              />
            )}
            <button
              type="button"
              onClick={() => setSettingsOpen(true)}
              className="rounded-full p-2 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
              aria-label="Settings"
            >
              <SettingsIcon className="h-5 w-5" />
            </button>
          </div>
        </header>

        <ChatView
          key={activeId ?? "new"}
          conversationId={activeId}
          currentUser={user}
          agentLabel={agentLabel}
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
        onThemeChange={onThemeChange}
        onLanguageChange={onLanguageChange}
        onPlaybackChange={onPlaybackChange}
      />
    </div>
  )
}
