import { useChat } from "@ai-sdk/react"
import { DefaultChatTransport, type UIMessage } from "ai"
import { useEffect, useMemo, useRef } from "react"
import { toast } from "sonner"
import { ChatInput } from "./chat-input"
import { MessageList } from "./message-list"
import { ThinkingBubble } from "./thinking-bubble"
import { api } from "@/lib/api"
import type { User, VoiceMode } from "@/lib/types"

type ConversationMeta = { id: string; title: string | null }

type RealtimeView = {
  mode: VoiceMode
  liveMessages: UIMessage[]
  thinking: { tool: string; query: string | null } | null
}

type ChatViewProps = {
  conversationId: string | null
  currentUser: User
  agentLabel: string
  onConversationUpdated: (conv: ConversationMeta) => void
  realtime?: RealtimeView
}

/**
 * Chat panel.
 *
 * Owns the `useChat` instance pointed at `/api/chat/stream` (AI SDK 6 UI
 * Message Stream Protocol). Loads existing message history from the
 * backend when `conversationId` changes, and forwards the
 * `data-conversation` part back up so the parent can refresh its sidebar
 * (e.g. when the backend created a brand-new conversation on the first
 * turn).
 */
export function ChatView({
  conversationId,
  currentUser,
  agentLabel,
  onConversationUpdated,
  realtime,
}: ChatViewProps) {
  const isLive = realtime !== undefined && realtime.mode !== "chat"
  // Track the latest conversationId via a ref so the body-prepare callback
  // always reads the current value, even when useChat doesn't re-mount.
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

  // Load history when the conversation changes. Skip while in a live voice
  // session — the transcripts arrive over the realtime stream, and refetching
  // would race with the live state.
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
          role: m.role === "system" ? "assistant" : (m.role as "user" | "assistant"),
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

  return (
    <div className="flex h-full flex-col">
      {visibleMessages.length === 0 && !isStreaming && !liveThinking ? (
        <div className="flex flex-1 flex-col items-center justify-center px-6 text-center">
          <p className="font-serif text-2xl text-foreground">
            Hi {currentUser.name.split(" ")[0]}.
          </p>
          <p className="mt-2 max-w-md text-sm text-muted-foreground">
            {isLive
              ? "Speak when you're ready."
              : `Ask anything. Heavy or live-data questions get routed to ${agentLabel}.`}
          </p>
        </div>
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

      {!isLive ? (
        <div className="border-t border-border bg-card px-6 py-4">
          <ChatInput
            onSend={(text) => {
              void sendMessage({ text })
            }}
            disabled={!isReady && isStreaming}
          />
          {error && (
            <p className="mt-2 text-xs text-destructive">
              {error instanceof Error ? error.message : String(error)}
            </p>
          )}
        </div>
      ) : (
        <div className="border-t border-border bg-card px-6 py-3 text-center text-xs uppercase tracking-wider text-muted-foreground">
          {realtime?.mode === "vision"
            ? "Vision + voice — speak naturally; the camera is live"
            : "Voice — speak naturally"}
        </div>
      )}
    </div>
  )
}
