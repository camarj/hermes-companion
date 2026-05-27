import { useCallback, useEffect, useState } from "react"
import type { PlaybackMode, Settings, ThemeMode } from "@/lib/types"

const STORAGE_KEY = "companion_settings"

const DEFAULTS: Settings = {
  theme: "dark",
  language: "es",
  playback: "private",
}

function readStored(): Settings {
  if (typeof window === "undefined") return DEFAULTS
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY)
    if (!raw) return DEFAULTS
    const parsed = JSON.parse(raw) as Partial<Settings>
    return { ...DEFAULTS, ...parsed }
  } catch {
    return DEFAULTS
  }
}

/**
 * Settings + theme class management.
 *
 * The theme is applied as a class on <html> (dark / light / system). The
 * system mode picks dark or light via the prefers-color-scheme media query at
 * CSS level (see src/index.css), so we just set the `system` class and let
 * CSS handle the rest.
 */
export function useSettings() {
  const [settings, setSettings] = useState<Settings>(() => readStored())

  // Persist on change.
  useEffect(() => {
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(settings))
    } catch {
      // localStorage may be unavailable (private mode); ignore.
    }
  }, [settings])

  // Apply theme class to <html>.
  useEffect(() => {
    const root = document.documentElement
    root.classList.remove("dark", "light", "system")
    root.classList.add(settings.theme)
  }, [settings.theme])

  const setTheme = useCallback((theme: ThemeMode) => {
    setSettings((prev) => ({ ...prev, theme }))
  }, [])

  const setLanguage = useCallback((language: string) => {
    setSettings((prev) => ({ ...prev, language }))
  }, [])

  const setPlayback = useCallback((playback: PlaybackMode) => {
    setSettings((prev) => ({ ...prev, playback }))
  }, [])

  return { settings, setTheme, setLanguage, setPlayback }
}
