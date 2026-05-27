import { useChat } from "@ai-sdk/react"
import { DefaultChatTransport, type UIMessage } from "ai"
import { useEffect, useMemo, useRef } from "react"
import { toast } from "sonner"
import { ChatInput } from "./chat-input"
import { MessageList } from "./message-list"
import { StartView } from "./start-view"
import { ThinkingBubble } from "./thinking-bubble"
import { t, type Lang } from "@/lib/i18n"
import { api } from "@/lib/api"
import type { AppConfig, User, VoiceMode } from "@/lib/types"

type ConversationMeta = { id: string; title: string | null }

type RealtimeView = {
  mode: VoiceMode
  liveMessages: UIMessage[]
  thinking: { tool: string; query: string | null } | null
}

type ChatViewProps = {
  config: AppConfig | null
  conversationId: string | null
  currentUser: User
  agentLabel: string
  lang: Lang
  onConversationUpdated: (conv: ConversationMeta) => void
  realtime?: RealtimeView
}

export function ChatView({
  config,
  conversationId,
  currentUser,
  agentLabel,
  lang,
  onConversationUpdated,
  realtime,
}: ChatViewProps) {
  const i = t(lang)
  const isLive = realtime !== undefined && realtime.mode !== "chat"

  const convIdRef = useRef(conversationId)
  useEffect(() => {
    convIdRef.current = conversationId
  }, [conversationId])

  const transport = useMemo(
    () =>
      new DefaultChatTransport<UIMessage>({
        api: "/api/chat/stream",
        credentials: "include",
        prepareSendMessagesRequest: ({ messages, id, body }) => ({
          body: {
            ...(body ?? {}),
            id,
            messages,
            conversation_id: convIdRef.current,
          },
        }),
      }),
    [],
  )

  const { messages, sendMessage, status, error, setMessages } = useChat({
    transport,
    onData: (part: { type: string; data?: unknown }) => {
      if (part.type === "data-conversation" && part.data) {
        const data = part.data as ConversationMeta
        if (data?.id) onConversationUpdated(data)
      }
    },
    onError: (e) => {
      toast.error(e instanceof Error ? e.message : String(e))
    },
  })

  // Load history when the conversation changes. Skip while live — transcripts
  // arrive over the realtime stream and refetching would race.
  useEffect(() => {
    if (isLive) return
    if (!conversationId) {
      setMessages([])
      return
    }
    let cancelled = false
    api
      .getConversation(conversationId)
      .then(({ messages: history }) => {
        if (cancelled) return
        const ui: UIMessage[] = history.map((m, idx) => ({
          id: `db_${m.id}_${idx}`,
          role:
            m.role === "system"
              ? "assistant"
              : (m.role as "user" | "assistant"),
          parts: [{ type: "text", text: m.content }],
        }))
        setMessages(ui)
      })
      .catch((e) => {
        toast.error(
          `Couldn't load conversation: ${e instanceof Error ? e.message : String(e)}`,
        )
      })
    return () => {
      cancelled = true
    }
  }, [conversationId, setMessages, isLive])

  const isStreaming = status === "submitted" || status === "streaming"
  const isReady = status === "ready" || status === "error"

  const visibleMessages = isLive ? realtime.liveMessages : messages
  const liveThinking = isLive ? realtime.thinking : null
  const showStart = !isLive && visibleMessages.length === 0 && !isStreaming

  const handleSend = (text: string) => {
    void sendMessage({ text })
  }

  if (showStart) {
    return (
      <StartView
        config={config}
        lang={lang}
        onSend={handleSend}
        inputDisabled={!isReady && isStreaming}
      />
    )
  }

  // Live (voice/vision) — show only transcripts + status hint at bottom.
  if (isLive) {
    return (
      <div className="flex h-full flex-col">
        {visibleMessages.length === 0 && !liveThinking ? (
          <StartView
            config={config}
            lang={lang}
            onSend={handleSend}
            inputDisabled
            hintOverride={
              realtime?.mode === "vision" ? i.visionModeHint : i.voiceModeHint
            }
          />
        ) : (
          <div className="relative flex flex-1 flex-col overflow-hidden">
            <MessageList
              messages={visibleMessages}
              currentUser={currentUser}
              agentLabel={agentLabel}
              isStreaming={isStreaming}
            />
            {liveThinking && (
              <div className="px-6 pb-2">
                <ThinkingBubble
                  label={agentLabel}
                  query={liveThinking.query ?? ""}
                />
              </div>
            )}
          </div>
        )}
        <div className="border-t border-border bg-background px-6 py-3 text-center font-mono text-[11px] uppercase tracking-[0.12em] text-muted-foreground">
          {realtime?.mode === "vision" ? i.visionModeHint : i.voiceModeHint}
        </div>
      </div>
    )
  }

  // Chat with messages — message list + bottom input
  return (
    <div className="flex h-full flex-col">
      <div className="relative flex flex-1 flex-col overflow-hidden">
        <MessageList
          messages={visibleMessages}
          currentUser={currentUser}
          agentLabel={agentLabel}
          isStreaming={isStreaming}
        />
        {liveThinking && (
          <div className="px-6 pb-2">
            <ThinkingBubble
              label={agentLabel}
              query={liveThinking.query ?? ""}
            />
          </div>
        )}
      </div>

      <div className="border-t border-border bg-background px-6 pt-2 pb-6">
        <div className="mx-auto w-full max-w-[80%]">
          <ChatInput
            onSend={handleSend}
            disabled={!isReady && isStreaming}
            placeholder={i.inputPlaceholder}
          />
          {error && (
            <p className="mt-2 text-xs text-destructive">
              {error instanceof Error ? error.message : String(error)}
            </p>
          )}
        </div>
      </div>
    </div>
  )
}
