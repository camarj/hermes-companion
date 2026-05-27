import { useMemo, useState } from "react"
import { LogOut, Menu, Plus, Settings as SettingsIcon, Trash2 } from "lucide-react"
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import { t, type Lang } from "@/lib/i18n"
import type { AgentInstance, AppConfig, Conversation, User } from "@/lib/types"
import { cn } from "@/lib/utils"

type SidebarProps = {
  config: AppConfig | null
  user: User
  conversations: Conversation[]
  agents?: AgentInstance[]
  activeId: string | null
  lang: Lang
  onSelect: (id: string) => void
  onNew: () => void
  onDelete: (id: string) => Promise<unknown> | unknown
  onLogout: () => void
  onToggle?: () => void
  onOpenAgentSettings?: (agentId: string) => void
}

type AgentGroup = {
  agentId: string | null
  label: string
  badgeColor: string
  conversations: Conversation[]
}

const BADGE_PALETTE = [
  "#7c3aed",
  "#0ea5e9",
  "#10b981",
  "#f59e0b",
  "#ef4444",
  "#ec4899",
  "#14b8a6",
  "#6366f1",
] as const

export function agentBadgeColor(agentId: string | null): string {
  if (!agentId) return "#94a3b8"
  let hash = 0
  for (let i = 0; i < agentId.length; i += 1) {
    hash = (hash * 31 + agentId.charCodeAt(i)) >>> 0
  }
  return BADGE_PALETTE[hash % BADGE_PALETTE.length]
}

function groupByAgent(
  list: Conversation[],
  agents: AgentInstance[],
  unassignedLabel: string,
): AgentGroup[] {
  const labelById = new Map(agents.map((a) => [a.id, a.label]))
  const groups = new Map<string | null, AgentGroup>()
  for (const c of list) {
    const aid = c.agent_id ?? null
    const key = aid ?? "__unassigned__"
    let group = groups.get(key)
    if (!group) {
      group = {
        agentId: aid,
        label: aid ? labelById.get(aid) ?? aid : unassignedLabel,
        badgeColor: agentBadgeColor(aid),
        conversations: [],
      }
      groups.set(key, group)
    }
    group.conversations.push(c)
  }
  // Stable order: agents in their registry order first, unassigned last.
  const ordered: AgentGroup[] = []
  for (const a of agents) {
    const g = groups.get(a.id)
    if (g) ordered.push(g)
  }
  const tail = groups.get("__unassigned__")
  if (tail) ordered.push(tail)
  // Any agent_id we don't have in the registry (deleted?) — append.
  for (const [key, g] of groups) {
    if (key !== "__unassigned__" && !agents.some((a) => a.id === key)) {
      ordered.push(g)
    }
  }
  return ordered
}

export function Sidebar({
  config,
  user,
  conversations,
  agents = [],
  activeId,
  lang,
  onSelect,
  onNew,
  onDelete,
  onLogout,
  onToggle,
  onOpenAgentSettings,
}: SidebarProps) {
  const i = t(lang)
  const [pendingDelete, setPendingDelete] = useState<Conversation | null>(null)
  const groups = useMemo(
    () => groupByAgent(conversations, agents, i.unassignedAgent),
    [conversations, agents, i.unassignedAgent],
  )
  const name = config?.assistant_name ?? "Companion"
  const letter = (name[0] ?? "C").toUpperCase()

  const renderGroup = (group: AgentGroup) => {
    if (group.conversations.length === 0) return null
    return (
      <div key={group.agentId ?? "__unassigned__"} className="pt-4 pb-1">
        <div className="flex items-center gap-2 px-4 pb-1.5 font-mono text-[11px] uppercase tracking-[0.12em] text-muted-foreground">
          <span
            data-testid={`agent-badge-${group.agentId ?? "unassigned"}`}
            aria-hidden="true"
            className="inline-block h-2 w-2 rounded-full"
            style={{ backgroundColor: group.badgeColor }}
          />
          <span className="flex-1 truncate">{group.label}</span>
          {group.agentId && onOpenAgentSettings && (
            <button
              type="button"
              onClick={() => onOpenAgentSettings(group.agentId!)}
              aria-label={i.agentSettingsAria}
              className="rounded p-1 text-muted-foreground transition-colors hover:text-foreground"
            >
              <SettingsIcon className="h-3 w-3" />
            </button>
          )}
        </div>
        <ul className="flex flex-col gap-px">
          {group.conversations.map((c) => {
            const isActive = activeId === c.id
            return (
              <li key={c.id} className="px-2">
                <div
                  className={cn(
                    "group flex items-center gap-2 rounded-md px-3 py-2 text-sm transition-colors",
                    isActive
                      ? "bg-primary/10 text-primary"
                      : "text-muted-foreground hover:bg-muted",
                  )}
                >
                  <span
                    data-testid={`conv-badge-${c.id}`}
                    aria-hidden="true"
                    className="inline-block h-1.5 w-1.5 flex-shrink-0 rounded-full"
                    style={{ backgroundColor: group.badgeColor }}
                  />
                  <button
                    type="button"
                    onClick={() => onSelect(c.id)}
                    className="flex-1 truncate text-left"
                    title={c.title}
                  >
                    {c.title || i.newConversation}
                  </button>
                  <button
                    type="button"
                    onClick={() => setPendingDelete(c)}
                    className="rounded p-1 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100 hover:text-destructive"
                    aria-label={i.delete}
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>
              </li>
            )
          })}
        </ul>
      </div>
    )
  }

  return (
    <>
      <aside className="flex h-full w-[var(--sidebar-w)] flex-col border-r border-border bg-card">
        {/* Brand row */}
        <div className="flex items-center gap-3 border-b border-border px-4 py-4">
          <div className="flex h-8 w-8 items-center justify-center rounded-full border border-primary font-serif text-primary">
            {letter}
          </div>
          <div className="flex-1 truncate font-serif text-lg text-foreground">
            {name}
          </div>
          {onToggle && (
            <button
              type="button"
              onClick={onToggle}
              className="rounded p-1 text-muted-foreground transition-colors hover:text-foreground"
              aria-label={i.closeMenu}
            >
              <Menu className="h-4 w-4" />
            </button>
          )}
        </div>

        {/* New conversation button */}
        <div className="px-4 py-3">
          <button
            type="button"
            onClick={onNew}
            className="flex w-full items-center justify-center gap-2 rounded-md border border-dashed border-border bg-transparent px-3 py-2 text-sm text-muted-foreground transition-colors hover:border-primary hover:bg-primary/5 hover:text-primary"
          >
            <Plus className="h-3.5 w-3.5" />
            <span>{i.newConversation}</span>
          </button>
        </div>

        {/* Current user pill */}
        <div className="flex items-center gap-2 border-b border-border px-4 py-2 font-mono text-[11px] uppercase tracking-[0.08em] text-muted-foreground">
          <span className="h-1.5 w-1.5 rounded-full bg-primary" />
          <span className="truncate">{user.name}</span>
        </div>

        {/* Conversation list */}
        <nav className="flex-1 overflow-y-auto py-1">
          {groups.map(renderGroup)}
          {conversations.length === 0 && (
            <p className="px-6 py-8 text-center text-sm text-muted-foreground">
              {i.noConversations}
            </p>
          )}
        </nav>

        {/* Footer */}
        <div className="flex items-center justify-between border-t border-border px-4 py-3">
          <span className="truncate font-mono text-[11px] uppercase tracking-[0.08em] text-muted-foreground">
            {user.name}
          </span>
          <button
            type="button"
            onClick={onLogout}
            className="rounded p-1 text-muted-foreground transition-colors hover:text-foreground"
            aria-label={i.logout}
            title={i.logout}
          >
            <LogOut className="h-4 w-4" />
          </button>
        </div>
      </aside>

      <AlertDialog
        open={pendingDelete !== null}
        onOpenChange={(open) => !open && setPendingDelete(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{i.deleteConversationTitle}</AlertDialogTitle>
            <AlertDialogDescription>
              {i.deleteConversationBody(pendingDelete?.title || i.newConversation)}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{i.cancel}</AlertDialogCancel>
            <AlertDialogAction
              onClick={async () => {
                if (!pendingDelete) return
                await onDelete(pendingDelete.id)
                setPendingDelete(null)
              }}
            >
              {i.delete}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  )
}
