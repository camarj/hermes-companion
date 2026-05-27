import { useMemo, useState } from "react"
import { LogOut, Menu, Plus, Trash2 } from "lucide-react"
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
import type { AppConfig, Conversation, User } from "@/lib/types"
import { cn } from "@/lib/utils"

type SidebarProps = {
  config: AppConfig | null
  user: User
  conversations: Conversation[]
  activeId: string | null
  lang: Lang
  onSelect: (id: string) => void
  onNew: () => void
  onDelete: (id: string) => Promise<unknown> | unknown
  onLogout: () => void
  onToggle?: () => void
}

type Grouped = {
  today: Conversation[]
  yesterday: Conversation[]
  older: Conversation[]
}

function groupByDate(list: Conversation[]): Grouped {
  const now = new Date()
  const startOfDay = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  const startOfYesterday = new Date(startOfDay.getTime() - 24 * 60 * 60 * 1000)
  const grouped: Grouped = { today: [], yesterday: [], older: [] }
  for (const c of list) {
    const updated = new Date(c.updated_at)
    if (updated >= startOfDay) grouped.today.push(c)
    else if (updated >= startOfYesterday) grouped.yesterday.push(c)
    else grouped.older.push(c)
  }
  return grouped
}

export function Sidebar({
  config,
  user,
  conversations,
  activeId,
  lang,
  onSelect,
  onNew,
  onDelete,
  onLogout,
  onToggle,
}: SidebarProps) {
  const i = t(lang)
  const [pendingDelete, setPendingDelete] = useState<Conversation | null>(null)
  const grouped = useMemo(() => groupByDate(conversations), [conversations])
  const name = config?.assistant_name ?? "Companion"
  const letter = (name[0] ?? "C").toUpperCase()

  const renderGroup = (label: string, items: Conversation[]) => {
    if (items.length === 0) return null
    return (
      <div className="pt-4 pb-1">
        <div className="px-4 pb-1.5 font-mono text-[11px] uppercase tracking-[0.12em] text-muted-foreground">
          {label}
        </div>
        <ul className="flex flex-col gap-px">
          {items.map((c) => {
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
          {renderGroup(i.groupToday, grouped.today)}
          {renderGroup(i.groupYesterday, grouped.yesterday)}
          {renderGroup(i.groupOlder, grouped.older)}
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
