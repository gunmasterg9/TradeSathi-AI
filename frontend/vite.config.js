import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const backendPort = env.VITE_BACKEND_PORT || env.BACKEND_PORT || '8000'
  const backendUrl =
    env.VITE_BACKEND_URL ||
    (env.VITE_API_BASE_URL ? env.VITE_API_BASE_URL.replace(/\/$/, '') : `http://127.0.0.1:${backendPort}`)

  return {
    plugins: [react()],
    server: {
      proxy: {
        '/api': {
          target: backendUrl,
          changeOrigin: true,
          configure: (proxy) => {
            proxy.on('error', (err, _req, res) => {
              console.warn(`[Vite Proxy] Could not connect to TradeSathi API backend at ${backendUrl}: ${err.message}`)
              if (res && !res.headersSent && typeof res.writeHead === 'function') {
                res.writeHead(502, { 'Content-Type': 'application/json' })
                res.end(
                  JSON.stringify({
                    detail: `Cannot connect to TradeSathi API backend at ${backendUrl} (${err.message}). Ensure the FastAPI server is running on port ${backendPort} or configure VITE_BACKEND_PORT.`,
                  })
                )
              }
            })
          },
        },
      },
    },
  }
})
