"use client";
import { useLayoutEffect, useState, type RefObject } from "react";

const MIN_ROWS = 3;
const BOTTOM_GAP = 16;      // matches the sidebar's max-h calc(100vh - top - 1rem)
const WIDE_SCREEN = 1280;   // Tailwind xl — the sidebar is only sticky from here up

/**
 * How many rows of a list fit so the sticky sidebar (the ancestor marked `data-sidebar`)
 * needs no inner scrolling. Re-measures when the window or the sidebar's content changes.
 * Below the xl breakpoint (sidebar not sticky) it returns `total`.
 */
export function useFitRows(listRef: RefObject<HTMLElement | null>, total: number, enabled: boolean): number {
  const [fit, setFit] = useState(total);

  useLayoutEffect(() => {
    if (!enabled) return;
    const list = listRef.current;
    const sidebar = list?.closest<HTMLElement>("[data-sidebar]");
    if (!list || !sidebar) return;

    const measure = () => {
      if (window.innerWidth < WIDE_SCREEN || list.children.length === 0) {
        setFit(total);
        return;
      }
      const rowH = list.offsetHeight / list.children.length;
      const top = parseFloat(getComputedStyle(sidebar).top) || 0;
      const others = sidebar.scrollHeight - list.offsetHeight;   // everything in the sidebar but these rows
      const avail = window.innerHeight - top - BOTTOM_GAP - others;
      setFit(Math.max(MIN_ROWS, Math.min(total, Math.floor(avail / rowH))));
    };

    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(sidebar);
    window.addEventListener("resize", measure);
    return () => { ro.disconnect(); window.removeEventListener("resize", measure); };
  }, [listRef, total, enabled]);

  return enabled ? fit : total;
}
