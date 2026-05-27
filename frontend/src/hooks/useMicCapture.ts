import { useCallback, useEffect, useRef } from "react"

const SAMPLE_RATE = 24000

// Inline worklet: just forwards Float32 chunks to the main thread.
// We encode to PCM16 + base64 in the main thread to keep the worklet tiny.
const WORKLET_SRC = `
class CompanionMicProcessor extends AudioWorkletProcessor {
  process(inputs) {
    const input = inputs[0]
    if (input && input[0] && input[0].length > 0) {
      this.port.postMessage(input[0].slice(0))
    }
    return true
  }
}
registerProcessor('companion-mic', CompanionMicProcessor)
`

type Options = {
  onChunk: (pcm16Base64: string) => void
  isMuted: () => boolean
}

export function useMicCapture({ onChunk, isMuted }: Options) {
  const ctxRef = useRef<AudioContext | null>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const nodeRef = useRef<AudioWorkletNode | ScriptProcessorNode | null>(null)
  const sourceRef = useRef<MediaStreamAudioSourceNode | null>(null)

  const onChunkRef = useRef(onChunk)
  const isMutedRef = useRef(isMuted)
  useEffect(() => {
    onChunkRef.current = onChunk
  }, [onChunk])
  useEffect(() => {
    isMutedRef.current = isMuted
  }, [isMuted])

  const start = useCallback(async () => {
    if (ctxRef.current) return
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        channelCount: 1,
        echoCancellation: true,
        noiseSuppression: true,
      },
    })
    streamRef.current = stream
    const AC =
      window.AudioContext ||
      (
        window as unknown as {
          webkitAudioContext: typeof AudioContext
        }
      ).webkitAudioContext
    const ctx = new AC({ sampleRate: SAMPLE_RATE })
    ctxRef.current = ctx

    const source = ctx.createMediaStreamSource(stream)
    sourceRef.current = source

    // Zero-gain node keeps the graph alive without feeding the speakers.
    const zeroGain = ctx.createGain()
    zeroGain.gain.value = 0

    if ("audioWorklet" in ctx) {
      try {
        const blob = new Blob([WORKLET_SRC], {
          type: "application/javascript",
        })
        const url = URL.createObjectURL(blob)
        await ctx.audioWorklet.addModule(url)
        URL.revokeObjectURL(url)
        const node = new AudioWorkletNode(ctx, "companion-mic")
        node.port.onmessage = (e: MessageEvent<Float32Array>) => {
          if (isMutedRef.current()) return
          onChunkRef.current(encodePcm16(e.data))
        }
        source.connect(node)
        node.connect(zeroGain)
        zeroGain.connect(ctx.destination)
        nodeRef.current = node
        return
      } catch (e) {
        console.warn(
          "[mic] AudioWorklet unavailable, falling back to ScriptProcessor:",
          e,
        )
      }
    }

    // ScriptProcessor fallback for older iOS Safari builds.
    const processor = ctx.createScriptProcessor(4096, 1, 1)
    processor.onaudioprocess = (e) => {
      if (isMutedRef.current()) return
      onChunkRef.current(encodePcm16(e.inputBuffer.getChannelData(0)))
    }
    source.connect(processor)
    processor.connect(zeroGain)
    zeroGain.connect(ctx.destination)
    nodeRef.current = processor
  }, [])

  const stop = useCallback(() => {
    if (nodeRef.current) {
      try {
        nodeRef.current.disconnect()
      } catch {
        // disconnect on an already-disposed node is fine.
      }
      if ("port" in nodeRef.current) {
        try {
          ;(nodeRef.current as AudioWorkletNode).port.close()
        } catch {
          // already closed
        }
      }
      nodeRef.current = null
    }
    if (sourceRef.current) {
      try {
        sourceRef.current.disconnect()
      } catch {
        // already disconnected
      }
      sourceRef.current = null
    }
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((t) => t.stop())
      streamRef.current = null
    }
    if (ctxRef.current) {
      try {
        void ctxRef.current.close()
      } catch {
        // already closed
      }
      ctxRef.current = null
    }
  }, [])

  useEffect(() => () => stop(), [stop])

  return { start, stop }
}

function encodePcm16(input: Float32Array): string {
  const pcm = new Int16Array(input.length)
  for (let i = 0; i < input.length; i++) {
    const s = Math.max(-1, Math.min(1, input[i]))
    pcm[i] = s < 0 ? s * 0x8000 : s * 0x7fff
  }
  const bytes = new Uint8Array(pcm.buffer)
  let binary = ""
  for (let i = 0; i < bytes.length; i++) binary += String.fromCharCode(bytes[i])
  return btoa(binary)
}
