import type { CapacitorConfig } from "@capacitor/cli";

/**
 * Capacitor native-shell configuration (iOS + Android app-store builds).
 *
 * The web app itself is bundled INTO the binary from `dist/` — there is no
 * remote-URL loading (Apple Guideline 4.2 rejects thin remote wrappers, and
 * bundling keeps the field app usable offline from first launch). The API
 * base URL is baked in at build time via VITE_API_URL, exactly like the web
 * deploy — see .github/workflows/mobile.yml.
 *
 * appId is the reverse-DNS identifier registered with both stores. It can
 * NEVER change after first store submission — chosen once, deliberately.
 */
const config: CapacitorConfig = {
  appId: "com.harboriq.app",
  appName: "HarborIQ",
  webDir: "dist",
  // Restrict the WebView to app-bundled content; all API traffic goes over
  // HTTPS via fetch to VITE_API_URL (Zero Trust: no cleartext, no mixed
  // origin surprises).
  server: {
    androidScheme: "https",
    iosScheme: "https",
    cleartext: false,
  },
  ios: {
    // Match the PWA theme; contentInset handled by safe-area CSS already in
    // the app shell.
    backgroundColor: "#f8fafc",
  },
  android: {
    backgroundColor: "#f8fafc",
    // Never allow the debug bridge in release builds.
    allowMixedContent: false,
  },
  plugins: {
    SplashScreen: {
      launchShowDuration: 800,
      launchAutoHide: true,
      backgroundColor: "#7e14ff",
      showSpinner: false,
    },
    StatusBar: {
      style: "LIGHT",
      backgroundColor: "#7e14ff",
    },
  },
};

export default config;
