import { KnownPeople } from "@/components/voice/known-people"
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet"
import type { PlaybackMode, Settings, ThemeMode } from "@/lib/types"
import { cn } from "@/lib/utils"

type SettingsPanelProps = {
  open: boolean
  onOpenChange: (open: boolean) => void
  settings: Settings
  onThemeChange: (theme: ThemeMode) => void
  onLanguageChange: (language: string) => void
  onPlaybackChange: (playback: PlaybackMode) => void
}

const THEMES: { label: string; value: ThemeMode }[] = [
  { label: "Light", value: "light" },
  { label: "Dark", value: "dark" },
  { label: "Auto", value: "system" },
]

const LANGUAGES = [
  { label: "Español", value: "es" },
  { label: "English", value: "en" },
  { label: "Português", value: "pt" },
]

const PLAYBACKS: { label: string; value: PlaybackMode }[] = [
  { label: "Browser", value: "private" },
  { label: "Speakers", value: "local" },
]

export function SettingsPanel({
  open,
  onOpenChange,
  settings,
  onThemeChange,
  onLanguageChange,
  onPlaybackChange,
}: SettingsPanelProps) {
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="w-[min(420px,95vw)] overflow-y-auto">
        <SheetHeader>
          <SheetTitle>Settings</SheetTitle>
          <SheetDescription>
            Preferences are stored in your browser only.
          </SheetDescription>
        </SheetHeader>

        <div className="mt-6 flex flex-col gap-6">
          <section>
            <h3 className="eyebrow mb-2">Theme</h3>
            <div className="inline-flex rounded-full border border-border p-1">
              {THEMES.map((t) => (
                <button
                  key={t.value}
                  type="button"
                  onClick={() => onThemeChange(t.value)}
                  className={cn(
                    "rounded-full px-4 py-1 text-sm transition-colors",
                    settings.theme === t.value
                      ? "bg-primary text-primary-foreground"
                      : "text-foreground hover:bg-muted",
                  )}
                >
                  {t.label}
                </button>
              ))}
            </div>
          </section>

          <section>
            <h3 className="eyebrow mb-2">Language</h3>
            <select
              value={settings.language}
              onChange={(e) => onLanguageChange(e.target.value)}
              className="w-full rounded-md border border-border bg-card px-3 py-2 text-sm text-foreground focus:border-primary focus:outline-none"
            >
              {LANGUAGES.map((l) => (
                <option key={l.value} value={l.value}>
                  {l.label}
                </option>
              ))}
            </select>
            <p className="mt-1 text-xs text-muted-foreground">
              Used for voice transcription and default greetings.
            </p>
          </section>

          <section>
            <h3 className="eyebrow mb-2">Voice playback</h3>
            <div className="inline-flex rounded-full border border-border p-1">
              {PLAYBACKS.map((p) => (
                <button
                  key={p.value}
                  type="button"
                  onClick={() => onPlaybackChange(p.value)}
                  className={cn(
                    "rounded-full px-4 py-1 text-sm transition-colors",
                    settings.playback === p.value
                      ? "bg-primary text-primary-foreground"
                      : "text-foreground hover:bg-muted",
                  )}
                >
                  {p.label}
                </button>
              ))}
            </div>
            <p className="mt-1 text-xs text-muted-foreground">
              Browser: assistant audio plays in this tab. Speakers: the server
              hosting Companion speaks instead (useful for kiosk / shared-space
              setups).
            </p>
          </section>

          <section>
            <h3 className="eyebrow mb-2">Known people</h3>
            <KnownPeople />
            <p className="mt-2 text-xs text-muted-foreground">
              Faces enrolled here are recognized in vision mode. The model
              greets them by name when they enter the frame.
            </p>
          </section>
        </div>
      </SheetContent>
    </Sheet>
  )
}
