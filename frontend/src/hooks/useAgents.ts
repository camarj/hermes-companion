import { useEffect, useState } from "react"

import { api } from "@/lib/api"
import type { AgentInstance } from "@/lib/types"

export function useAgents(): {
  agents: AgentInstance[]
  loading: boolean
  refresh: () => Promise<void>
} {
  const [agents, setAgents] = useState<AgentInstance[]>([])
  const [loading, setLoading] = useState(true)

  const refresh = async () => {
    try {
      const list = await api.listAgents()
      setAgents(list)
    } catch {
      setAgents([])
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void refresh()
  }, [])

  return { agents, loading, refresh }
}
