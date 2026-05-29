import { useState } from "react"

import { t, type Lang } from "@/lib/i18n"
import type { CreateAgentPayload } from "@/lib/types"

type NewAgentDialogProps = {
  open: boolean
  lang: Lang
  onCreate: (payload: CreateAgentPayload) => void | Promise<void>
  onCancel: () => void
}

const AGENT_TYPES = ["hermes", "openclaw", "custom"] as const
const TRANSPORTS = ["local-acp", "remote-acp"] as const

const inputClass =
  "w-full rounded-md border border-border bg-background px-3 py-2 text-sm text-foreground"
const labelClass =
  "mb-1 block text-xs font-mono uppercase tracking-wider text-muted-foreground"

export function NewAgentDialog({
  open,
  lang,
  onCreate,
  onCancel,
}: NewAgentDialogProps) {
  const i = t(lang)
  const [id, setId] = useState("")
  const [label, setLabel] = useState("")
  const [type, setType] = useState<string>("hermes")
  const [transport, setTransport] = useState<string>("local-acp")
  const [url, setUrl] = useState("")
  const [token, setToken] = useState("")

  if (!open) return null

  const isRemote = transport === "remote-acp"
  const canCreate = id.trim() !== "" && label.trim() !== ""

  const submit = () => {
    if (!canCreate) return
    onCreate({
      id: id.trim(),
      label: label.trim(),
      type,
      transport,
      transport_config: isRemote ? { url: url.trim(), token: token.trim() } : {},
    })
  }

  return (
    <div
      role="dialog"
      aria-label={i.newAgentTitle}
      aria-modal="true"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
    >
      <div className="w-full max-w-md rounded-md border border-border bg-card p-6 shadow-lg">
        <h2 className="mb-2 font-serif text-lg text-foreground">
          {i.newAgentTitle}
        </h2>
        <p className="mb-4 text-sm text-muted-foreground">{i.newAgentHint}</p>

        <div className="mb-3">
          <label className={labelClass} htmlFor="agent-id">
            {i.fieldId}
          </label>
          <input
            id="agent-id"
            aria-label={i.fieldId}
            value={id}
            onChange={(e) => setId(e.target.value)}
            className={inputClass}
          />
        </div>

        <div className="mb-3">
          <label className={labelClass} htmlFor="agent-label">
            {i.fieldLabel}
          </label>
          <input
            id="agent-label"
            aria-label={i.fieldLabel}
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            className={inputClass}
          />
        </div>

        <div className="mb-3">
          <label className={labelClass} htmlFor="agent-type">
            {i.agentType}
          </label>
          <select
            id="agent-type"
            aria-label={i.agentType}
            value={type}
            onChange={(e) => setType(e.target.value)}
            className={inputClass}
          >
            {AGENT_TYPES.map((tp) => (
              <option key={tp} value={tp}>
                {tp}
              </option>
            ))}
          </select>
        </div>

        <div className="mb-3">
          <label className={labelClass} htmlFor="agent-transport">
            {i.transport}
          </label>
          <select
            id="agent-transport"
            aria-label={i.transport}
            value={transport}
            onChange={(e) => setTransport(e.target.value)}
            className={inputClass}
          >
            {TRANSPORTS.map((tr) => (
              <option key={tr} value={tr}>
                {tr}
              </option>
            ))}
          </select>
        </div>

        {isRemote && (
          <>
            <div className="mb-3">
              <label className={labelClass} htmlFor="agent-url">
                {i.fieldUrl}
              </label>
              <input
                id="agent-url"
                aria-label={i.fieldUrl}
                value={url}
                onChange={(e) => setUrl(e.target.value)}
                placeholder="wss://host/api/host/acp"
                className={inputClass}
              />
            </div>
            <div className="mb-3">
              <label className={labelClass} htmlFor="agent-token">
                {i.fieldToken}
              </label>
              <input
                id="agent-token"
                aria-label={i.fieldToken}
                value={token}
                onChange={(e) => setToken(e.target.value)}
                placeholder="env:VPS_HOST_TOKEN"
                className={inputClass}
              />
            </div>
          </>
        )}

        <div className="mt-6 flex items-center justify-end gap-2">
          <button
            type="button"
            onClick={onCancel}
            className="rounded-md border border-border px-4 py-2 text-sm text-muted-foreground hover:bg-muted"
          >
            {i.cancel}
          </button>
          <button
            type="button"
            onClick={submit}
            disabled={!canCreate}
            className="rounded-md bg-primary px-4 py-2 text-sm text-primary-foreground hover:bg-primary/90 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {i.create}
          </button>
        </div>
      </div>
    </div>
  )
}
