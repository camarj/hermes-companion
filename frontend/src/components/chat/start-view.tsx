import { ChatInput } from "./chat-input"
import { t, type Lang } from "@/lib/i18n"
import type { AppConfig } from "@/lib/types"

type Props = {
  config: AppConfig | null
  lang: Lang
  onSend: (text: string) => void
  inputDisabled?: boolean
  hintOverride?: string
}

/**
 * Empty-state ("new conversation") view: centered eyebrow + serif h1 with
 * accent-colored italic assistant name + subtitle + big input. Mirrors the
 * legacy `.start-view` layout (frontend/static/index.html lines 759-768).
 */
export function StartView({
  config,
  lang,
  onSend,
  inputDisabled,
  hintOverride,
}: Props) {
  const i = t(lang)
  const name = config?.assistant_name ?? "Companion"
  const eyebrow = config?.company_name
    ? `${i.assistant.toUpperCase()} · ${config.company_name.toUpperCase()}`
    : i.assistant.toUpperCase()

  return (
    <div className="flex flex-1 flex-col items-center justify-center px-8 py-12 text-center">
      <p className="font-mono text-[11px] uppercase tracking-[0.12em] text-muted-foreground">
        {eyebrow}
      </p>
      <h2 className="mt-3 font-serif text-3xl font-normal tracking-tight text-foreground">
        {i.greetingPrefix}{" "}
        <em className="italic text-primary">{name}</em>
      </h2>
      <p className="mt-4 mb-8 max-w-[420px] text-sm leading-[1.65] text-muted-foreground">
        {hintOverride ?? i.startSubtitle}
      </p>

      <div className="w-full max-w-[600px]">
        <ChatInput
          onSend={onSend}
          disabled={inputDisabled}
          placeholder={i.inputPlaceholder}
          autoFocus
        />
      </div>
    </div>
  )
}
