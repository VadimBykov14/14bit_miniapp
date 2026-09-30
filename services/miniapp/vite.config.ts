import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Локальная разработка ходит в боевой API: поднимать весь стек второй раз
// ради проверки вёрстки нет смысла.
const proxy = {
  "/api": {
    target: process.env.API_PROXY_TARGET ?? "https://14-bit-max.ru",
    changeOrigin: true,
    secure: true,
  },
};

export default defineConfig({
  plugins: [react()],
  server: { host: "127.0.0.1", port: 5173, proxy },
  preview: { host: "127.0.0.1", port: 4173, proxy },
  build: { outDir: "dist", sourcemap: false },
});
