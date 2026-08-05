import { useEffect, useState } from "react";

/** Tracks browser connectivity via the `online`/`offline` events, backed by
 * `navigator.onLine` for the initial value. Note this only reflects
 * network-adapter state (e.g. still true on a captive portal with no real
 * internet) -- actual API reachability is separately detected by fetch
 * failures in useFieldJobs/offline queue senders, which is why the field
 * view's offline banner is driven by *both* this hook and observed fetch
 * failures, not this alone. */
export function useOnlineStatus(): boolean {
  const [online, setOnline] = useState(() =>
    typeof navigator === "undefined" ? true : navigator.onLine,
  );

  useEffect(() => {
    const goOnline = () => setOnline(true);
    const goOffline = () => setOnline(false);
    window.addEventListener("online", goOnline);
    window.addEventListener("offline", goOffline);
    return () => {
      window.removeEventListener("online", goOnline);
      window.removeEventListener("offline", goOffline);
    };
  }, []);

  return online;
}
