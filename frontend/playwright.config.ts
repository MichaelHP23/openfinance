import { defineConfig } from "@playwright/test";

// Assumes the API stack is up: `docker compose up -d`.
export default defineConfig({
  testDir: "./e2e",
  use: { baseURL: "http://localhost:5173" },
  webServer: [
    { command: "npm run dev", url: "http://localhost:5173", reuseExistingServer: true },
    // Service worker registration is gated on import.meta.env.PROD (see src/main.tsx) —
    // it's meaningless against unbundled dev-mode modules. pwa.spec.ts targets this one
    // instead of the default baseURL above.
    {
      command: "npm run build && npm run preview -- --port 4174",
      url: "http://localhost:4174",
      reuseExistingServer: true,
      timeout: 120_000,
    },
  ],
});
