import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import path from 'node:path'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
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
