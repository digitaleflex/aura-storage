import { useEffect, useState } from "react";

/**
 * Live browser connectivity for the offline banner. The queue provider tracks
 * connectivity too (for announcements), but the banner must reflect
 * `navigator.onLine` directly so it appears even before any file is queued.
 */
export function useOnlineStatus(): boolean {
  const [online, setOnline] = useState(() =>
    typeof navigator === "undefined" ? true : navigator.onLine,
  );

  useEffect(() => {
    const handleOnline = () => setOnline(true);
    const handleOffline = () => setOnline(false);
    // Resync in case connectivity changed between first render and effect.
    setOnline(navigator.onLine);
    window.addEventListener("online", handleOnline);
    window.addEventListener("offline", handleOffline);
    return () => {
      window.removeEventListener("online", handleOnline);
      window.removeEventListener("offline", handleOffline);
    };
  }, []);

  return online;
}
