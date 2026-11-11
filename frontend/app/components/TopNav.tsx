"use client";
import { useEffect, useState, useSyncExternalStore } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// `offMonths`: months (0 = January) with no games — the sport is left out of the phone header then
const SPORT_LINKS = [
  { href: "/nba", label: "NBA", key: "nba", offMonths: [6, 7, 8], match: (p: string) => p !== "/" && !p.startsWith("/mlb") && !p.startsWith("/nfl") && !p.startsWith("/nhl") },
  { href: "/nfl", label: "NFL", key: "nfl", offMonths: [2, 3, 4, 5, 6, 7], match: (p: string) =>  p.startsWith("/nfl") },
  { href: "/nhl", label: "NHL", key: "nhl", offMonths: [6, 7, 8], match: (p: string) =>  p.startsWith("/nhl") },
  { href: "/mlb", label: "MLB", key: "mlb", offMonths: [10, 11, 0, 1], match: (p: string) =>  p.startsWith("/mlb") },
];

const noSubscribe = () => () => {};

// Which leagues have a game on right now, refreshed every minute
function useLiveLeagues(): Record<string, boolean> {
  const [live, setLive] = useState<Record<string, boolean>>({});
  useEffect(() => {
    const load = () =>
      fetch(`${API}/api/live_now`)
        .then(r => (r.ok ? r.json() : {}))
        .then(setLive)
        .catch(() => {});
    load();
    const id = setInterval(load, 60_000);
    return () => clearInterval(id);
  }, []);
  return live;
}

export default function TopNav() {
  const path = usePathname();
  const live = useLiveLeagues();
  const month = useSyncExternalStore(noSubscribe, () => new Date().getMonth(), () => -1);
  // Sports with a game on come first; otherwise the usual order (sort is stable)
  const links = [...SPORT_LINKS].sort((a, b) => Number(!!live[b.key]) - Number(!!live[a.key]));
  return (
    <div className="flex items-center gap-3 sm:gap-4 ml-1 sm:ml-2">
      {links.map(({ href, label, key, offMonths, match }) => {
        const active = match(path);
        // Phones have room for three sports: one out of season is hidden (unless you are on it)
        const phoneHidden = offMonths.includes(month) && !active && !live[key];
        return (
          <Link
            key={label}
            href={href}
            title={live[key] ? `${label}: game in progress` : undefined}
            className={`relative text-sm sm:text-base font-bold tracking-wide transition-colors ${phoneHidden ? "hidden sm:inline" : ""} ${
              active
                ? "text-red-600"
                : "text-gray-400 dark:text-gray-500 hover:text-gray-700 dark:hover:text-gray-300"
            }`}
          >
            {label}
            {live[key] && (
              <span className="absolute left-1/2 -translate-x-1/2 -bottom-1.5 w-1.5 h-1.5 rounded-full bg-red-500 animate-pulse" aria-label="live" />
            )}
          </Link>
        );
      })}
    </div>
  );
}
