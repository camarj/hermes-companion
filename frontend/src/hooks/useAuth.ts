import { useCallback, useEffect, useState } from "react"
import { api } from "@/lib/api"
import type { User } from "@/lib/types"

type AuthState = {
  user: User | null
  status: "loading" | "anonymous" | "authenticated"
}

export function useAuth() {
  const [state, setState] = useState<AuthState>({ user: null, status: "loading" })

  useEffect(() => {
    let cancelled = false
    api
      .me()
      .then((u) => {
        if (cancelled) return
        setState({ user: u, status: u ? "authenticated" : "anonymous" })
      })
      .catch(() => {
        if (cancelled) return
        setState({ user: null, status: "anonymous" })
      })
    return () => {
      cancelled = true
    }
  }, [])

  const login = useCallback(async (userId: string) => {
    const user = await api.login(userId)
    setState({ user, status: "authenticated" })
    return user
  }, [])

  const logout = useCallback(async () => {
    await api.logout()
    setState({ user: null, status: "anonymous" })
  }, [])

  return { ...state, login, logout }
}
