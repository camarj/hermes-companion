import { cn } from "@/lib/utils"

type Props = {
  connecting: boolean
  connected: boolean
  autoMuted: boolean
  userMuted: boolean
}

export function RealtimeIndicator({
  connecting,
  connected,
  autoMuted,
  userMuted,
}: Props) {
  if (!connecting && !connected) return null
  const label = connecting
    ? "CONNECTING"
    : userMuted
      ? "MIC OFF"
      : autoMuted
        ? "PROCESSING"
        : "LIVE"
  return (
    <div className="flex items-center gap-2 rounded-full border border-border bg-card px-3 py-1 text-xs uppercase tracking-wider">
      <span
        className={cn(
          "h-2 w-2 rounded-full",
          connecting && "bg-muted-foreground animate-pulse",
          !connecting && userMuted && "bg-destructive",
          !connecting && !userMuted && autoMuted && "bg-amber-500",
          !connecting && !userMuted && !autoMuted && "bg-emerald-500 animate-pulse",
        )}
      />
      <span className="text-foreground">{label}</span>
    </div>
  )
}
