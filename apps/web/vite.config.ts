import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import path from 'node:path'

export default defineConfig({
  // Dev WebSockets bypass the vite proxy (see comment below). Build-time
  // constant lets webcall.ts route the WS to the real API host without
  // disturbing HTTP requests, which go through the same-origin proxy.
  define: {
    __VITE_API_ORIGIN__: JSON.stringify(
      process.env.VITE_API_ORIGIN || 'http://127.0.0.1:8000',
    ),
  },
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    port: 5173,
    proxy: {
      // Same-origin proxy for the API so the session cookie (SameSite=Lax)
      // actually rides on dashboard fetches in dev. With a true cross-origin
      // setup (web:5174 → api:8000), Lax cookies are dropped on every XHR
      // and the user looks signed in but every call 401s. Proxying makes the
      // browser treat /v1/* as same-origin.
      '/v1': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        // ws upgrades are routed to the API directly via __VITE_API_ORIGIN__
        // below — Vite 8's WS proxy throws EPIPE under load and isn't worth
        // fighting for the dev-only path.
        ws: false,
      },
      '/healthz': { target: 'http://127.0.0.1:8000', changeOrigin: true },
    },
  },
  build: {
    rolldownOptions: {
      output: {
        manualChunks: (id: string) => {
          if (!id.includes('node_modules')) return undefined
          if (id.includes('@xyflow')) return 'flow'
          if (id.includes('recharts') || id.includes('d3-')) return 'charts'
          if (id.includes('lucide-react')) return 'icons'
          if (
            id.includes('react-dom') ||
            id.includes('react-router') ||
            /node_modules[\\/]react[\\/]/.test(id) ||
            /node_modules[\\/]scheduler[\\/]/.test(id)
          ) {
            return 'react-vendor'
          }
          return undefined
        },
      },
    },
  },
})
