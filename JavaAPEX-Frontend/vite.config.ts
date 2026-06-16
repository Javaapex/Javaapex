import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  base: "/",
  build: {
    modulePreload: false,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes("vite/preload-helper")) {
            return "preload-helper";
          }

          if (!id.includes("node_modules")) {
            return undefined;
          }

          if (id.includes("react-router-dom") || id.includes("react-router")) {
            return "router-vendor";
          }

          if (id.includes("react-icons")) {
            return "icons-vendor";
          }

          if (id.includes("jspdf")) {
            return "jspdf-vendor";
          }

          if (id.includes("html2canvas")) {
            return "html2canvas-vendor";
          }

          if (id.includes("fflate")) {
            return "fflate-vendor";
          }

          if (id.includes("dompurify")) {
            return "sanitizer-vendor";
          }

          return undefined;
        },
      },
    },
  },

  server: {
    port: 5173,
    host: true,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        secure: false,
      }
    }
  }
})
