import { useState } from "react";
import { useInstallPrompt } from "../hooks/useInstallPrompt";
import { Button } from "./ui";

/**
 * "Install this app" banner (Phase 12). Two completely different UX paths:
 *  - iOS Safari: no install API exists at all, so we show the manual
 *    Share -> Add to Home Screen steps (dismissible, persisted in
 *    localStorage so it doesn't nag every visit).
 *  - Everywhere else supporting `beforeinstallprompt` (Chrome/Edge/Android):
 *    a real "Install" button that drives the native browser prompt.
 * If the app is already installed (standalone display mode) or the
 * standard prompt isn't available and we're not on iOS, renders nothing.
 */
const DISMISS_KEY = "harboriq-install-banner-dismissed";

export function InstallAppBanner() {
  const { installed, isIos, canPromptInstall, promptInstall } = useInstallPrompt();
  const [dismissed, setDismissed] = useState(
    () => typeof window !== "undefined" && localStorage.getItem(DISMISS_KEY) === "1",
  );

  if (installed || dismissed) return null;
  if (!isIos && !canPromptInstall) return null;

  const dismiss = () => {
    localStorage.setItem(DISMISS_KEY, "1");
    setDismissed(true);
  };

  return (
    <div
      role="region"
      aria-label="Install HarborIQ"
      className="mb-4 rounded-md border border-violet-200 bg-violet-50 px-4 py-3 text-sm text-violet-900"
    >
      {isIos ? (
        <div className="flex items-start justify-between gap-3">
          <div>
            <p className="font-medium">Install HarborIQ on your iPhone</p>
            <p className="mt-1 text-violet-800">
              Tap the Share icon in Safari, then choose{" "}
              <strong>Add to Home Screen</strong>. HarborIQ will open full-screen, like an
              app, and keeps working offline — no App Store account needed.
            </p>
          </div>
          <button
            onClick={dismiss}
            aria-label="Dismiss install instructions"
            className="text-violet-500 hover:text-violet-700"
          >
            &times;
          </button>
        </div>
      ) : (
        <div className="flex items-center justify-between gap-3">
          <p className="font-medium">Install HarborIQ for quick, offline access</p>
          <div className="flex items-center gap-2">
            <Button onClick={() => void promptInstall()}>Install</Button>
            <button
              onClick={dismiss}
              aria-label="Dismiss install prompt"
              className="text-violet-500 hover:text-violet-700"
            >
              &times;
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
