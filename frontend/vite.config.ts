import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import path from 'node:path'

// The new React app is served by FastAPI's StaticFiles mount at
// `/static/next/`. Building into `static/next/` keeps everything under a
// single static directory and avoids touching backend mounts in this PR.
export default defineConfig({
  base: '/static/next/',
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  build: {
    outDir: 'static/next',
    emptyOutDir: true,
  },
  server: {
    port: 5173,
    proxy: {
      // REST endpoints
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        // WebSocket upgrade for /api/realtime
        ws: true,
      },
    },
  },
})
