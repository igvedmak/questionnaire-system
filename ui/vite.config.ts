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
  server: { port: 5173 },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
  },
})
