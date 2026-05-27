import { Loader2, Mic, MicOff } from "lucide-react"
import { cn } from "@/lib/utils"

type Props = {
  autoMuted: boolean
  userMuted: boolean
  onClick: () => void
}

export function MuteButton({ autoMuted, userMuted, onClick }: Props) {
  const title = userMuted
    ? "Unmute microphone"
    : autoMuted
      ? "Processing — click to force mic on"
      : "Mute microphone"
  return (
    <button
      type="button"
      onClick={onClick}
      title={title}
      aria-label={title}
      className={cn(
        "flex h-9 w-9 items-center justify-center rounded-full border border-border bg-card text-foreground transition-colors",
        userMuted && "border-destructive text-destructive",
        autoMuted && !userMuted && "border-amber-500 text-amber-500",
        !userMuted && !autoMuted && "hover:bg-muted",
      )}
    >
      {userMuted ? (
        <MicOff className="h-4 w-4" />
      ) : autoMuted ? (
        <Loader2 className="h-4 w-4 animate-spin" />
      ) : (
        <Mic className="h-4 w-4" />
      )}
    </button>
  )
}
