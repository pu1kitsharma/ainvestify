import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      // The FastAPI backend runs on 8000 locally (uvicorn api.main:app) --
      // proxying /api means frontend code just calls fetch('/api/...') with
      // no base URL to configure per environment.
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      // Compiled documents reference chart images at /memo_output/... --
      // see api/main.py's StaticFiles mount.
      '/memo_output': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
})
