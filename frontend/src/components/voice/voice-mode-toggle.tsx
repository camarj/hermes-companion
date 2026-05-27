import { Eye, MessageSquare, Mic } from "lucide-react"
import type { VoiceMode } from "@/lib/types"
import { cn } from "@/lib/utils"

type Props = {
  mode: VoiceMode
  onChange: (mode: VoiceMode) => void
  disabled?: boolean
}

const OPTIONS: { value: VoiceMode; label: string; icon: typeof MessageSquare }[] = [
  { value: "chat", label: "Chat", icon: MessageSquare },
  { value: "voice", label: "Voice", icon: Mic },
  { value: "vision", label: "Vision", icon: Eye },
]

export function VoiceModeToggle({ mode, onChange, disabled }: Props) {
  return (
    <div
      className={cn(
        "inline-flex items-center gap-0.5 rounded-full border border-border bg-card p-1",
        disabled && "opacity-50",
      )}
    >
      {OPTIONS.map((opt) => {
        const Icon = opt.icon
        const active = mode === opt.value
        return (
          <button
            key={opt.value}
            type="button"
            disabled={disabled}
            onClick={() => onChange(opt.value)}
            aria-pressed={active}
            className={cn(
              "flex items-center gap-1.5 rounded-full px-3 py-1 text-xs uppercase tracking-wider transition-colors",
              active
                ? "bg-primary text-primary-foreground"
                : "text-muted-foreground hover:bg-muted hover:text-foreground",
            )}
          >
            <Icon className="h-3.5 w-3.5" />
            <span className="hidden sm:inline">{opt.label}</span>
          </button>
        )
      })}
    </div>
  )
}
