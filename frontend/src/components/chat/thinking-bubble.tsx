import { cn } from "@/lib/utils"

type ThinkingBubbleProps = {
  label: string
  query: string
}

/**
 * Three pulsing dots in a bubble — Claude-style "thinking" indicator.
 * Shown while a `call_agent` tool call is in flight (between
 * `tool-input-available` and `tool-output-available` in the AI SDK 6 stream,
 * or between companion.tool_started/finished in realtime mode).
 *
 * `label` and `query` are kept on the props for back-compat; only `label`
 * surfaces as a subtle tooltip — we deliberately don't dump the full query
 * into the UI anymore (the user just typed it; restating it is noise).
 */
export function ThinkingBubble({ label, query }: ThinkingBubbleProps) {
  const title = query
    ? `Consultando ${label}: ${query}`
    : `Consultando ${label}…`
  return (
    <div className="flex items-start gap-3" title={title}>
      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full border border-primary text-xs text-primary">
        H
      </div>
      <div className="flex h-9 items-center gap-1.5 rounded-2xl bg-card px-4">
        <Dot delay="0ms" />
        <Dot delay="160ms" />
        <Dot delay="320ms" />
      </div>
    </div>
  )
}

function Dot({ delay }: { delay: string }) {
  return (
    <span
      className={cn(
        "h-1.5 w-1.5 rounded-full bg-muted-foreground/70",
        "animate-[thinkingPulse_1.2s_ease-in-out_infinite]",
      )}
      style={{ animationDelay: delay }}
    />
  )
}
