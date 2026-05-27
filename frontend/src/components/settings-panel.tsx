import { KnownPeople } from "@/components/voice/known-people"
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet"
import { t, type Lang } from "@/lib/i18n"
import type { Settings } from "@/lib/types"

type SettingsPanelProps = {
  open: boolean
  onOpenChange: (open: boolean) => void
  settings: Settings
  lang: Lang
  onLanguageChange: (language: string) => void
}

const LANGUAGES = [
  { label: "Español", value: "es" },
  { label: "English", value: "en" },
  { label: "Português", value: "pt" },
]

export function SettingsPanel({
  open,
  onOpenChange,
  settings,
  lang,
  onLanguageChange,
}: SettingsPanelProps) {
  const i = t(lang)
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="w-[min(420px,95vw)] overflow-y-auto">
        <SheetHeader>
          <SheetTitle>{i.settings}</SheetTitle>
          <SheetDescription>
            {lang === "es"
              ? "Las preferencias se guardan en este navegador."
              : lang === "pt"
                ? "As preferências são salvas neste navegador."
                : "Preferences are stored in your browser only."}
          </SheetDescription>
        </SheetHeader>

        <div className="mt-6 flex flex-col gap-6">
          <section>
            <h3 className="mb-2 font-mono text-[11px] uppercase tracking-[0.12em] text-muted-foreground">
              {i.language}
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
          </section>

          <section>
            <h3 className="mb-2 font-mono text-[11px] uppercase tracking-[0.12em] text-muted-foreground">
              {i.knownPeople}
            </h3>
            <KnownPeople lang={lang} />
            <p className="mt-2 text-xs text-muted-foreground">
              {i.knownPeopleHint}
            </p>
          </section>
        </div>
      </SheetContent>
    </Sheet>
  )
}
