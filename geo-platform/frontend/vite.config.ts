import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ mode }) => ({
  plugins: [
    react(),
    {
      name: "geo-release-build-marker",
      generateBundle() {
        if (mode !== "release") return;
        this.emitFile({
          type: "asset",
          fileName: "geo-release-build.json",
          source: JSON.stringify({ mode: "release", release_first_slice: true }),
        });
      },
    },
  ],
  server: {
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8000"
    }
  }
}));
