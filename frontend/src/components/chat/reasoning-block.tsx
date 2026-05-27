import { ChevronRight } from "lucide-react"
import { useState } from "react"
import { Markdown } from "./markdown"
import { cn } from "@/lib/utils"

type ReasoningBlockProps = {
  text: string
}

/**
 * Collapsible chain-of-thought block.
 *
 * Backed by `reasoning` parts emitted by the AI SDK 6 protocol. Default is
 * collapsed because intermediate reasoning shouldn't compete visually with
 * the final answer — but it's one click away so the user can verify what
 * the agent was thinking.
 */
export function ReasoningBlock({ text }: ReasoningBlockProps) {
  const [open, setOpen] = useState(false)

  return (
    <div className="rounded-md border border-rule-soft bg-muted/40">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs tracking-wide text-muted-foreground uppercase transition-colors hover:text-foreground"
      >
        <ChevronRight
          className={cn(
            "h-3.5 w-3.5 transition-transform",
            open && "rotate-90",
          )}
        />
        Thinking
      </button>
      {open && (
        <div className="border-t border-rule-soft px-4 pt-2 pb-3 text-sm text-muted-foreground">
          <Markdown>{text}</Markdown>
        </div>
      )}
    </div>
  )
}
