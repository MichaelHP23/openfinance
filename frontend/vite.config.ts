import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  test: {
    environment: 'jsdom',
    setupFiles: './src/test-setup.ts',
    // e2e/ belongs to Playwright — vitest must not try to run those files.
    include: ['src/**/*.{test,spec}.{ts,tsx}'],
  },
})
