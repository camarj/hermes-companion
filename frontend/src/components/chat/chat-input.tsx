import { ArrowUp } from "lucide-react"
import { useRef, useState, type KeyboardEvent } from "react"
import { cn } from "@/lib/utils"

type ChatInputProps = {
  onSend: (text: string) => void
  disabled?: boolean
  placeholder?: string
  autoFocus?: boolean
}

/**
 * Large input matching the legacy `.text-input` + `.btn-action` pair: ~96px
 * minimum height growing to 150px, rounded-lg border with focus accent, and
 * a round 42px send button on the right.
 */
export function ChatInput({
  onSend,
  disabled,
  placeholder,
  autoFocus,
}: ChatInputProps) {
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
      className="flex items-end gap-2"
    >
      <textarea
        ref={ref}
        value={value}
        autoFocus={autoFocus}
        onChange={(e) => {
          setValue(e.target.value)
          const t = e.currentTarget
          t.style.height = "auto"
          t.style.height = Math.min(t.scrollHeight, 150) + "px"
        }}
        onKeyDown={handleKey}
        rows={4}
        placeholder={placeholder}
        disabled={disabled}
        className={cn(
          "flex-1 resize-none rounded-lg border border-border bg-transparent px-4 py-3 text-sm text-foreground placeholder:text-muted-foreground transition-colors focus:border-primary focus:outline-none disabled:opacity-30",
          "min-h-[96px] max-h-[150px] leading-[1.55]",
        )}
      />
      <button
        type="submit"
        disabled={disabled || !value.trim()}
        title="Send"
        aria-label="Send"
        className={cn(
          "flex h-[42px] w-[42px] shrink-0 items-center justify-center rounded-full border border-primary bg-primary text-primary-foreground transition-all",
          "hover:opacity-90 disabled:opacity-20 disabled:cursor-default",
        )}
      >
        <ArrowUp className="h-[18px] w-[18px]" />
      </button>
    </form>
  )
}
