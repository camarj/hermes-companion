import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet"
import type { Settings, ThemeMode } from "@/lib/types"
import { cn } from "@/lib/utils"

type SettingsPanelProps = {
  open: boolean
  onOpenChange: (open: boolean) => void
  settings: Settings
  onThemeChange: (theme: ThemeMode) => void
  onLanguageChange: (language: string) => void
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

export function SettingsPanel({
  open,
  onOpenChange,
  settings,
  onThemeChange,
  onLanguageChange,
}: SettingsPanelProps) {
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="w-[min(420px,95vw)]">
        <SheetHeader>
          <SheetTitle>Settings</SheetTitle>
          <SheetDescription>
            Preferences are stored in your browser only.
          </SheetDescription>
        </SheetHeader>

        <div className="mt-6 flex flex-col gap-6">
          <section>
            <h3 className="mb-2 text-xs tracking-widest text-muted-foreground uppercase">
              Theme
            </h3>
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
            <h3 className="mb-2 text-xs tracking-widest text-muted-foreground uppercase">
              Language
            </h3>
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
              Used for voice transcription and default greetings. The server's
              config.yaml is the source of truth — this is just a UI hint until
              the chat is wired up in a later PR.
            </p>
          </section>

          <section>
            <h3 className="mb-2 text-xs tracking-widest text-muted-foreground uppercase">
              Known people
            </h3>
            <p className="text-sm text-muted-foreground">
              Face enrollment will be available once the vision mode is ported
              (migration PR 5).
            </p>
          </section>
        </div>
      </SheetContent>
    </Sheet>
  )
}
