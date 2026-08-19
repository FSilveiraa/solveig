import { defineConfig } from "vite";
import { svelte } from "@sveltejs/vite-plugin-svelte";

// The SPA is built into the Python package's `static/` directory, which
// `server.py` serves under "/". During development, run `npm run dev` and
// point the solveig web-interface backend at Vite's proxy so the SPA and the
// API stay on one origin.
export default defineConfig({
  plugins: [svelte()],
  build: {
    outDir: "../static",
    emptyOutDir: true,
  },
  server: {
    // Dev-only: forward API + event traffic to the solveig backend.
    proxy: {
      "/events": "http://127.0.0.1:8080",
      "/api": "http://127.0.0.1:8080",
    },
  },
});