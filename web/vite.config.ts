import { defineConfig } from "vite";
import { svelte } from "@sveltejs/vite-plugin-svelte";

export default defineConfig({
  plugins: [svelte()],
  build: {
    outDir: "../server/finanzen/static/app",
    emptyOutDir: true,
    target: "safari16",
  },
  server: {
    proxy: { "/api": "http://127.0.0.1:8750", "/connect": "http://127.0.0.1:8750" },
  },
  test: { environment: "node", include: ["src/**/*.test.ts"] },
});
