import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  return { plugins: [react()], resolve: { alias: { "@": path.resolve(__dirname, "./src") } },
    server: { port: 5173, proxy: { "/api": { target: env.VITE_PROXY_TARGET || "http://localhost:8080", changeOrigin: true } } } };
});
