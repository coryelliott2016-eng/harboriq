/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_URL: string;
  /** Override when the backend renames its CSRF cookie (e.g. "__Host-csrf_token"
   * behind hosts that only forward __Host--prefixed cookies). Must match the
   * backend's CSRF_COOKIE_NAME setting. Defaults to "csrf_token". */
  readonly VITE_CSRF_COOKIE_NAME?: string;
  /** "hash" switches the SPA to HashRouter for hosts that serve the app from
   * a deep/non-root path (staging demo proxies). Unset = BrowserRouter. */
  readonly VITE_ROUTER?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
