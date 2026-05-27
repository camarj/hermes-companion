import { useEffect, useState } from "react"

import { t, type Lang } from "@/lib/i18n"
import type { AgentInstance } from "@/lib/types"

type NewConversationDialogProps = {
  open: boolean
  agents: AgentInstance[]
  lang: Lang
  onSelect: (agentId: string) => void
  onCancel: () => void
}

export function NewConversationDialog({
  open,
  agents,
  lang,
  onSelect,
  onCancel,
}: NewConversationDialogProps) {
  const i = t(lang)
  const enabled = agents.filter((a) => a.enabled)
  const single = enabled.length === 1 ? enabled[0] : null
  const [picked, setPicked] = useState<string>(enabled[0]?.id ?? "")

  useEffect(() => {
    if (open && single) {
      onSelect(single.id)
    }
  }, [open, single, onSelect])

  useEffect(() => {
    if (open && enabled.length >= 2 && !picked) {
      setPicked(enabled[0].id)
    }
  }, [open, enabled, picked])

  if (!open || enabled.length < 2) return null

  return (
    <div
      role="dialog"
      aria-label={i.newConversation}
      aria-modal="true"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
    >
      <div className="w-full max-w-md rounded-md border border-border bg-card p-6 shadow-lg">
        <h2 className="mb-2 font-serif text-lg text-foreground">
          {i.newConversation}
        </h2>
        <p className="mb-4 text-sm text-muted-foreground">
          {i.pickAgent}
        </p>

        <label className="mb-1 block text-xs font-mono uppercase tracking-wider text-muted-foreground">
          {i.agent}
        </label>
        <select
          aria-label={i.agent}
          value={picked}
          onChange={(e) => setPicked(e.target.value)}
          className="mb-6 w-full rounded-md border border-border bg-background px-3 py-2 text-sm text-foreground"
        >
          {enabled.map((a) => (
            <option key={a.id} value={a.id}>
              {a.label}
            </option>
          ))}
        </select>

        <div className="flex items-center justify-end gap-2">
          <button
            type="button"
            onClick={onCancel}
            className="rounded-md border border-border px-4 py-2 text-sm text-muted-foreground hover:bg-muted"
          >
            {i.cancel}
          </button>
          <button
            type="button"
            onClick={() => onSelect(picked)}
            className="rounded-md bg-primary px-4 py-2 text-sm text-primary-foreground hover:bg-primary/90"
          >
            {i.create}
          </button>
        </div>
      </div>
    </div>
  )
}
