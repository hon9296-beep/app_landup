import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// 도커: VITE_API_TARGET=http://backend-java:8080, VITE_WS_TARGET=http://backend:8000
// 로컬(Java): http://localhost:8081
// 로컬(Python 직접): http://localhost:8000
const apiTarget = process.env.VITE_API_TARGET || 'http://localhost:8081'
const wsTarget = process.env.VITE_WS_TARGET || 'http://localhost:8000'

export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 3000,
    watch: {
      usePolling: true,
      interval: 1000,
    },
    proxy: {
      '/api': {
        target: apiTarget,
      },
      '/ws': {
        target: wsTarget,
        ws: true,
        changeOrigin: true,
      },
    },
  },
  appType: 'spa',
})
