import type { UIMessage } from "ai"
import { Markdown } from "./markdown"
import { ReasoningBlock } from "./reasoning-block"
import { cn } from "@/lib/utils"
import type { User } from "@/lib/types"

type MessageBubbleProps = {
  message: UIMessage
  currentUser: User
}

/**
 * Render a single chat turn.
 *
 * User messages are right-aligned in a tinted bubble. Assistant messages are
 * left-aligned with avatar, and their `parts[]` map to:
 *   - text → markdown bubble
 *   - reasoning → collapsible ReasoningBlock
 *   - tool-call_agent (state input-available, output-available) — handled
 *     separately by ChatView's transient thinking bubble; ignored here since
 *     once the tool finishes the answer parts carry the payload.
 */
export function MessageBubble({ message, currentUser }: MessageBubbleProps) {
  const isUser = message.role === "user"

  // Concatenate text parts so a single visual bubble shows the full message
  // even when the SDK split it across multiple text-delta frames.
  const textParts = message.parts.filter((p) => p.type === "text") as Array<{
    type: "text"
    text: string
  }>
  const reasoningParts = message.parts.filter(
    (p) => p.type === "reasoning",
  ) as Array<{ type: "reasoning"; text: string }>

  const text = textParts.map((p) => p.text).join("")

  return (
    <div className={cn("flex items-start gap-3", isUser && "flex-row-reverse")}>
      <div
        className={cn(
          "flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-xs",
          isUser
            ? "bg-muted text-foreground"
            : "border border-primary text-primary",
        )}
      >
        {isUser ? currentUser.name.charAt(0).toUpperCase() : "H"}
      </div>

      <div
        className={cn(
          "flex max-w-[min(720px,80%)] flex-col gap-2",
          isUser && "items-end",
        )}
      >
        {reasoningParts.length > 0 && !isUser && (
          <div className="flex w-full flex-col gap-1">
            {reasoningParts.map((p, i) => (
              <ReasoningBlock
                key={`${message.id}-r-${i}`}
                text={p.text}
              />
            ))}
          </div>
        )}

        {text && (
          <div
            className={cn(
              "rounded-2xl px-4 py-2.5 text-body-sm",
              isUser
                ? "bg-primary text-primary-foreground"
                : "bg-card text-foreground",
            )}
          >
            {isUser ? <p className="whitespace-pre-wrap">{text}</p> : <Markdown>{text}</Markdown>}
          </div>
        )}
      </div>
    </div>
  )
}
