"use client";

import { useEffect, useState } from "react";

/**
 * Milliseconds since `startedAt`, ticking once a second while `running`.
 * Falls back to mount time when the server timestamp is unusable (clock skew).
 */
export function useElapsed(startedAtIso: string | null, running: boolean): number {
  const [start] = useState(() => {
    const now = Date.now();
    if (!startedAtIso) return now;
    const parsed = Date.parse(startedAtIso);
    if (Number.isNaN(parsed) || parsed > now || now - parsed > 24 * 60 * 60 * 1000) {
      return now;
    }
    return parsed;
  });

  const [elapsed, setElapsed] = useState(() => Date.now() - start);

  useEffect(() => {
    setElapsed(Date.now() - start);
    if (!running) return;
    const id = setInterval(() => setElapsed(Date.now() - start), 1000);
    return () => clearInterval(id);
  }, [start, running]);

  return elapsed;
}
