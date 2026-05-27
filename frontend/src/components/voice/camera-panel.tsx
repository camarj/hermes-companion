import type { Ref } from "react"

type Props = {
  videoRef: Ref<HTMLVideoElement>
  visible: boolean
}

export function CameraPanel({ videoRef, visible }: Props) {
  return (
    <div
      className={
        visible
          ? "fixed bottom-6 right-6 z-30 overflow-hidden rounded-2xl border border-border bg-card shadow-xl transition-opacity"
          : "pointer-events-none fixed bottom-6 right-6 z-30 opacity-0"
      }
      style={{ width: 240, height: 180 }}
    >
      <video
        ref={videoRef}
        autoPlay
        playsInline
        muted
        className="h-full w-full object-cover"
      />
    </div>
  )
}
