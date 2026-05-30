import { useChat } from "@ai-sdk/react"
import { DefaultChatTransport, type UIMessage } from "ai"
import { useEffect, useMemo, useRef, useState } from "react"
import { toast } from "sonner"
import { ChatInput } from "./chat-input"
import { MessageList } from "./message-list"
import { StartView } from "./start-view"
import { ThinkingBubble } from "./thinking-bubble"
import { t, type Lang } from "@/lib/i18n"
import { api } from "@/lib/api"
import type { Artifact, AppConfig, ChatAttachment, User, VoiceMode } from "@/lib/types"

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

  // Map of UIMessage.id → Artifact[] for rendering download chips.
  // Populated from data-artifacts SSE frames during streaming and from
  // listConversationArtifacts backfill when a conversation is loaded.
  const [artifactsByMessageId, setArtifactsByMessageId] = useState<
    Record<string, Artifact[]>
  >({})

  const pendingAttachmentsRef = useRef<ChatAttachment[]>([])

  const transport = useMemo(
    () =>
      new DefaultChatTransport<UIMessage>({
        api: "/api/chat/stream",
        credentials: "include",
        prepareSendMessagesRequest: ({ messages, id, body }) => {
          const attachments = pendingAttachmentsRef.current
          pendingAttachmentsRef.current = []
          return {
            body: {
              ...(body ?? {}),
              id,
              messages,
              conversation_id: convIdRef.current,
              attachments,
            },
          }
        },
      }),
    [],
  )

  const { messages, sendMessage, status, error, setMessages } = useChat({
    transport,
    onData: (part: { type: string; data?: unknown; messageId?: string; artifacts?: Artifact[] }) => {
      if (part.type === "data-conversation" && part.data) {
        const data = part.data as ConversationMeta
        if (data?.id) onConversationUpdated(data)
      }
      if (part.type === "data-artifacts" && part.messageId && part.artifacts?.length) {
        setArtifactsByMessageId((prev) => ({
          ...prev,
          [part.messageId!]: part.artifacts!,
        }))
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
      setArtifactsByMessageId({})
      return
    }
    let cancelled = false
    const uiIdByDbId: Record<string, string> = {}

    api
      .getConversation(conversationId)
      .then(({ messages: history }) => {
        if (cancelled) return
        const ui: UIMessage[] = history.map((m, idx) => {
          const uiId = `db_${m.id}_${idx}`
          uiIdByDbId[String(m.id)] = uiId
          return {
            id: uiId,
            role:
              m.role === "system"
                ? "assistant"
                : (m.role as "user" | "assistant"),
            parts: [{ type: "text", text: m.content }],
          }
        })
        setMessages(ui)
        return api.listConversationArtifacts(conversationId)
      })
      .then((artifacts) => {
        if (cancelled || !artifacts) return
        const byMsgId: Record<string, Artifact[]> = {}
        for (const art of artifacts) {
          if (!art.message_id) continue
          const uiId = uiIdByDbId[art.message_id] ?? art.message_id
          byMsgId[uiId] = [...(byMsgId[uiId] ?? []), art]
        }
        setArtifactsByMessageId(byMsgId)
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

  const handleSend = (text: string, attachments: ChatAttachment[] = []) => {
    pendingAttachmentsRef.current = attachments
    const composed = attachments.length
      ? text
        ? `${text}\n\n${attachments.map((a) => `[${a.name}]`).join(" ")}`
        : attachments.map((a) => `[${a.name}]`).join(" ")
      : text
    void sendMessage({ text: composed })
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
      <div className="flex min-h-0 flex-1 flex-col">
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
              artifactsByMessageId={artifactsByMessageId}
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
    <div className="flex min-h-0 flex-1 flex-col">
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
