import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, HashRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { registerSW } from "virtual:pwa-register";
import App from "./App.tsx";
import { AuthProvider } from "./context/AuthContext.tsx";
import "./index.css";

// Phase 12: register the service worker that makes the app installable and
// keeps the field view's app shell available with no network at all.
// `registerSW` is a no-op outside a real browser (e.g. under Vitest/jsdom)
// because vite-plugin-pwa only injects `navigator.serviceWorker` support
// checks -- still guarded explicitly here for clarity and testability.
if ("serviceWorker" in navigator) {
  registerSW({ immediate: true });
}

// Hosted-demo escape hatch: some staging hosts serve the SPA from a deep,
// non-root path where BrowserRouter can never match routes and deep links
// 404 at the static host. Building with VITE_ROUTER=hash switches to
// fragment-based routing (#/login, #/jobs/:id) with zero server config.
// Default (unset) remains BrowserRouter — production behavior unchanged.
const Router = import.meta.env.VITE_ROUTER === "hash" ? HashRouter : BrowserRouter;

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <Router>
        <AuthProvider>
          <App />
        </AuthProvider>
      </Router>
    </QueryClientProvider>
  </StrictMode>,
);
