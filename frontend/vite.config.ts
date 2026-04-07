import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  base: '/arbitrage/',
  plugins: [react()],
  server: {
    port: 5273,
    strictPort: true,
    host: '127.0.0.1',
    proxy: {
      '/arbitrage/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        rewrite: (p) => p.replace(/^\/arbitrage/, ''),
      },
      '/arbitrage/ws': {
        target: 'ws://localhost:8000',
        ws: true,
        rewrite: (p) => p.replace(/^\/arbitrage/, ''),
      },
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      '/ws': {
        target: 'ws://localhost:8000',
        ws: true,
      },
    },
  },
})
