import { useMemo, useState } from "react"
import { Plus, Trash2, LogOut } from "lucide-react"
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
import { Button } from "@/components/ui/button"
import type { AppConfig, Conversation, User } from "@/lib/types"
import { cn } from "@/lib/utils"

type SidebarProps = {
  config: AppConfig | null
  user: User
  conversations: Conversation[]
  activeId: string | null
  onSelect: (id: string) => void
  onNew: () => void
  onDelete: (id: string) => Promise<unknown> | unknown
  onLogout: () => void
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
  onSelect,
  onNew,
  onDelete,
  onLogout,
}: SidebarProps) {
  const [pendingDelete, setPendingDelete] = useState<Conversation | null>(null)
  const grouped = useMemo(() => groupByDate(conversations), [conversations])

  const renderGroup = (label: string, items: Conversation[]) => {
    if (items.length === 0) return null
    return (
      <div className="px-2 pt-3 pb-1">
        <div className="px-2 pb-1 text-[0.6875rem] tracking-widest text-muted-foreground uppercase">
          {label}
        </div>
        <ul className="flex flex-col gap-px">
          {items.map((c) => (
            <li key={c.id}>
              <div
                className={cn(
                  "group flex items-center gap-2 rounded-md px-3 py-2 text-sm transition-colors",
                  activeId === c.id
                    ? "bg-muted text-foreground"
                    : "text-foreground/90 hover:bg-muted/60",
                )}
              >
                <button
                  type="button"
                  onClick={() => onSelect(c.id)}
                  className="flex-1 truncate text-left"
                  title={c.title}
                >
                  {c.title || "Untitled"}
                </button>
                <button
                  type="button"
                  onClick={() => setPendingDelete(c)}
                  className="rounded p-1 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100 hover:text-destructive"
                  aria-label="Delete conversation"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </div>
            </li>
          ))}
        </ul>
      </div>
    )
  }

  return (
    <>
      <aside className="flex h-full w-[var(--sidebar-w)] flex-col border-r border-border bg-card">
        <div className="flex items-center gap-3 px-4 py-4">
          <div className="flex h-8 w-8 items-center justify-center rounded-full border border-primary font-serif text-primary">
            {(config?.assistant_name ?? "C").charAt(0).toUpperCase()}
          </div>
          <div className="font-serif text-lg text-foreground">
            {config?.assistant_name ?? "Companion"}
          </div>
        </div>

        <div className="px-3">
          <Button
            variant="outline"
            className="w-full justify-start gap-2"
            onClick={onNew}
          >
            <Plus className="h-4 w-4" />
            New conversation
          </Button>
        </div>

        <nav className="mt-2 flex-1 overflow-y-auto">
          {renderGroup("Today", grouped.today)}
          {renderGroup("Yesterday", grouped.yesterday)}
          {renderGroup("Older", grouped.older)}
          {conversations.length === 0 && (
            <p className="px-6 py-8 text-center text-sm text-muted-foreground">
              No conversations yet.
            </p>
          )}
        </nav>

        <div className="flex items-center justify-between border-t border-border px-4 py-3">
          <div className="flex items-center gap-2 text-sm text-foreground">
            <div className="flex h-6 w-6 items-center justify-center rounded-full bg-muted text-xs">
              {user.name.charAt(0).toUpperCase()}
            </div>
            <span>{user.name}</span>
          </div>
          <button
            type="button"
            onClick={onLogout}
            className="rounded p-1 text-muted-foreground hover:text-foreground"
            aria-label="Log out"
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
            <AlertDialogTitle>Delete conversation?</AlertDialogTitle>
            <AlertDialogDescription>
              {`"${pendingDelete?.title || "Untitled"}" will be permanently deleted along with its messages.`}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={async () => {
                if (!pendingDelete) return
                await onDelete(pendingDelete.id)
                setPendingDelete(null)
              }}
            >
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  )
}
