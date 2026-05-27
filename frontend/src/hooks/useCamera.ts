import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { api } from "@/lib/api"

const POLL_INTERVAL_MS = 5000

type SnapshotOpts = {
  silent?: boolean
}

/**
 * Camera handle: owns the MediaStream and (via attachVideo) the <video>
 * element that previews it. Exposes frame capture + background polling for
 * known faces.
 *
 * The video element lives in the UI tree (CameraPanel), so the consumer
 * passes attachVideo as a ref callback when rendering it.
 */
export function useCamera() {
  const [active, setActive] = useState(false)
  const streamRef = useRef<MediaStream | null>(null)
  const videoRef = useRef<HTMLVideoElement | null>(null)
  const pollRef = useRef<number | null>(null)
  const inFlightRef = useRef(false)
  const seenRef = useRef<Set<string>>(new Set())
  const tickRef = useRef<() => Promise<void>>(async () => {})
  const greetedRef = useRef(false)
  // Mirror of `active` for use inside closures (event handlers that read
  // `active` directly would see a stale value because the closure was created
  // when `active` was still false).
  const activeRef = useRef(false)
  useEffect(() => {
    activeRef.current = active
  }, [active])
  const isActive = useCallback(() => activeRef.current, [])

  const open = useCallback(async (): Promise<boolean> => {
    if (streamRef.current) return true
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: {
          width: { ideal: 1280 },
          height: { ideal: 720 },
          facingMode: "user",
        },
        audio: false,
      })
      streamRef.current = stream
      if (videoRef.current) {
        videoRef.current.srcObject = stream
        try {
          await videoRef.current.play()
        } catch {
          // autoplay may be blocked until user gesture; first frame will appear once it resolves
        }
        await waitForVideoReady(videoRef.current, 2000)
      }
      setActive(true)
      return true
    } catch (e) {
      console.error("[vision] getUserMedia error:", e)
      return false
    }
  }, [])

  const close = useCallback(() => {
    if (pollRef.current !== null) {
      window.clearInterval(pollRef.current)
      pollRef.current = null
    }
    seenRef.current = new Set()
    greetedRef.current = false
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((t) => t.stop())
      streamRef.current = null
    }
    if (videoRef.current) videoRef.current.srcObject = null
    setActive(false)
  }, [])

  const attachVideo = useCallback((el: HTMLVideoElement | null) => {
    videoRef.current = el
    if (el && streamRef.current && el.srcObject !== streamRef.current) {
      el.srcObject = streamRef.current
      void el.play().catch(() => {})
    }
  }, [])

  const captureFrame = useCallback((quality = 0.82): string | null => {
    if (!streamRef.current || !videoRef.current) return null
    const v = videoRef.current
    const w = v.videoWidth || 0
    const h = v.videoHeight || 0
    if (w === 0 || h === 0) return null
    const canvas = document.createElement("canvas")
    canvas.width = w
    canvas.height = h
    const ctx = canvas.getContext("2d")
    if (!ctx) return null
    ctx.drawImage(v, 0, 0, w, h)
    return canvas.toDataURL("image/jpeg", quality)
  }, [])

  // Capture + POST /api/vision/snapshot. Returns the recognized names array
  // (or null on error / no frame). Used both for vision-mode turn injection
  // and for the initial greeting.
  const snapshotAndSend = useCallback(
    async (
      promptText: string | null,
      _opts: SnapshotOpts = {},
    ): Promise<string[] | null> => {
      const dataUrl = captureFrame(0.82)
      if (!dataUrl) {
        console.warn("[vision] skipping snapshot — video not ready")
        return null
      }
      try {
        const data = await api.visionSnapshot(dataUrl, promptText)
        return Array.isArray(data.recognized) ? data.recognized : []
      } catch (e) {
        console.error("[vision] snapshot error:", e)
        return null
      }
    },
    [captureFrame],
  )

  // Background poll: every POLL_INTERVAL_MS capture a frame, run face
  // recognition, and report newly-seen known faces via onNewFaces.
  type PollOpts = {
    onNewFaces: (names: string[]) => void
    canPoll: () => boolean
  }
  const startPolling = useCallback(({ onNewFaces, canPoll }: PollOpts) => {
    if (pollRef.current !== null) return

    const tick = async () => {
      if (!canPoll()) return
      if (inFlightRef.current) return
      const dataUrl = captureFrame(0.7)
      if (!dataUrl) return
      inFlightRef.current = true
      try {
        const data = await api.visionRecognize(dataUrl)
        const names = data.recognized || []
        const newcomers = names.filter((n) => !seenRef.current.has(n))
        if (newcomers.length > 0) {
          newcomers.forEach((n) => seenRef.current.add(n))
          onNewFaces(newcomers)
        }
      } catch {
        // swallow — next tick will retry
      } finally {
        inFlightRef.current = false
      }
    }
    tickRef.current = tick
    pollRef.current = window.setInterval(() => {
      void tick()
    }, POLL_INTERVAL_MS)
  }, [captureFrame])

  const stopPolling = useCallback(() => {
    if (pollRef.current !== null) {
      window.clearInterval(pollRef.current)
      pollRef.current = null
    }
  }, [])

  // Mark a name as already-greeted (used after the initial vision greeting
  // returns recognized names — we don't want the poller to greet them again).
  const markSeen = useCallback((names: string[]) => {
    names.forEach((n) => seenRef.current.add(n))
  }, [])

  const markGreeted = useCallback(() => {
    greetedRef.current = true
  }, [])

  const hasGreeted = useCallback(() => greetedRef.current, [])

  useEffect(() => () => close(), [close])

  return useMemo(
    () => ({
      active,
      isActive,
      open,
      close,
      attachVideo,
      captureFrame,
      snapshotAndSend,
      startPolling,
      stopPolling,
      markSeen,
      markGreeted,
      hasGreeted,
    }),
    [
      active,
      isActive,
      open,
      close,
      attachVideo,
      captureFrame,
      snapshotAndSend,
      startPolling,
      stopPolling,
      markSeen,
      markGreeted,
      hasGreeted,
    ],
  )
}

function waitForVideoReady(
  videoEl: HTMLVideoElement,
  timeoutMs: number,
): Promise<boolean> {
  return new Promise((resolve) => {
    const start = Date.now()
    const check = () => {
      if (videoEl.videoWidth > 0 && videoEl.videoHeight > 0) {
        resolve(true)
        return
      }
      if (Date.now() - start > timeoutMs) {
        resolve(false)
        return
      }
      window.setTimeout(check, 50)
    }
    check()
  })
}
