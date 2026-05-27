import { ArrowUp } from "lucide-react"
import { useRef, useState, type KeyboardEvent } from "react"
import { cn } from "@/lib/utils"

type ChatInputProps = {
  onSend: (text: string) => void
  disabled?: boolean
  placeholder?: string
}

export function ChatInput({ onSend, disabled, placeholder }: ChatInputProps) {
  const [value, setValue] = useState("")
  const ref = useRef<HTMLTextAreaElement>(null)

  const submit = () => {
    const text = value.trim()
    if (!text || disabled) return
    onSend(text)
    setValue("")
    if (ref.current) ref.current.style.height = "auto"
  }

  const handleKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault()
      submit()
    }
  }

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault()
        submit()
      }}
      className="flex items-end gap-2 rounded-2xl border border-border bg-card p-2"
    >
      <textarea
        ref={ref}
        value={value}
        onChange={(e) => {
          setValue(e.target.value)
          const t = e.currentTarget
          t.style.height = "auto"
          t.style.height = Math.min(t.scrollHeight, 200) + "px"
        }}
        onKeyDown={handleKey}
        rows={1}
        placeholder={placeholder ?? "Type your message…"}
        disabled={disabled}
        className="max-h-[200px] min-h-[2.5rem] flex-1 resize-none bg-transparent px-2 py-1.5 text-body text-foreground placeholder:text-muted-foreground focus:outline-none disabled:opacity-50"
      />
      <button
        type="submit"
        disabled={disabled || !value.trim()}
        className={cn(
          "flex h-9 w-9 items-center justify-center rounded-full bg-primary text-primary-foreground transition-opacity",
          "disabled:opacity-30 disabled:cursor-not-allowed",
        )}
        aria-label="Send"
      >
        <ArrowUp className="h-4 w-4" />
      </button>
    </form>
  )
}
