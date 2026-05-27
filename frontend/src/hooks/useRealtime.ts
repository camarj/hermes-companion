import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import type { UIMessage } from "ai"
import { api } from "@/lib/api"
import type { User, VoiceMode } from "@/lib/types"
import { useAudioPlayback } from "./useAudioPlayback"
import { useCamera } from "./useCamera"
import { useEchoSuppression } from "./useEchoSuppression"
import { useMicCapture } from "./useMicCapture"

type ToolThinking = {
  tool: string
  query: string | null
}

type Options = {
  user: User
  onError?: (msg: string) => void
  onConversationCreated?: (id: string) => void
  onNewFacesGreeting?: () => void
}

// Server emits errors we treat as benign — handled internally by OpenAI and
// not worth surfacing as toasts.
const BENIGN_ERROR_CODES = new Set([
  "conversation_already_has_active_response",
  "input_audio_buffer_commit_empty",
  "response_cancel_not_active",
])

function makeId(prefix: string): string {
  return `${prefix}_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`
}

export function useRealtime({
  user,
  onError,
  onConversationCreated,
  onNewFacesGreeting,
}: Options) {
  const [mode, setModeState] = useState<VoiceMode>("chat")
  const [connected, setConnected] = useState(false)
  const [connecting, setConnecting] = useState(false)
  const [sessionReady, setSessionReady] = useState(false)
  const [liveMessages, setLiveMessages] = useState<UIMessage[]>([])
  const [thinking, setThinking] = useState<ToolThinking | null>(null)
  const [conversationId, setConversationId] = useState<string | null>(null)

  const wsRef = useRef<WebSocket | null>(null)
  const modeRef = useRef<VoiceMode>("chat")
  const sessionReadyRef = useRef(false)
  const connectedRef = useRef(false)

  // Pending message handles for the current turn.
  const pendingUserIdRef = useRef<string | null>(null)
  const pendingAssistantIdRef = useRef<string | null>(null)

  useEffect(() => {
    modeRef.current = mode
  }, [mode])
  useEffect(() => {
    sessionReadyRef.current = sessionReady
  }, [sessionReady])
  useEffect(() => {
    connectedRef.current = connected
  }, [connected])

  const echo = useEchoSuppression({
    onWatchdog: () => onError?.("Tool timed out — microphone reactivated"),
  })

  // When the mic un-mutes (auto or user), drop anything OpenAI may have
  // buffered during the wait so the next turn doesn't pick up stale audio.
  const prevMutedRef = useRef(false)
  useEffect(() => {
    const ws = wsRef.current
    const wasMuted = prevMutedRef.current
    prevMutedRef.current = echo.isMuted
    if (wasMuted && !echo.isMuted && ws && ws.readyState === WebSocket.OPEN) {
      try {
        ws.send(JSON.stringify({ type: "input_audio_buffer.clear" }))
      } catch {
        // socket closing
      }
    }
  }, [echo.isMuted])

  const playback_ = useAudioPlayback()

  const camera = useCamera()

  // ── helpers to mutate the live transcript ──────────────────────────────

  const upsertMessage = useCallback(
    (id: string, role: "user" | "assistant", text: string) => {
      setLiveMessages((prev) => {
        const idx = prev.findIndex((m) => m.id === id)
        const next: UIMessage = {
          id,
          role,
          parts: [{ type: "text", text }],
        }
        if (idx === -1) return [...prev, next]
        const copy = prev.slice()
        copy[idx] = next
        return copy
      })
    },
    [],
  )

  const appendToMessage = useCallback((id: string, piece: string) => {
    setLiveMessages((prev) => {
      const idx = prev.findIndex((m) => m.id === id)
      if (idx === -1) return prev
      const msg = prev[idx]
      const current =
        msg.parts.find((p) => p.type === "text") &&
        (msg.parts.find((p) => p.type === "text") as { type: "text"; text: string }).text
      const newText = (current || "") + piece
      const next: UIMessage = {
        ...msg,
        parts: [{ type: "text", text: newText }],
      }
      const copy = prev.slice()
      copy[idx] = next
      return copy
    })
  }, [])

  const removeMessage = useCallback((id: string) => {
    setLiveMessages((prev) => prev.filter((m) => m.id !== id))
  }, [])

  // ── mic ────────────────────────────────────────────────────────────────

  const mic = useMicCapture({
    onChunk: (b64) => {
      const ws = wsRef.current
      if (!ws || ws.readyState !== WebSocket.OPEN) return
      if (!sessionReadyRef.current) return
      try {
        ws.send(JSON.stringify({ type: "input_audio_buffer.append", audio: b64 }))
      } catch {
        // socket closing
      }
    },
    isMuted: echo.isMutedGetter,
  })

  // ── inbound event handling ─────────────────────────────────────────────

  const handleEvent = useCallback(
    (msg: { type?: string } & Record<string, unknown>) => {
      const type = msg.type as string

      if (type === "session.created" || type === "session.updated") {
        if (type === "session.updated" && !sessionReadyRef.current) {
          setSessionReady(true)
        }
        return
      }

      if (type === "realtime.conversation_ready") {
        const convId = msg.conversation_id as string | undefined
        if (convId) {
          setConversationId(convId)
          onConversationCreated?.(convId)
        }
        return
      }

      if (type === "input_audio_buffer.speech_started") {
        // server_vad interrupt — stop assistant playback so user can talk over.
        playback_.stop()
        return
      }

      if (type === "input_audio_buffer.speech_stopped") {
        // Pre-create the user bubble now so it appears before assistant deltas.
        if (!pendingUserIdRef.current) {
          const id = makeId("user")
          pendingUserIdRef.current = id
          upsertMessage(id, "user", "…")
        }
        // Vision: server_vad has create_response=false; capture + inject the frame
        // so the assistant answers this turn with both audio and what you're seeing.
        // Read camera.isActive() (ref-backed) rather than camera.active (React
        // state) — the captured closure may have a stale value from the moment
        // handleEvent was last memoized.
        if (modeRef.current === "vision" && camera.isActive()) {
          void camera.snapshotAndSend(null, { silent: true })
        }
        return
      }

      if (type === "conversation.item.input_audio_transcription.delta") {
        const piece = (msg.delta as string) || ""
        if (!piece) return
        if (!pendingUserIdRef.current) {
          const id = makeId("user")
          pendingUserIdRef.current = id
          upsertMessage(id, "user", "")
        }
        const id = pendingUserIdRef.current
        setLiveMessages((prev) => {
          const idx = prev.findIndex((m) => m.id === id)
          if (idx === -1) return prev
          const msg2 = prev[idx]
          const cur = msg2.parts.find((p) => p.type === "text") as
            | { type: "text"; text: string }
            | undefined
          const text = cur && cur.text !== "…" ? cur.text + piece : piece
          const next: UIMessage = {
            ...msg2,
            parts: [{ type: "text", text }],
          }
          const copy = prev.slice()
          copy[idx] = next
          return copy
        })
        return
      }

      if (type === "conversation.item.input_audio_transcription.completed") {
        const transcript = ((msg.transcript as string) || "").trim()
        const id = pendingUserIdRef.current
        if (id) {
          if (transcript) {
            upsertMessage(id, "user", transcript)
          } else {
            removeMessage(id)
          }
        }
        pendingUserIdRef.current = null
        return
      }

      if (
        type === "response.output_audio.delta" ||
        type === "response.audio.delta"
      ) {
        const delta = msg.delta as string | undefined
        if (delta) playback_.enqueue(delta)
        return
      }

      if (
        type === "response.output_audio.done" ||
        type === "response.audio.done"
      ) {
        return
      }

      if (
        type === "response.output_audio_transcript.delta" ||
        type === "response.audio_transcript.delta"
      ) {
        const piece = (msg.delta as string) || ""
        if (!piece) return
        if (!pendingAssistantIdRef.current) {
          const id = makeId("assistant")
          pendingAssistantIdRef.current = id
          upsertMessage(id, "assistant", "")
        }
        appendToMessage(pendingAssistantIdRef.current, piece)
        return
      }

      if (
        type === "response.output_audio_transcript.done" ||
        type === "response.audio_transcript.done"
      ) {
        pendingAssistantIdRef.current = null
        return
      }

      if (type === "companion.tool_started") {
        echo.autoMuteOn(`tool ${(msg.tool as string) || "unknown"} started`)
        setThinking({
          tool: (msg.tool as string) || "unknown",
          query: (msg.query as string) || null,
        })
        return
      }

      if (type === "companion.tool_finished") {
        echo.autoMuteOff(`tool ${(msg.tool as string) || "unknown"} finished`)
        setThinking(null)
        return
      }

      if (type === "response.done") {
        echo.autoMuteOff("response.done")
        pendingAssistantIdRef.current = null
        return
      }

      if (type === "error") {
        const err = msg.error as
          | { code?: string; message?: string }
          | undefined
        const code = err?.code || ""
        const errMsg = err?.message || "Unknown realtime error"
        if (BENIGN_ERROR_CODES.has(code)) {
          console.warn("[realtime] benign API note:", code, "—", errMsg)
          return
        }
        console.error("[realtime] API error:", msg)
        onError?.(`Realtime error: ${errMsg}`)
        // Don't leave the user stuck muted if something went sideways.
        echo.autoMuteOff("error event")
        return
      }
    },
    [
      appendToMessage,
      camera,
      echo,
      onConversationCreated,
      onError,
      playback_,
      removeMessage,
      upsertMessage,
    ],
  )

  // ── connect / disconnect ───────────────────────────────────────────────

  const disconnect = useCallback(
    async (opts: { silent?: boolean } = {}) => {
      const ws = wsRef.current
      wsRef.current = null
      setConnected(false)
      setSessionReady(false)
      pendingUserIdRef.current = null
      pendingAssistantIdRef.current = null
      setThinking(null)
      setConversationId(null)
      setLiveMessages([])
      echo.reset()
      mic.stop()
      playback_.stop()
      if (ws) {
        try {
          ws.close()
        } catch {
          // already closing
        }
      }
      if (!opts.silent) {
        // surface via onError only? Toast handled at UI layer.
      }
    },
    [echo, mic, playback_],
  )

  const connect = useCallback(async (): Promise<boolean> => {
    if (wsRef.current) return true
    setConnecting(true)

    // Create a conversation so transcripts persist server-side.
    let convId = ""
    try {
      const conv = await api.createConversation()
      convId = conv.id
    } catch (e) {
      console.warn("[realtime] could not create conversation, continuing:", e)
    }

    const protocol = location.protocol === "https:" ? "wss:" : "ws:"
    const url = `${protocol}//${location.host}/api/realtime?user_id=${encodeURIComponent(user.id)}&conversation_id=${encodeURIComponent(convId)}`

    return new Promise<boolean>((resolve) => {
      let resolved = false
      const settle = (value: boolean) => {
        if (resolved) return
        resolved = true
        resolve(value)
      }
      let ws: WebSocket
      try {
        ws = new WebSocket(url)
      } catch (e) {
        console.error("[realtime] WebSocket creation failed:", e)
        onError?.("Could not create Realtime connection")
        setConnecting(false)
        settle(false)
        return
      }
      wsRef.current = ws

      ws.onopen = async () => {
        try {
          await mic.start()
        } catch (e) {
          console.error("[realtime] mic error:", e)
          onError?.("Could not access microphone")
          try {
            ws.close()
          } catch {
            // socket may already be closing
          }
          return
        }
      }

      ws.onmessage = (e) => {
        try {
          const msg = JSON.parse(e.data)
          handleEvent(msg)
          // Mark connected on first session.updated (handled inside handleEvent).
          if (msg.type === "session.updated" && !connectedRef.current) {
            setConnected(true)
            setConnecting(false)
            // If we connected directly into vision mode, sync that to the proxy.
            if (modeRef.current === "vision") {
              try {
                ws.send(
                  JSON.stringify({
                    type: "companion.vision_mode",
                    enabled: true,
                  }),
                )
              } catch {
                // socket closing
              }
            }
            settle(true)
          }
        } catch (err) {
          console.error("[realtime] parse error:", err)
        }
      }

      ws.onclose = (e) => {
        console.log("[realtime] disconnected:", e.code, e.reason)
        wsRef.current = null
        setConnected(false)
        setSessionReady(false)
        setConnecting(false)
        mic.stop()
        playback_.stop()
        echo.reset()
        // If the user was in voice/vision when the socket dropped, fall back to chat.
        if (modeRef.current !== "chat") {
          camera.close()
          setModeState("chat")
        }
        // Only resolve(false) if we never reached session.updated. After
        // session.updated already resolved(true), this becomes a no-op.
        settle(false)
      }

      ws.onerror = (e) => {
        console.error("[realtime] WebSocket error:", e)
        onError?.("Realtime connection error")
      }
    })
  }, [camera, echo, handleEvent, mic, onError, playback_, user.id])

  // ── mode transitions ───────────────────────────────────────────────────

  const setMode = useCallback(
    async (next: VoiceMode) => {
      if (next === modeRef.current) return
      const prev = modeRef.current
      modeRef.current = next
      setModeState(next)

      if (next === "chat") {
        camera.close()
        await disconnect({ silent: true })
        return
      }

      if (next === "voice") {
        camera.close()
        const ws = wsRef.current
        if (ws && ws.readyState === WebSocket.OPEN) {
          try {
            ws.send(
              JSON.stringify({ type: "companion.vision_mode", enabled: false }),
            )
          } catch {
            // socket closing
          }
        } else {
          const ok = await connect()
          if (!ok) {
            modeRef.current = prev
            setModeState(prev)
          }
        }
        return
      }

      // vision
      const camOk = await camera.open()
      if (!camOk) {
        onError?.("Could not access the camera")
        modeRef.current = prev
        setModeState(prev)
        return
      }
      const ws = wsRef.current
      if (ws && ws.readyState === WebSocket.OPEN) {
        try {
          ws.send(
            JSON.stringify({ type: "companion.vision_mode", enabled: true }),
          )
        } catch {
          // socket closing
        }
        // Match the initial-connect path: defer the greeting so the proxy has
        // a beat to re-tune VAD with create_response=false before we inject.
        // Without this defer, an in-flight speech_stopped could trigger an
        // image-less response.
        window.setTimeout(() => {
          void sendVisionGreeting()
        }, 300)
      } else {
        const ok = await connect()
        if (!ok) {
          camera.close()
          modeRef.current = prev
          setModeState(prev)
          return
        }
        // Tiny defer so the proxy processes companion.vision_mode (switches
        // server_vad's create_response off) before we inject the frame.
        window.setTimeout(() => {
          void sendVisionGreeting()
        }, 300)
      }
    },
    // sendVisionGreeting closes over camera/echo/etc — defined below; we
    // intentionally pin the deps to the externally-stable bits.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [camera, connect, disconnect, onError],
  )

  const sendVisionGreeting = useCallback(async () => {
    if (camera.hasGreeted()) return
    if (modeRef.current !== "vision") return
    if (!connectedRef.current || !sessionReadyRef.current) return
    if (!camera.active) return
    camera.markGreeted()
    const prompt =
      'I just enabled vision + voice mode. If the system context block tells you that you recognized someone, greet them by name with a short phrase (e.g. "Hi Alex"). If no name is recognized, just say "Hi". Do NOT mention the place, objects, clothing, glasses, background, decoration or anything else visible in the image. Just the greeting, nothing else.'
    const recognized = await camera.snapshotAndSend(prompt, { silent: true })
    if (Array.isArray(recognized)) camera.markSeen(recognized)
    // Start background polling once the greeting is out.
    camera.startPolling({
      canPoll: () =>
        modeRef.current === "vision" &&
        connectedRef.current &&
        camera.active,
      onNewFaces: async (newcomers) => {
        const list = newcomers.join(", ")
        const greetingPrompt =
          newcomers.length === 1
            ? `Acaba de entrar al cuadro ${list}. Salúdale por su nombre con una frase corta (ej. "Hola ${newcomers[0]}, cuéntame"). NO menciones el lugar, los objetos, la ropa, los audífonos, gafas, fondo, decoración ni cualquier otra cosa más allá del saludo.`
            : `Acaban de aparecer en cámara: ${list}. Salúdales por su nombre con una frase corta. NO menciones el lugar, los objetos, la ropa, los audífonos, gafas, fondo, decoración ni cualquier otra cosa más allá del saludo.`
        await camera.snapshotAndSend(greetingPrompt, { silent: true })
        onNewFacesGreeting?.()
      },
    })
  }, [camera, onNewFacesGreeting])

  // Cleanup on unmount.
  useEffect(() => {
    return () => {
      const ws = wsRef.current
      if (ws) {
        try {
          ws.close()
        } catch {
          // already closing
        }
      }
      wsRef.current = null
    }
  }, [])

  return useMemo(
    () => ({
      mode,
      setMode,
      connected,
      connecting,
      sessionReady,
      liveMessages,
      thinking,
      conversationId,
      autoMuted: echo.autoMuted,
      userMuted: echo.userMuted,
      isMuted: echo.isMuted,
      toggleMute: echo.toggleUserMute,
      attachCameraVideo: camera.attachVideo,
      cameraActive: camera.active,
    }),
    [
      mode,
      setMode,
      connected,
      connecting,
      sessionReady,
      liveMessages,
      thinking,
      conversationId,
      echo.autoMuted,
      echo.userMuted,
      echo.isMuted,
      echo.toggleUserMute,
      camera.attachVideo,
      camera.active,
    ],
  )
}
