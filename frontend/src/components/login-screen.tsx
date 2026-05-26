import { useEffect, useState } from "react"
import { Loader2 } from "lucide-react"
import { api } from "@/lib/api"
import type { AppConfig, User } from "@/lib/types"
import { cn } from "@/lib/utils"

type LoginScreenProps = {
  config: AppConfig | null
  onLogin: (userId: string) => Promise<unknown>
}

export function LoginScreen({ config, onLogin }: LoginScreenProps) {
  const [users, setUsers] = useState<User[]>([])
  const [loadingUsers, setLoadingUsers] = useState(true)
  const [submitting, setSubmitting] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    api
      .listUsers()
      .then((list) => {
        if (!cancelled) {
          setUsers(list)
          setLoadingUsers(false)
        }
      })
      .catch((e) => {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : String(e))
          setLoadingUsers(false)
        }
      })
    return () => {
      cancelled = true
    }
  }, [])

  const handlePick = async (userId: string) => {
    setError(null)
    setSubmitting(userId)
    try {
      await onLogin(userId)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      setSubmitting(null)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-background">
      <div className="w-[min(400px,90vw)] p-12 text-center">
        <div className="mx-auto mb-6 flex h-16 w-16 items-center justify-center rounded-full border-2 border-primary font-serif text-2xl text-primary">
          {(config?.assistant_name ?? "C").charAt(0).toUpperCase()}
        </div>
        <h1 className="mb-2 font-serif text-2xl text-foreground">
          {config?.assistant_name ?? "Companion"}
        </h1>
        <p className="mb-8 text-xs tracking-widest text-muted-foreground uppercase">
          {config?.company_name ?? ""}
        </p>

        {loadingUsers ? (
          <div className="flex items-center justify-center py-8 text-muted-foreground">
            <Loader2 className="h-5 w-5 animate-spin" />
          </div>
        ) : (
          <ul className="flex flex-col gap-2">
            {users.map((u) => (
              <li key={u.id}>
                <button
                  type="button"
                  disabled={submitting !== null}
                  onClick={() => handlePick(u.id)}
                  className={cn(
                    "flex w-full items-center gap-4 rounded-lg border border-border bg-card p-4 text-left transition-colors hover:border-primary disabled:opacity-50",
                    u.is_shared_space && "border-dashed",
                    submitting === u.id && "border-primary",
                  )}
                >
                  <div className="flex h-10 w-10 items-center justify-center rounded-full bg-muted text-base font-medium text-foreground">
                    {u.name.charAt(0).toUpperCase()}
                  </div>
                  <div className="flex flex-1 flex-col">
                    <span className="text-foreground">{u.name}</span>
                    {u.role && (
                      <span className="text-xs text-muted-foreground">
                        {u.role}
                      </span>
                    )}
                  </div>
                  {submitting === u.id && (
                    <Loader2 className="h-4 w-4 animate-spin text-primary" />
                  )}
                </button>
              </li>
            ))}
          </ul>
        )}

        {error && (
          <p className="mt-4 text-sm text-destructive" role="alert">
            {error}
          </p>
        )}
      </div>
    </div>
  )
}
