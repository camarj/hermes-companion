import { useCallback, useEffect, useState } from "react"
import { api } from "@/lib/api"
import type { Conversation } from "@/lib/types"

/**
 * Conversation list state + CRUD wrappers.
 *
 * The list is fetched once when a logged-in user is provided; mutations
 * (create, rename, delete) update the list optimistically where it's safe,
 * otherwise they refresh from the server after the request settles.
 */
export function useConversations(enabled: boolean) {
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    if (!enabled) return
    setLoading(true)
    setError(null)
    try {
      const list = await api.listConversations()
      setConversations(list)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }, [enabled])

  useEffect(() => {
    void refresh()
  }, [refresh])

  const create = useCallback(async () => {
    const conv = await api.createConversation()
    setConversations((prev) => [conv, ...prev])
    return conv
  }, [])

  const remove = useCallback(async (id: string) => {
    await api.deleteConversation(id)
    setConversations((prev) => prev.filter((c) => c.id !== id))
  }, [])

  const rename = useCallback(async (id: string, title: string) => {
    await api.renameConversation(id, title)
    setConversations((prev) =>
      prev.map((c) => (c.id === id ? { ...c, title } : c)),
    )
  }, [])

  return { conversations, loading, error, refresh, create, remove, rename }
}
