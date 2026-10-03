import path from 'node:path'
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { '@': path.resolve(import.meta.dirname, './src') } },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test-setup.ts'],
    css: false,
  },
  server: {
    port: 3000,
    // `pnpm dev` talks to a backend started on the host (uvicorn, port 8000)
    proxy: { '/api': process.env.BACKEND_URL ?? 'http://localhost:8000' },
  },
})
