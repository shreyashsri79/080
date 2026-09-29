import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { defineConfig } from 'vite'

// `npm run dev:api`: forward /api to a running `regimerain serve` (hot reload + real runs).
const apiProxy = process.env.API_PROXY

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: apiProxy ? { proxy: { '/api': { target: apiProxy, changeOrigin: true } } } : undefined,
  build: {
    rollupOptions: {
      output: { manualChunks: (id) => (id.includes('maplibre-gl') ? 'maplibre' : undefined) },
    },
  },
})
