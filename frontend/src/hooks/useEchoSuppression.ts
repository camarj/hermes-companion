import { useCallback, useEffect, useMemo, useRef, useState } from "react"

// agent.timeout_seconds = 180 server-side; give the round-trip a bit of headroom.
const WATCHDOG_MS = 200_000

type Options = {
  onWatchdog?: () => void
}

/**
 * Two independent mute flags so the user can override the auto-mute:
 *   - autoMuted: set when a server-side tool call is in flight
 *   - userMuted: set by the manual mute button
 * Effective mute = autoMuted || userMuted.
 *
 * The watchdog covers the case where the backend never emits
 * companion.tool_finished (network drop, agent crash) — we don't want the user
 * stuck unable to talk.
 */
export function useEchoSuppression({ onWatchdog }: Options = {}) {
  const [autoMuted, setAutoMuted] = useState(false)
  const [userMuted, setUserMuted] = useState(false)
  const watchdogRef = useRef<number | null>(null)
  const autoMutedRef = useRef(false)
  const userMutedRef = useRef(false)
  useEffect(() => {
    autoMutedRef.current = autoMuted
  }, [autoMuted])
  useEffect(() => {
    userMutedRef.current = userMuted
  }, [userMuted])
  const cbRef = useRef(onWatchdog)
  useEffect(() => {
    cbRef.current = onWatchdog
  }, [onWatchdog])

  const clearWatchdog = useCallback(() => {
    if (watchdogRef.current !== null) {
      window.clearTimeout(watchdogRef.current)
      watchdogRef.current = null
    }
  }, [])

  const autoMuteOn = useCallback(
    (reason: string) => {
      if (autoMutedRef.current) return
      console.log("[realtime] auto-mute on —", reason)
      setAutoMuted(true)
      clearWatchdog()
      watchdogRef.current = window.setTimeout(() => {
        console.warn("[realtime] mute watchdog fired — forcing off")
        setAutoMuted(false)
        cbRef.current?.()
      }, WATCHDOG_MS)
    },
    [clearWatchdog],
  )

  const autoMuteOff = useCallback(
    (reason: string) => {
      clearWatchdog()
      if (!autoMutedRef.current) return
      console.log("[realtime] auto-mute off —", reason)
      setAutoMuted(false)
    },
    [clearWatchdog],
  )

  const toggleUserMute = useCallback(() => {
    setUserMuted((u) => !u)
  }, [])

  const reset = useCallback(() => {
    clearWatchdog()
    setAutoMuted(false)
    setUserMuted(false)
  }, [clearWatchdog])

  useEffect(() => () => clearWatchdog(), [clearWatchdog])

  // Stable getter for the mic worklet/processor to gate frames on.
  // useMemo so the identity stays the same across renders.
  const isMutedGetter = useMemo(
    () => () => autoMutedRef.current || userMutedRef.current,
    [],
  )

  return {
    autoMuted,
    userMuted,
    isMuted: autoMuted || userMuted,
    isMutedGetter,
    autoMuteOn,
    autoMuteOff,
    toggleUserMute,
    reset,
  }
}
