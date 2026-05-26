import { useEffect, useState } from "react"
import { api } from "@/lib/api"
import type { AppConfig } from "@/lib/types"

export function useAppConfig() {
  const [config, setConfig] = useState<AppConfig | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    api
      .getConfig()
      .then((c) => {
        if (!cancelled) setConfig(c)
      })
      .catch((e) => {
        if (!cancelled) setError(String(e?.message ?? e))
      })
    return () => {
      cancelled = true
    }
  }, [])

  return { config, error }
}
