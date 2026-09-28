import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// The api serves the built app from src/cmbs_radar/api/web; in development
// `npm run dev` proxies /api to a running `uv run cmbs-api`.
export default defineConfig({
  plugins: [react()],
  build: { outDir: "../src/cmbs_radar/api/web", emptyOutDir: true },
  server: { proxy: { "/api": "http://127.0.0.1:8080" } },
  test: { environment: "jsdom", globals: true, setupFiles: ["./src/setupTests.ts"] },
});
