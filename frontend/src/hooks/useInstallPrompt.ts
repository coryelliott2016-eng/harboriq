import { useEffect, useState, useCallback } from "react";

// `beforeinstallprompt` isn't in the standard lib.dom.d.ts yet.
interface BeforeInstallPromptEvent extends Event {
  prompt: () => Promise<void>;
  userChoice: Promise<{ outcome: "accepted" | "dismissed" }>;
}

function isStandaloneDisplayMode(): boolean {
  if (typeof window === "undefined") return false;
  const mediaStandalone = window.matchMedia?.("(display-mode: standalone)").matches ?? false;
  // iOS Safari's non-standard flag for "already added to home screen".
  const iosStandalone = (window.navigator as unknown as { standalone?: boolean }).standalone;
  return mediaStandalone || Boolean(iosStandalone);
}

function isIos(): boolean {
  if (typeof navigator === "undefined") return false;
  const ua = navigator.userAgent || "";
  const isAppleMobile = /iphone|ipad|ipod/i.test(ua);
  // iPadOS 13+ reports as "Macintosh" with touch support.
  const isIpadOs13Plus =
    /Macintosh/.test(ua) && typeof navigator.maxTouchPoints === "number" && navigator.maxTouchPoints > 1;
  return isAppleMobile || isIpadOs13Plus;
}

/**
 * Drives the "Install this app" UI (Phase 12). iOS Safari never fires
 * `beforeinstallprompt` and has no programmatic install API at all -- the
 * only path is the user manually tapping Share -> Add to Home Screen -- so
 * on iOS we always surface manual instructions instead of a button.
 * Everywhere else (Chrome/Edge/Android) we listen for the standard
 * `beforeinstallprompt` event and drive the native install flow from it.
 */
export function useInstallPrompt() {
  const [deferredPrompt, setDeferredPrompt] = useState<BeforeInstallPromptEvent | null>(null);
  const [installed, setInstalled] = useState(isStandaloneDisplayMode());

  useEffect(() => {
    const onBeforeInstallPrompt = (event: Event) => {
      event.preventDefault();
      setDeferredPrompt(event as BeforeInstallPromptEvent);
    };
    const onAppInstalled = () => {
      setInstalled(true);
      setDeferredPrompt(null);
    };
    window.addEventListener("beforeinstallprompt", onBeforeInstallPrompt);
    window.addEventListener("appinstalled", onAppInstalled);
    return () => {
      window.removeEventListener("beforeinstallprompt", onBeforeInstallPrompt);
      window.removeEventListener("appinstalled", onAppInstalled);
    };
  }, []);

  const promptInstall = useCallback(async () => {
    if (!deferredPrompt) return false;
    await deferredPrompt.prompt();
    const { outcome } = await deferredPrompt.userChoice;
    setDeferredPrompt(null);
    return outcome === "accepted";
  }, [deferredPrompt]);

  return {
    installed,
    isIos: isIos(),
    canPromptInstall: deferredPrompt !== null,
    promptInstall,
  };
}
