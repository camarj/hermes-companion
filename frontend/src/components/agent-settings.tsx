import { useEffect, useState } from "react"

import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet"
import { api } from "@/lib/api"
import { t, type Lang } from "@/lib/i18n"
import type { AgentInstance } from "@/lib/types"

type AgentSettingsProps = {
  open: boolean
  onOpenChange: (open: boolean) => void
  agent: AgentInstance | null
  lang: Lang
  onSaved?: (agent: AgentInstance) => void
}

type InspectionKind = "skills" | "mcp" | "tools" | "config"

type InspectionResult =
  | { state: "loading" }
  | { state: "ok"; output: string }
  | { state: "error"; message: string }

const KINDS: InspectionKind[] = ["skills", "mcp", "tools", "config"]

export function AgentSettings({
  open,
  onOpenChange,
  agent,
  lang,
  onSaved,
}: AgentSettingsProps) {
  const i = t(lang)
  const [sections, setSections] = useState<Record<InspectionKind, InspectionResult>>({
    skills: { state: "loading" },
    mcp: { state: "loading" },
    tools: { state: "loading" },
    config: { state: "loading" },
  })
  const [prompt, setPrompt] = useState<string>("")
  const [saveState, setSaveState] = useState<"idle" | "saving" | "saved" | "error">("idle")

  useEffect(() => {
    if (!open || !agent) return
    setPrompt(agent.system_prompt_override ?? "")
    setSaveState("idle")
    setSections({
      skills: { state: "loading" },
      mcp: { state: "loading" },
      tools: { state: "loading" },
      config: { state: "loading" },
    })
    let cancelled = false
    Promise.all(
      KINDS.map(async (kind) => {
        try {
          const data = await api.getAgentInspection(agent.id, kind)
          if (cancelled) return
          const text =
            data.stdout ||
            (data.exit_code !== 0 ? data.stderr : "") ||
            ""
          setSections((s) => ({ ...s, [kind]: { state: "ok", output: text } }))
        } catch (e) {
          if (cancelled) return
          const message = e instanceof Error ? e.message : i.loadFailed
          setSections((s) => ({ ...s, [kind]: { state: "error", message } }))
        }
      }),
    )
    return () => {
      cancelled = true
    }
  }, [open, agent, i.loadFailed])

  const handleSave = async () => {
    if (!agent) return
    setSaveState("saving")
    try {
      const updated = await api.setAgentSystemPrompt(agent.id, prompt)
      setSaveState("saved")
      onSaved?.(updated)
    } catch {
      setSaveState("error")
    }
  }

  const renderSection = (kind: InspectionKind, label: string) => {
    const s = sections[kind]
    return (
      <section key={kind}>
        <h3 className="mb-2 font-mono text-[11px] uppercase tracking-[0.12em] text-muted-foreground">
          {label}
        </h3>
        {s.state === "loading" && (
          <p className="text-sm text-muted-foreground">…</p>
        )}
        {s.state === "ok" && (
          <pre
            data-testid={`inspection-${kind}`}
            className="max-h-48 overflow-y-auto rounded-md border border-border bg-muted/50 p-3 font-mono text-xs text-foreground"
          >
            {s.output || "—"}
          </pre>
        )}
        {s.state === "error" && (
          <p className="text-sm text-destructive">{s.message}</p>
        )}
      </section>
    )
  }

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent
        side="right"
        className="w-[min(520px,95vw)] overflow-y-auto"
      >
        <SheetHeader>
          <SheetTitle>
            {i.agentSettings}
            {agent && (
              <span className="ml-2 text-sm text-muted-foreground">
                {agent.label}
              </span>
            )}
          </SheetTitle>
          <SheetDescription>{i.systemPromptHint}</SheetDescription>
        </SheetHeader>

        <div className="mt-6 flex flex-col gap-6">
          <section>
            <h3 className="mb-2 font-mono text-[11px] uppercase tracking-[0.12em] text-muted-foreground">
              {i.systemPrompt}
            </h3>
            <textarea
              aria-label={i.systemPrompt}
              value={prompt}
              onChange={(e) => {
                setPrompt(e.target.value)
                setSaveState("idle")
              }}
              className="min-h-[140px] w-full rounded-md border border-border bg-card px-3 py-2 font-mono text-sm text-foreground focus:border-primary focus:outline-none"
              placeholder=""
            />
            <div className="mt-2 flex items-center gap-2">
              <button
                type="button"
                onClick={handleSave}
                disabled={saveState === "saving" || !agent}
                className="rounded-md bg-primary px-4 py-2 text-sm text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
              >
                {saveState === "saving" ? i.saving : i.save}
              </button>
              {saveState === "saved" && (
                <span className="text-xs text-muted-foreground">{i.saved}</span>
              )}
              {saveState === "error" && (
                <span className="text-xs text-destructive">{i.saveFailed}</span>
              )}
            </div>
          </section>

          {renderSection("skills", i.skillsSection)}
          {renderSection("mcp", i.mcpSection)}
          {renderSection("tools", i.toolsSection)}
          {renderSection("config", i.configSection)}
        </div>
      </SheetContent>
    </Sheet>
  )
}
