"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

const SPORT_LINKS = [
  { href: "/",    label: "NBA", key: "nba", match: (p: string) => !p.startsWith("/mlb") && !p.startsWith("/nfl") },
  { href: "/mlb", label: "MLB", key: "mlb", match: (p: string) =>  p.startsWith("/mlb") },
  { href: "/nfl", label: "NFL", key: "nfl", match: (p: string) =>  p.startsWith("/nfl") },
  { href: "#",    label: "NHL", key: "nhl", match: () => false, disabled: true },
];

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
  return (
    <div className="flex items-center gap-3 sm:gap-4 ml-1 sm:ml-2">
      {SPORT_LINKS.map(({ href, label, key, match, disabled }) => {
        const active = match(path);
        if (disabled) {
          return (
            <span
              key={label}
              className="hidden sm:inline text-base font-bold text-gray-300 dark:text-gray-600 tracking-wide cursor-default select-none"
              title="Coming soon"
            >
              {label}
            </span>
          );
        }
        return (
          <Link
            key={label}
            href={href}
            title={live[key] ? `${label}: game in progress` : undefined}
            className={`relative text-sm sm:text-base font-bold tracking-wide transition-colors ${
              active
                ? "text-red-600"
                : "text-gray-400 dark:text-gray-500 hover:text-gray-700 dark:hover:text-gray-300"
            }`}
          >
            {label}
            {live[key] && (
              <span className="absolute -top-0.5 -right-2 w-1.5 h-1.5 rounded-full bg-red-500 animate-pulse" aria-label="live" />
            )}
          </Link>
        );
      })}
    </div>
  );
}
