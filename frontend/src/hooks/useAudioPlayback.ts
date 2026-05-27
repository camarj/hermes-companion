import { useCallback, useEffect, useMemo, useRef } from "react"

const SAMPLE_RATE = 24000

export function useAudioPlayback() {
  const ctxRef = useRef<AudioContext | null>(null)
  const queueRef = useRef<Float32Array[]>([])
  const playingRef = useRef(false)
  const mutedRef = useRef(false)
  const currentSourceRef = useRef<AudioBufferSourceNode | null>(null)

  const ensureCtx = useCallback((): AudioContext => {
    if (!ctxRef.current || ctxRef.current.state === "closed") {
      const AC =
        window.AudioContext ||
        (
          window as unknown as {
            webkitAudioContext: typeof AudioContext
          }
        ).webkitAudioContext
      ctxRef.current = new AC({ sampleRate: SAMPLE_RATE })
    }
    return ctxRef.current
  }, [])

  const playNext = useCallback(() => {
    const queue = queueRef.current
    if (queue.length === 0) {
      playingRef.current = false
      return
    }
    playingRef.current = true
    const chunk = queue.shift()
    if (!chunk) {
      playingRef.current = false
      return
    }
    const ctx = ensureCtx()
    const buffer = ctx.createBuffer(1, chunk.length, SAMPLE_RATE)
    buffer.getChannelData(0).set(chunk)
    const source = ctx.createBufferSource()
    source.buffer = buffer
    source.connect(ctx.destination)
    source.onended = () => {
      if (currentSourceRef.current === source) currentSourceRef.current = null
      playNext()
    }
    currentSourceRef.current = source
    source.start()
  }, [ensureCtx])

  const enqueue = useCallback(
    (b64Pcm16: string) => {
      if (!b64Pcm16) return
      if (mutedRef.current) return
      try {
        const binary = atob(b64Pcm16)
        const bytes = new Uint8Array(binary.length)
        for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i)
        const pcm16 = new Int16Array(bytes.buffer)
        const float32 = new Float32Array(pcm16.length)
        for (let i = 0; i < pcm16.length; i++) {
          float32[i] = pcm16[i] / (pcm16[i] < 0 ? 0x8000 : 0x7fff)
        }
        queueRef.current.push(float32)
        if (!playingRef.current) playNext()
      } catch (e) {
        console.error("[playback] decode error:", e)
      }
    },
    [playNext],
  )

  const silenceCurrent = useCallback(() => {
    const source = currentSourceRef.current
    if (!source) return
    currentSourceRef.current = null
    try {
      source.onended = null
      source.stop()
    } catch {
      // already stopped
    }
    try {
      source.disconnect()
    } catch {
      // already disconnected
    }
    playingRef.current = false
  }, [])

  // Drop buffered chunks, stop the in-flight source, and tear down the context.
  const stop = useCallback(() => {
    queueRef.current = []
    silenceCurrent()
    if (ctxRef.current) {
      try {
        void ctxRef.current.close()
      } catch {
        // already closed
      }
      ctxRef.current = null
    }
  }, [silenceCurrent])

  // LOCAL playback: backend pipes audio to server speakers, browser stays silent
  // to avoid a duplicated, out-of-sync echo. Setting muted=true drops the
  // queue *and* silences any in-flight BufferSource so the user doesn't hear
  // the current chunk play out on top of the server speaker output.
  const setMuted = useCallback(
    (muted: boolean) => {
      mutedRef.current = muted
      if (muted) {
        queueRef.current = []
        silenceCurrent()
      }
    },
    [silenceCurrent],
  )

  useEffect(() => () => stop(), [stop])

  return useMemo(
    () => ({ enqueue, stop, setMuted }),
    [enqueue, stop, setMuted],
  )
}
