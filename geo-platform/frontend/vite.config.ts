import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ mode }) => {
  const release = mode !== "legacy";
  const apiTarget = process.env.GEO_API_PROXY_TARGET || `http://127.0.0.1:${release ? 8021 : 8000}`;
  return {
    define: {
      "import.meta.env.VITE_GEO_RELEASE_FIRST_SLICE": JSON.stringify(release ? "1" : "0"),
    },
    plugins: [
      react(),
      {
        name: "geo-release-build-marker",
        configureServer(server) {
          server.middlewares.use("/__geo_dev_config", (_request, response) => {
            response.setHeader("Content-Type", "application/json");
            response.end(JSON.stringify({ release, api_target: apiTarget }));
          });
        },
        generateBundle() {
          if (!release) return;
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
      strictPort: true,
      proxy: {
        "/api": apiTarget
      }
    }
  };
});
