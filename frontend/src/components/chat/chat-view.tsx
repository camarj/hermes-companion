import { useChat } from "@ai-sdk/react"
import { DefaultChatTransport, type UIMessage } from "ai"
import { useEffect, useMemo, useRef } from "react"
import { toast } from "sonner"
import { ChatInput } from "./chat-input"
import { MessageList } from "./message-list"
import { api } from "@/lib/api"
import type { User } from "@/lib/types"

type ConversationMeta = { id: string; title: string | null }

type ChatViewProps = {
  conversationId: string | null
  currentUser: User
  agentLabel: string
  onConversationUpdated: (conv: ConversationMeta) => void
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
}: ChatViewProps) {
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

  // Load history when the conversation changes.
  useEffect(() => {
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
  }, [conversationId, setMessages])

  const isStreaming = status === "submitted" || status === "streaming"
  const isReady = status === "ready" || status === "error"

  return (
    <div className="flex h-full flex-col">
      {messages.length === 0 && !isStreaming ? (
        <div className="flex flex-1 flex-col items-center justify-center px-6 text-center">
          <p className="font-serif text-2xl text-foreground">
            Hi {currentUser.name.split(" ")[0]}.
          </p>
          <p className="mt-2 max-w-md text-sm text-muted-foreground">
            Ask anything. Heavy or live-data questions get routed to {agentLabel}.
          </p>
        </div>
      ) : (
        <MessageList
          messages={messages}
          currentUser={currentUser}
          agentLabel={agentLabel}
          isStreaming={isStreaming}
        />
      )}

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
    </div>
  )
}
