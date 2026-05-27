import { ArrowUp, Paperclip, X } from "lucide-react"
import { useRef, useState, type DragEvent, type KeyboardEvent } from "react"
import { toast } from "sonner"
import { cn } from "@/lib/utils"
import { t, type Lang } from "@/lib/i18n"
import type { ChatAttachment } from "@/lib/types"

type ChatInputProps = {
  onSend: (text: string, attachments: ChatAttachment[]) => void
  disabled?: boolean
  placeholder?: string
  autoFocus?: boolean
  lang?: Lang
}

const MAX_FILES = 5
const MAX_FILE_BYTES = 1_000_000
const TEXT_EXTS = new Set([
  "txt", "md", "markdown", "mdown", "mkd",
  "csv", "tsv", "json", "jsonl", "ndjson",
  "yaml", "yml", "toml", "ini", "cfg", "conf", "env",
  "log",
  "py", "js", "ts", "tsx", "jsx",
  "html", "htm", "css", "scss", "sass", "less",
  "sql", "sh", "bash", "zsh",
  "go", "rs", "rb", "java", "kt", "swift",
  "cpp", "cc", "cxx", "c", "h", "hpp",
  "xml", "svg",
])
const BINARY_EXTS = new Set(["pdf", "png", "jpg", "jpeg", "webp", "gif"])

function extOf(name: string): string {
  const i = name.lastIndexOf(".")
  return i >= 0 ? name.slice(i + 1).toLowerCase() : ""
}

function bytesToBase64(bytes: Uint8Array): string {
  // btoa() needs a binary string; chunk to avoid blowing the call stack on
  // large buffers (~1 MB PDF = ~1M chars).
  let binary = ""
  const chunk = 0x8000
  for (let i = 0; i < bytes.length; i += chunk) {
    binary += String.fromCharCode.apply(
      null,
      Array.from(bytes.subarray(i, i + chunk)),
    )
  }
  return btoa(binary)
}

export function ChatInput({
  onSend,
  disabled,
  placeholder,
  autoFocus,
  lang,
}: ChatInputProps) {
  const i = t(lang)
  const [value, setValue] = useState("")
  const [attachments, setAttachments] = useState<ChatAttachment[]>([])
  const [dragOver, setDragOver] = useState(false)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const ingestFiles = async (files: File[]) => {
    if (!files.length) return
    if (attachments.length + files.length > MAX_FILES) {
      toast.error(i.attachmentLimitReached)
      return
    }
    const accepted: ChatAttachment[] = []
    for (const file of files) {
      const ext = extOf(file.name)
      const isBinary = BINARY_EXTS.has(ext)
      if (!TEXT_EXTS.has(ext) && !isBinary) {
        toast.error(i.attachmentTypeUnsupported(file.name))
        continue
      }
      if (file.size > MAX_FILE_BYTES) {
        toast.error(i.attachmentTooLarge(file.name))
        continue
      }
      try {
        const content = isBinary
          ? bytesToBase64(new Uint8Array(await file.arrayBuffer()))
          : await file.text()
        accepted.push({ name: file.name, size: file.size, content })
      } catch {
        toast.error(i.attachmentReadFailed(file.name))
      }
    }
    if (accepted.length) {
      setAttachments((prev) => [...prev, ...accepted])
    }
  }

  const submit = () => {
    const text = value.trim()
    if (disabled) return
    if (!text && attachments.length === 0) return
    onSend(text, attachments)
    setValue("")
    setAttachments([])
    if (textareaRef.current) textareaRef.current.style.height = "auto"
  }

  const handleKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault()
      submit()
    }
  }

  const onDrop = (e: DragEvent<HTMLFormElement>) => {
    e.preventDefault()
    setDragOver(false)
    const files = Array.from(e.dataTransfer.files)
    void ingestFiles(files)
  }

  const onDragOver = (e: DragEvent<HTMLFormElement>) => {
    e.preventDefault()
    if (!dragOver) setDragOver(true)
  }

  const onDragLeave = (e: DragEvent<HTMLFormElement>) => {
    if (e.currentTarget.contains(e.relatedTarget as Node)) return
    setDragOver(false)
  }

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault()
        submit()
      }}
      onDragEnter={onDragOver}
      onDragOver={onDragOver}
      onDragLeave={onDragLeave}
      onDrop={onDrop}
      className={cn(
        "flex flex-col gap-2 rounded-lg border border-border bg-transparent px-3 py-2 transition-colors focus-within:border-primary",
        dragOver && "border-primary bg-primary/5",
        disabled && "opacity-60",
      )}
    >
      {attachments.length > 0 && (
        <ul className="flex flex-wrap gap-1.5">
          {attachments.map((att, idx) => (
            <li
              key={`${att.name}-${idx}`}
              className="flex items-center gap-1.5 rounded-md border border-border bg-muted px-2 py-1 text-xs"
            >
              <Paperclip className="h-3 w-3 text-muted-foreground" />
              <span className="max-w-[180px] truncate font-mono text-[11px]">{att.name}</span>
              <button
                type="button"
                aria-label={i.removeAttachment}
                onClick={() =>
                  setAttachments((prev) => prev.filter((_, j) => j !== idx))
                }
                className="-mr-0.5 rounded p-0.5 text-muted-foreground hover:text-foreground"
              >
                <X className="h-3 w-3" />
              </button>
            </li>
          ))}
        </ul>
      )}

      <div className="flex items-end gap-2">
        <button
          type="button"
          aria-label={i.attachFile}
          title={i.attachFile}
          onClick={() => fileInputRef.current?.click()}
          disabled={disabled || attachments.length >= MAX_FILES}
          className="flex h-[36px] w-[36px] shrink-0 items-center justify-center rounded-full text-muted-foreground transition-colors hover:bg-muted hover:text-foreground disabled:opacity-30 disabled:hover:bg-transparent"
        >
          <Paperclip className="h-[18px] w-[18px]" />
        </button>
        <input
          ref={fileInputRef}
          type="file"
          multiple
          className="hidden"
          onChange={(e) => {
            const files = Array.from(e.target.files ?? [])
            void ingestFiles(files)
            e.target.value = ""
          }}
        />

        <textarea
          ref={textareaRef}
          value={value}
          autoFocus={autoFocus}
          onChange={(e) => {
            setValue(e.target.value)
            const t = e.currentTarget
            t.style.height = "auto"
            t.style.height = Math.min(t.scrollHeight, 150) + "px"
          }}
          onKeyDown={handleKey}
          rows={3}
          placeholder={placeholder}
          disabled={disabled}
          className={cn(
            "flex-1 resize-none bg-transparent px-1 py-2 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none disabled:opacity-30",
            "min-h-[72px] max-h-[150px] leading-[1.55]",
          )}
        />

        <button
          type="submit"
          disabled={disabled || (!value.trim() && attachments.length === 0)}
          title="Send"
          aria-label="Send"
          className={cn(
            "flex h-[36px] w-[36px] shrink-0 items-center justify-center rounded-full border border-primary bg-primary text-primary-foreground transition-all",
            "hover:opacity-90 disabled:opacity-20 disabled:cursor-default",
          )}
        >
          <ArrowUp className="h-[18px] w-[18px]" />
        </button>
      </div>
    </form>
  )
}
