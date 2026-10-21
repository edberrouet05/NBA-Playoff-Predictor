"use client";
import { useEffect, useState } from "react";

/** True once `loading` has lasted `ms`: the free Render server sleeps when idle and takes up to
 *  a minute to answer the first request, so a page can say so instead of a bare "Loading…". */
export function useWakeHint(loading: boolean, ms = 4000): boolean {
  const [slow, setSlow] = useState(false);
  useEffect(() => {
    if (!loading) return;
    const timer = setTimeout(() => setSlow(true), ms);
    return () => clearTimeout(timer);
  }, [loading, ms]);
  return loading && slow;
}

export const WAKE_HINT = "Waking up the server — the first visit can take up to a minute.";
