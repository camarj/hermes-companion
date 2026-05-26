function App() {
  return (
    <main className="dark flex h-dvh flex-col items-center justify-center gap-4 bg-bg p-8 text-fg">
      <div className="flex h-16 w-16 items-center justify-center rounded-full border-2 border-accent font-serif text-2xl text-accent">
        H
      </div>
      <h1 className="font-serif text-h3">hermes-companion</h1>
      <p className="text-meta tracking-widest text-fg-subtle uppercase">
        Next frontend · scaffold OK
      </p>
      <p className="max-w-sm text-center text-body-sm text-fg-muted">
        This is the React + Vite + Tailwind v4 + AI SDK 6 scaffold. The legacy
        single-file frontend is still authoritative at <code className="font-mono text-fg">/</code>.
      </p>
    </main>
  )
}

export default App
