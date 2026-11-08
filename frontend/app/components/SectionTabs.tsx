"use client";
import { useSyncExternalStore } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";

// Tabs at the top of the pages grouped under one sidebar icon: "Standings" (standings, power
// index, playoff bracket) and "Model" (season record, how the model was tested).

export type Sport = "nba" | "nfl" | "mlb";
export type Section = "standings" | "model";

interface Tab { href: string; label: string }

const noSubscribe = () => () => {};

function tabsFor(sport: Sport, section: Section, bracketSeason: boolean): Tab[] {
  if (section === "model") {
    return [
      { href: `/${sport}/performance`, label: "Record" },
      { href: sport === "nba" ? "/stats" : `/${sport}/stats`, label: "How it's tested" },
    ];
  }
  if (sport === "nba") {
    return [
      { href: "/nba/standings", label: "Standings" },
      { href: "/nba/power", label: "Power index" },
      ...(bracketSeason ? [{ href: "/bracket", label: "Playoff bracket" }] : []),
    ];
  }
  if (sport === "nfl") {
    return [{ href: "/nfl/standings", label: "Standings" }, { href: "/nfl/power", label: "Power index" }];
  }
  return [{ href: "/mlb/standings", label: "Standings" }];
}

export function SectionTabs({ sport, section }: { sport: Sport; section: Section }) {
  const path = usePathname();
  // The NBA bracket tab shows from the playoffs (April) until the next season starts (October)
  const month = useSyncExternalStore(noSubscribe, () => new Date().getMonth(), () => -1);
  const bracketSeason = (month >= 3 && month <= 8) || path === "/bracket";
  const tabs = tabsFor(sport, section, bracketSeason);
  if (tabs.length < 2) return null;
  return (
    <nav className="px-4 md:px-6 pt-5 -mb-2">
      <div className="inline-flex gap-1 bg-gray-100 dark:bg-gray-800 rounded-xl p-1">
        {tabs.map(t => {
          const active = path === t.href;
          return (
            <Link key={t.href} href={t.href}
              className={`px-4 py-1.5 rounded-lg text-xs font-semibold transition-colors ${
                active ? "bg-white dark:bg-gray-900 text-gray-900 dark:text-white shadow-sm" : "text-gray-500 hover:text-gray-800 dark:hover:text-gray-200"}`}>
              {t.label}
            </Link>
          );
        })}
      </div>
    </nav>
  );
}
