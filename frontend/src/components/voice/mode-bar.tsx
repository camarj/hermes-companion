import { Loader2, Mic, MicOff } from "lucide-react"
import { t, type Lang } from "@/lib/i18n"
import type { ThemeMode, VoiceMode } from "@/lib/types"
import { cn } from "@/lib/utils"

type ModeBarProps = {
  lang: Lang
  theme: ThemeMode
  mode: VoiceMode
  autoMuted: boolean
  userMuted: boolean
  modeDisabled?: boolean
  onThemeChange: (t: ThemeMode) => void
  onModeChange: (m: VoiceMode) => void
  onToggleMute: () => void
}

type Opt<T extends string> = { value: T; label: string }

function Pill<T extends string>({
  options,
  value,
  onChange,
  disabled,
}: {
  options: Opt<T>[]
  value: T
  onChange: (v: T) => void
  disabled?: boolean
}) {
  return (
    <div
      className={cn(
        "inline-flex items-center rounded-full border border-border p-[2px]",
        disabled && "opacity-50",
      )}
    >
      {options.map((opt) => {
        const active = opt.value === value
        return (
          <button
            key={opt.value}
            type="button"
            disabled={disabled}
            onClick={() => onChange(opt.value)}
            aria-pressed={active}
            className={cn(
              "rounded-full px-3 py-1 font-mono text-[11px] font-medium uppercase tracking-[0.08em] transition-colors",
              active
                ? "bg-primary text-primary-foreground"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            {opt.label}
          </button>
        )
      })}
    </div>
  )
}

export function ModeBar({
  lang,
  theme,
  mode,
  autoMuted,
  userMuted,
  modeDisabled,
  onThemeChange,
  onModeChange,
  onToggleMute,
}: ModeBarProps) {
  const i = t(lang)
  const showMute = mode !== "chat"
  const muteTitle = userMuted
    ? i.micUnmute
    : autoMuted
      ? i.micProcessing
      : i.micMute

  return (
    <div className="flex flex-wrap items-center justify-center gap-2 border-b border-border bg-background px-6 py-2">
      <Label>{i.modeLabelTheme}</Label>
      <Pill<ThemeMode>
        value={theme}
        onChange={onThemeChange}
        options={[
          { value: "light", label: i.themeLight },
          { value: "dark", label: i.themeDark },
          { value: "system", label: i.themeAuto },
        ]}
      />

      <Divider />

      <Label>{i.modeLabelMode}</Label>
      <Pill<VoiceMode>
        value={mode}
        onChange={onModeChange}
        disabled={modeDisabled}
        options={[
          { value: "chat", label: i.modeChat },
          { value: "voice", label: i.modeVoice },
          { value: "vision", label: i.modeVision },
        ]}
      />

      {showMute && (
        <button
          type="button"
          onClick={onToggleMute}
          title={muteTitle}
          aria-label={muteTitle}
          className={cn(
            "ml-1 flex h-7 w-7 items-center justify-center rounded-full border border-border text-muted-foreground transition-colors",
            userMuted && "border-destructive text-destructive",
            autoMuted && !userMuted && "border-amber-500 text-amber-500",
            !userMuted && !autoMuted && "hover:text-foreground",
          )}
        >
          {userMuted ? (
            <MicOff className="h-3.5 w-3.5" />
          ) : autoMuted ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <Mic className="h-3.5 w-3.5" />
          )}
        </button>
      )}
    </div>
  )
}

function Label({ children }: { children: React.ReactNode }) {
  return (
    <span className="font-mono text-[11px] uppercase tracking-[0.12em] text-muted-foreground">
      {children}
    </span>
  )
}

function Divider() {
  return <span className="mx-1 h-3 w-px bg-border" />
}
