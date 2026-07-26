// vitest/config, not vite — it's the one whose type knows about `test`.
import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    // Docker on Windows/macOS does not forward filesystem events into the container,
    // so without polling the dev server never notices an edit and silently serves
    // stale code. Costs a little CPU; beats debugging a change that isn't running.
    watch: { usePolling: true, interval: 400 },
  },
  test: {
    environment: 'jsdom',
    setupFiles: './src/test-setup.ts',
    // e2e/ belongs to Playwright — vitest must not try to run those files.
    include: ['src/**/*.{test,spec}.{ts,tsx}'],
  },
})
