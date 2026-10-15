import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The browser only ever talks to THIS dev server (port 5173). Anything under
// /api is forwarded to the FastAPI backend (port 8000). Because the browser
// sees one origin, there is no cross-origin request and so no CORS to
// configure -- and the same-origin shape is what a built, served app would
// have too.
export default defineConfig({
  plugins: [react()],
  server: {
    // 127.0.0.1 explicitly: "localhost" can resolve to IPv6 (::1) only, which made the dev
    // server unreachable at http://127.0.0.1:5173 and invisible to IPv4 port checks.
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": { target: "http://127.0.0.1:8000", changeOrigin: false },
    },
  },
});
