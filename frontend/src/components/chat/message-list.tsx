import { useEffect, useRef } from "react"
import type { UIMessage } from "ai"
import { MessageBubble } from "./message-bubble"
import { ThinkingBubble } from "./thinking-bubble"
import type { User } from "@/lib/types"

type MessageListProps = {
  messages: UIMessage[]
  currentUser: User
  agentLabel: string
  isStreaming: boolean
}

/**
 * Detects whether the assistant is currently waiting on the `call_agent`
 * tool. We use this to render the "Querying Hermes…" thinking bubble.
 *
 * In the AI SDK 6 protocol, tool-call parts arrive as parts named
 * `tool-<toolName>` with a `state` field: input-streaming, input-available,
 * output-available, output-error. We're "waiting" when the last assistant
 * message has a tool part whose state is input-available (or earlier) and
 * no output-available has come in yet.
 */
function pendingToolQuery(messages: UIMessage[]): string | null {
  const last = messages.at(-1)
  if (!last || last.role !== "assistant") return null
  // Find the latest tool part on the last assistant message
  let pending: { input?: unknown; state?: string } | null = null
  for (const part of last.parts) {
    if (typeof part.type === "string" && part.type.startsWith("tool-")) {
      pending = part as { input?: unknown; state?: string }
    }
  }
  if (!pending) return null
  const state = pending.state ?? ""
  if (state === "output-available" || state === "output-error") return null
  const input = pending.input as { query?: string } | undefined
  return input?.query ?? ""
}

export function MessageList({
  messages,
  currentUser,
  agentLabel,
  isStreaming,
}: MessageListProps) {
  const endRef = useRef<HTMLDivElement | null>(null)

  // Auto-scroll to the bottom on new messages / tokens.
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" })
  }, [messages])

  const pendingQuery = isStreaming ? pendingToolQuery(messages) : null

  return (
    <div className="flex flex-1 flex-col gap-6 overflow-y-auto px-6 py-8">
      {messages.map((m) => (
        <MessageBubble key={m.id} message={m} currentUser={currentUser} />
      ))}
      {pendingQuery !== null && (
        <ThinkingBubble label={agentLabel} query={pendingQuery} />
      )}
      <div ref={endRef} />
    </div>
  )
}
