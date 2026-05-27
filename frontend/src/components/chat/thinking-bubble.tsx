import { useEffect, useState } from "react"
import { Loader2 } from "lucide-react"

type ThinkingBubbleProps = {
  label: string
  query: string
}

/**
 * "Querying <agent>…" indicator with elapsed seconds counter. Shown while a
 * tool call is in flight (i.e. between `tool-input-available` and
 * `tool-output-available` in the AI SDK 6 stream).
 */
export function ThinkingBubble({ label, query }: ThinkingBubbleProps) {
  const [elapsed, setElapsed] = useState(0)

  useEffect(() => {
    const start = Date.now()
    const id = window.setInterval(() => {
      setElapsed(Math.floor((Date.now() - start) / 1000))
    }, 500)
    return () => window.clearInterval(id)
  }, [])

  return (
    <div className="flex items-start gap-3">
      <div className="flex h-8 w-8 items-center justify-center rounded-full border border-primary text-xs text-primary">
        H
      </div>
      <div className="flex-1 rounded-md border border-dashed border-rule px-4 py-3 text-sm text-muted-foreground">
        <div className="flex items-center gap-2">
          <Loader2 className="h-4 w-4 animate-spin" />
          <span>
            Querying {label}
            <span className="ml-2 font-mono text-xs text-fg-subtle">
              {elapsed}s
            </span>
          </span>
        </div>
        {query && (
          <p className="mt-2 truncate text-xs text-fg-subtle">{query}</p>
        )}
      </div>
    </div>
  )
}
