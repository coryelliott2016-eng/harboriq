/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { VitePWA } from "vite-plugin-pwa";

// https://vite.dev/config/
export default defineConfig({
  plugins: [
    react(),
    // Phase 12: installable PWA for the technician field app. `autoUpdate`
    // means a new deploy's service worker takes over silently on next
    // navigation rather than requiring the user to dismiss a prompt --
    // appropriate here since the app shell has no offline "long session"
    // risk (see README's PWA section for the full write-up).
    VitePWA({
      registerType: "autoUpdate",
      includeAssets: ["favicon.svg", "icons.svg", "icons/apple-touch-icon.png"],
      manifest: {
        name: "HarborIQ",
        short_name: "HarborIQ",
        description: "HarborIQ field app — offline-capable job queue, photos, signatures, and time clock for marine service technicians.",
        theme_color: "#7e14ff",
        background_color: "#f8fafc",
        display: "standalone",
        start_url: "/field",
        scope: "/",
        icons: [
          { src: "/icons/pwa-192x192.png", sizes: "192x192", type: "image/png" },
          { src: "/icons/pwa-512x512.png", sizes: "512x512", type: "image/png" },
          {
            src: "/icons/maskable-512x512.png",
            sizes: "512x512",
            type: "image/png",
            purpose: "maskable",
          },
        ],
      },
      workbox: {
        // App-shell precache (JS/CSS/HTML/icons) so the field view keeps
        // working with no signal at all. API responses are NOT cached by
        // the service worker -- the app-level IndexedDB cache in
        // src/lib/offlineDb.ts is the source of truth for job data offline
        // (see README's "Offline architecture" section for why these are
        // deliberately two separate layers).
        globPatterns: ["**/*.{js,css,html,svg,png,ico,woff2}"],
        navigateFallback: "index.html",
        runtimeCaching: [
          {
            urlPattern: ({ url }: { url: URL }) => url.pathname.startsWith("/api/"),
            handler: "NetworkOnly",
          },
        ],
      },
      devOptions: {
        enabled: false,
      },
    }),
  ],
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
  },
});
