"use client";
// Favorite teams, kept in this browser only (no account): their games come first on the Today
// page, with a star. Stored as "league:Team Name" keys, e.g. "nhl:Montreal Canadiens".
import { useSyncExternalStore } from "react";

export type League = "nba" | "nfl" | "mlb" | "nhl";

const KEY = "courtedge:favorites";
const EVENT = "courtedge-favorites";
const EMPTY: string[] = [];
let cachedRaw: string | null = null;
let cached: string[] = EMPTY;

function read(): string[] {
  let raw: string | null = null;
  try { raw = localStorage.getItem(KEY); } catch { /* storage blocked: no favorites */ }
  if (raw !== cachedRaw) {
    cachedRaw = raw;
    try { cached = raw ? (JSON.parse(raw) as string[]) : EMPTY; } catch { cached = EMPTY; }
  }
  return cached;
}

function subscribe(onChange: () => void) {
  window.addEventListener(EVENT, onChange);
  window.addEventListener("storage", onChange);   // another tab changed them
  return () => { window.removeEventListener(EVENT, onChange); window.removeEventListener("storage", onChange); };
}

export const favoriteKey = (league: League, team: string) => `${league}:${team}`;

/** The favorite keys; empty during the server render. */
export function useFavorites(): string[] {
  return useSyncExternalStore(subscribe, read, () => EMPTY);
}

export function toggleFavorite(league: League, team: string) {
  const key = favoriteKey(league, team);
  const now = read();
  const next = now.includes(key) ? now.filter(k => k !== key) : [...now, key];
  try { localStorage.setItem(KEY, JSON.stringify(next)); } catch { /* storage blocked */ }
  window.dispatchEvent(new Event(EVENT));
}

export function FavoriteStar({ league, team, size = 16, className = "" }: {
  league: League; team: string; size?: number; className?: string;
}) {
  const on = useFavorites().includes(favoriteKey(league, team));
  return (
    <button type="button"
      onClick={e => { e.preventDefault(); e.stopPropagation(); toggleFavorite(league, team); }}
      title={on ? `Remove ${team} from your teams` : `Add ${team} to your teams`}
      aria-label={on ? `Remove ${team} from your teams` : `Add ${team} to your teams`}
      aria-pressed={on}
      className={`inline-flex items-center justify-center transition-colors ${on ? "text-yellow-400" : "text-gray-300 dark:text-gray-600 hover:text-yellow-400"} ${className}`}>
      <svg width={size} height={size} viewBox="0 0 16 16" fill={on ? "currentColor" : "none"} stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round">
        <path d="M8 1.6l1.9 3.9 4.3.6-3.1 3 .7 4.3L8 11.4l-3.8 2 .7-4.3-3.1-3 4.3-.6z" />
      </svg>
    </button>
  );
}
