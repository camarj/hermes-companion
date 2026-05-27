import { Toaster } from "sonner"
import { Loader2 } from "lucide-react"
import { AppShell } from "@/components/app-shell"
import { LoginScreen } from "@/components/login-screen"
import { useAppConfig } from "@/hooks/useAppConfig"
import { useAuth } from "@/hooks/useAuth"
import { useSettings } from "@/hooks/useSettings"

function App() {
  const { config } = useAppConfig()
  const auth = useAuth()
  const { settings, setTheme, setLanguage } = useSettings()

  if (auth.status === "loading") {
    return (
      <div className="flex h-dvh items-center justify-center bg-background text-muted-foreground">
        <Loader2 className="h-6 w-6 animate-spin" />
      </div>
    )
  }

  if (auth.status === "anonymous" || !auth.user) {
    return (
      <>
        <LoginScreen config={config} onLogin={auth.login} />
        <Toaster richColors closeButton />
      </>
    )
  }

  return (
    <>
      <AppShell
        config={config}
        user={auth.user}
        settings={settings}
        onThemeChange={setTheme}
        onLanguageChange={setLanguage}
        onLogout={auth.logout}
      />
      <Toaster richColors closeButton />
    </>
  )
}

export default App
