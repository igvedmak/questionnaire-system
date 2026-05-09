import { defineConfig } from 'vitest/config'
import { createLogger } from 'vite'
import react from '@vitejs/plugin-react-swc'

const logger = createLogger()
const warn = logger.warn.bind(logger)
logger.warn = (msg, opts) => {
  if (msg.includes('esbuildOptions')) return  // known Vitest 4 / Vite 6 compat noise
  warn(msg, opts)
}

export default defineConfig({
  customLogger: logger,
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      // Forward all API paths to the local FastAPI server in dev mode.
      // In production the Docker build sets VITE_API_URL instead.
      '/templates': 'http://localhost:8000',
      '/questionnaires': 'http://localhost:8000',
      '/audit': 'http://localhost:8000',
      '/respondents': 'http://localhost:8000',
      '/analytics': 'http://localhost:8000',
      '/webhooks': 'http://localhost:8000',
      '/llm': 'http://localhost:8000',
      '/health': 'http://localhost:8000',
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
  },
})
