import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 3527,
    strictPort: true,
    proxy: {
      "/api": "http://127.0.0.1:8629",
    },
  },
  preview: {
    host: "127.0.0.1",
    port: 4627,
    strictPort: true,
  },
});
