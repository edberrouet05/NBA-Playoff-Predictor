"use client";
import { useLayoutEffect, useState, type RefObject } from "react";

const MIN_ROWS = 3;
const BOTTOM_GAP = 16;      // matches the sidebar's max-h calc(100vh - top - 1rem)
const WIDE_SCREEN = 1280;   // Tailwind xl — the sidebar is only sticky from here up

/**
 * How many rows of a list fit between its top in the sticky sidebar (the ancestor marked
 * `data-sidebar`) and the bottom of the screen, leaving room for what follows it in its card
 * (the "See all" link). Cards further down the sidebar scroll, so a long one (NBA injuries)
 * does not keep the list short. Re-measures when the window or the sidebar's content changes.
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
      // Sidebar content above the list, then the rest of its card below it
      const above = list.getBoundingClientRect().top - sidebar.getBoundingClientRect().top + sidebar.scrollTop;
      const after = list.nextElementSibling as HTMLElement | null;
      const below = (after ? after.offsetHeight + parseFloat(getComputedStyle(after).marginTop || "0") : 0) + 24;
      const avail = window.innerHeight - top - BOTTOM_GAP - above - below;
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
