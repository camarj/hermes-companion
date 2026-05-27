import { useEffect, useState } from "react"

const POLL_MS = 30_000

export function useHealth() {
  const [online, setOnline] = useState<boolean | null>(null)

  useEffect(() => {
    let cancelled = false

    const check = async () => {
      try {
        const r = await fetch("/api/health", { credentials: "include" })
        if (!cancelled) setOnline(r.ok)
      } catch {
        if (!cancelled) setOnline(false)
      }
    }

    void check()
    const id = window.setInterval(check, POLL_MS)
    return () => {
      cancelled = true
      window.clearInterval(id)
    }
  }, [])

  return online
}
