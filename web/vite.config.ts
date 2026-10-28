import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// En dev, le front (port 5173) relaie /api vers le back FastAPI.
// En production, le back sert web/dist lui-même : une seule adresse à ouvrir via Tailscale.
const api = process.env.LOOPCAST_API ?? "http://127.0.0.1:8787";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    proxy: { "/api": { target: api, changeOrigin: true } },
  },
  build: { target: "es2022", sourcemap: false },
});
