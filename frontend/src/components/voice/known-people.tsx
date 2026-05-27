import { useCallback, useEffect, useRef, useState } from "react"
import { X } from "lucide-react"
import { toast } from "sonner"
import { api } from "@/lib/api"
import { t, type Lang } from "@/lib/i18n"
import type { KnownPerson } from "@/lib/types"

type Props = {
  lang?: Lang
}

export function KnownPeople({ lang = "en" }: Props) {
  const i = t(lang)
  const [people, setPeople] = useState<KnownPerson[]>([])
  const [loading, setLoading] = useState(false)
  const [enrolling, setEnrolling] = useState(false)
  const [name, setName] = useState("")
  const fileRef = useRef<HTMLInputElement | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const list = await api.listPeople()
      setPeople(list)
    } catch (e) {
      console.error("[people] load error:", e)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const enroll = async () => {
    const trimmed = name.trim()
    const file = fileRef.current?.files?.[0]
    if (!trimmed) {
      toast.error(i.enterName)
      return
    }
    if (!file) {
      toast.error(i.selectPhoto)
      return
    }
    setEnrolling(true)
    try {
      await api.enrollPerson(trimmed, file)
      toast.success(i.registered(trimmed))
      setName("")
      if (fileRef.current) fileRef.current.value = ""
      await load()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e))
    } finally {
      setEnrolling(false)
    }
  }

  const remove = async (target: string) => {
    if (!confirm(i.removePerson(target))) return
    try {
      await api.deletePersonByName(target)
      toast.success(i.removed(target))
      await load()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e))
    }
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-col gap-2 rounded-md border border-border p-3">
        <input
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder={lang === "es" ? "Nombre" : lang === "pt" ? "Nome" : "Name"}
          className="w-full rounded-md border border-border bg-card px-3 py-2 text-sm text-foreground focus:border-primary focus:outline-none"
        />
        <input
          ref={fileRef}
          type="file"
          accept="image/*"
          className="block w-full text-xs text-muted-foreground file:mr-3 file:rounded-md file:border file:border-border file:bg-card file:px-3 file:py-1.5 file:text-xs file:text-foreground hover:file:bg-muted"
        />
        <button
          type="button"
          onClick={enroll}
          disabled={enrolling}
          className="self-start rounded-full bg-primary px-4 py-1.5 text-xs uppercase tracking-wider text-primary-foreground transition-opacity hover:opacity-90 disabled:opacity-50"
        >
          {enrolling ? i.uploading : i.enroll}
        </button>
      </div>

      <div className="rounded-md border border-border">
        {loading ? (
          <p className="px-3 py-4 text-center text-xs text-muted-foreground">
            …
          </p>
        ) : people.length === 0 ? (
          <p className="px-3 py-4 text-center text-xs text-muted-foreground">
            {lang === "es"
              ? "Aún no hay personas registradas."
              : lang === "pt"
                ? "Ainda não há pessoas registradas."
                : "No registered people yet."}
          </p>
        ) : (
          <ul className="divide-y divide-border">
            {people.map((p) => (
              <li
                key={p.name}
                className="flex items-center justify-between px-3 py-2"
              >
                <div className="flex flex-col">
                  <span className="text-sm text-foreground">{p.name}</span>
                  <span className="text-xs text-muted-foreground">
                    {p.count}{" "}
                    {lang === "es"
                      ? p.count === 1 ? "foto" : "fotos"
                      : lang === "pt"
                        ? p.count === 1 ? "foto" : "fotos"
                        : p.count === 1 ? "photo" : "photos"}
                  </span>
                </div>
                <button
                  type="button"
                  onClick={() => remove(p.name)}
                  className="rounded-full p-1.5 text-muted-foreground hover:bg-muted hover:text-destructive"
                  aria-label={`Remove ${p.name}`}
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}
