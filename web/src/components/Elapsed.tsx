import { useEffect, useState } from "react";

/** m:ss since `since` (ms epoch). Owns its 1 s timer, so only this node
 * re-renders each second, not the page around it. */
export function formatElapsed(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000));
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

export function Elapsed({ since }: { since: number | undefined }) {
  const [, tick] = useState(0);
  useEffect(() => {
    if (since === undefined) return;
    const id = setInterval(() => tick((n) => n + 1), 1000);
    return () => clearInterval(id);
  }, [since]);
  if (since === undefined) return null;
  return <span className="elapsed">{formatElapsed(Date.now() - since)}</span>;
}
