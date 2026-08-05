import { useEffect, useRef, useState } from "react";
import { usersApi } from "../lib/services";
import type { User } from "../types/api";

/**
 * Phase 11 "live" dispatch board location tracking.
 *
 * HONESTY NOTE: this is *best-effort tracking while the web app tab is open
 * and the technician has granted browser geolocation permission* -- it is
 * NOT true background/mobile tracking. The browser's Geolocation API only
 * fires while this page is open (and, depending on OS/browser power
 * settings, only while the tab is in the foreground). Closing the tab or
 * putting the phone to sleep stops pings immediately; there is no native
 * background service. True background tracking would require a native
 * mobile app or a persistent background service and is deliberately
 * deferred to Phase 12 (see docs/COMPETITIVE_PARITY_ROADMAP.md).
 *
 * Only technicians ping (matches the backend's `POST /users/me/location-ping`,
 * which is open to any authenticated user, but the dispatch board's map
 * only reads back `role='technician'` rows via `GET /users/technician-locations`
 * -- pinging as a non-technician is harmless but pointless, so this hook
 * no-ops for other roles).
 */

const DEFAULT_INTERVAL_MS = 3 * 60 * 1000; // 3 minutes -- within the spec's 2-5 min range.

export type LocationPingStatus =
  | "idle"
  | "unsupported"
  | "requesting-permission"
  | "denied"
  | "active"
  | "error";

function geolocationUnsupported(): boolean {
  return typeof navigator === "undefined" || !navigator.geolocation;
}

/** Purely derived from the inputs -- safe to compute during render (no
 * effect needed) and used both as the initial state and to detect when the
 * caller's `user` identity changes into/out of "technician". */
function deriveStatus(isTechnician: boolean): LocationPingStatus {
  if (!isTechnician) return "idle";
  if (geolocationUnsupported()) return "unsupported";
  return "requesting-permission";
}

export function useLocationPing(
  user: User | null | undefined,
  intervalMs: number = DEFAULT_INTERVAL_MS,
) {
  const isTechnician = !!user && user.role === "technician";
  const [status, setStatus] = useState<LocationPingStatus>(() => deriveStatus(isTechnician));
  const [lastPingAt, setLastPingAt] = useState<Date | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  // Tracks the technician-ness we last started (or skipped) polling for, so
  // the effect below can tell "still the same subject, ignore" apart from
  // "the user actually changed" without an unconditional setState call.
  const trackedForRef = useRef<boolean | null>(null);

  useEffect(() => {
    if (!isTechnician || geolocationUnsupported()) {
      // Only reset visible status if we're moving away from a technician
      // we were previously tracking -- avoids a bare setState on every
      // render when nothing has actually changed.
      if (trackedForRef.current !== isTechnician) {
        trackedForRef.current = isTechnician;
        setStatus(deriveStatus(isTechnician));
      }
      return;
    }
    trackedForRef.current = isTechnician;

    let cancelled = false;

    function pingOnce() {
      setStatus((prev) => (prev === "active" ? prev : "requesting-permission"));
      navigator.geolocation.getCurrentPosition(
        (position) => {
          if (cancelled) return;
          const { latitude, longitude } = position.coords;
          usersApi
            .pingLocation({ latitude: String(latitude), longitude: String(longitude) })
            .then(() => {
              if (cancelled) return;
              setStatus("active");
              setLastPingAt(new Date());
            })
            .catch(() => {
              if (!cancelled) setStatus("error");
            });
        },
        (err) => {
          if (cancelled) return;
          // PERMISSION_DENIED = 1 per the Geolocation API spec.
          setStatus(err.code === 1 ? "denied" : "error");
        },
        { enableHighAccuracy: false, maximumAge: 60_000, timeout: 20_000 },
      );
    }

    pingOnce();
    timerRef.current = setInterval(pingOnce, intervalMs);

    return () => {
      cancelled = true;
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [isTechnician, intervalMs]);

  return { status, lastPingAt };
}
