import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8765",
        changeOrigin: true,
        ws: true,
      },
      // Workspace API: /{slug}/api/... — must not match /src/api/... (frontend source)
      "^/(?!src|@vite|@fs|@id|node_modules|assets)[^/]+/api": {
        target: "http://127.0.0.1:8765",
        changeOrigin: true,
      },
      "/health": {
        target: "http://127.0.0.1:8765",
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
});
