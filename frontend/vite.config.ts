import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Docker Compose runs Vite in a different container from the FastAPI service.
// The default continues to support ordinary non-Docker local development.
const apiProxyTarget = process.env.TASKPLANNER_VITE_API_PROXY_TARGET || "http://localhost:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": apiProxyTarget,
    },
  },
});
