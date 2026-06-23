"use client";
import React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";

// ── Icons ──────────────────────────────────────────────────────────────────────

function IconGames() {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18" fill="currentColor">
      <rect x="1" y="1" width="7" height="7" rx="1.5" />
      <rect x="10" y="1" width="7" height="7" rx="1.5" />
      <rect x="1" y="10" width="7" height="7" rx="1.5" />
      <rect x="10" y="10" width="7" height="7" rx="1.5" />
    </svg>
  );
}

function IconBracket() {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M2 4h4v3H2M2 11h4v3H2" />
      <path d="M6 5.5h3v5H6M9 8h4v3H9M13 9.5h3" />
    </svg>
  );
}

function IconMatchup() {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M2 6h14M12 3l4 3-4 3" />
      <path d="M16 12H2M6 9l-4 3 4 3" />
    </svg>
  );
}

function IconStats() {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18" fill="currentColor">
      <rect x="2" y="10" width="4" height="6" rx="1" />
      <rect x="7" y="6" width="4" height="10" rx="1" />
      <rect x="12" y="2" width="4" height="14" rx="1" />
    </svg>
  );
}

function IconStandings() {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M2 4h14" />
      <path d="M2 8h14" />
      <path d="M2 12h14" />
      <path d="M2 16h8" />
    </svg>
  );
}

function IconLog() {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <rect x="2" y="2" width="14" height="14" rx="2" />
      <path d="M5 6.5l2 2 4-4" />
      <path d="M5 11.5l2 2 4-4" />
    </svg>
  );
}

// ── Sport detection ────────────────────────────────────────────────────────────

type Sport = "nba" | "mlb" | "nhl";

function getSport(path: string): Sport {
  if (path.startsWith("/mlb")) return "mlb";
  if (path.startsWith("/nhl")) return "nhl";
  return "nba";
}

// ── Sidebar config per sport ───────────────────────────────────────────────────

type SidebarLink = {
  href: string;
  Icon: () => React.JSX.Element;
  label: string;
  isActive: (path: string) => boolean;
};

const SPORT_SIDEBAR: Record<Sport, SidebarLink[]> = {
  nba: [
    {
      href: "/",
      Icon: IconGames,
      label: "Games",
      isActive: (p) => p === "/" || p.startsWith("/game"),
    },
    {
      href: "/bracket",
      Icon: IconBracket,
      label: "Bracket",
      isActive: (p) => p === "/bracket" || p.startsWith("/team"),
    },
    {
      href: "/predictions",
      Icon: IconLog,
      label: "Predictions",
      isActive: (p) => p === "/predictions",
    },
    {
      href: "/stats",
      Icon: IconStats,
      label: "Stats",
      isActive: (p) => p === "/stats",
    },
  ],
  mlb: [
    {
      href: "/mlb",
      Icon: IconGames,
      label: "Games",
      isActive: (p) => p === "/mlb",
    },
    {
      href: "/mlb/standings",
      Icon: IconStandings,
      label: "Standings",
      isActive: (p) => p === "/mlb/standings",
    },
    {
      href: "/mlb/predictions",
      Icon: IconLog,
      label: "Predictions",
      isActive: (p) => p === "/mlb/predictions",
    },
    {
      href: "/mlb/stats",
      Icon: IconStats,
      label: "Stats",
      isActive: (p) => p === "/mlb/stats",
    },
  ],
  nhl: [
    {
      href: "/nhl",
      Icon: IconGames,
      label: "Games",
      isActive: (p) => p === "/nhl",
    },
    {
      href: "/nhl/bracket",
      Icon: IconBracket,
      label: "Bracket",
      isActive: (p) => p === "/nhl/bracket",
    },
    {
      href: "/nhl/matchup",
      Icon: IconMatchup,
      label: "Matchup",
      isActive: (p) => p === "/nhl/matchup",
    },
    {
      href: "/nhl/stats",
      Icon: IconStats,
      label: "Stats",
      isActive: (p) => p === "/nhl/stats",
    },
  ],
};

// ── Sidebar component ──────────────────────────────────────────────────────────

export default function Sidebar() {
  const path  = usePathname();
  const sport = getSport(path);
  const links = SPORT_SIDEBAR[sport];

  return (
    <>
      {/* Desktop: left sidebar */}
      <aside className="hidden md:flex fixed left-0 top-0 h-screen w-[68px] bg-[#0d0d0d] flex-col items-center pt-5 pb-6 z-20 border-r border-white/[0.06]">
        <nav className="flex flex-col gap-1 mt-2">
          {links.map(({ href, Icon, label, isActive }) => (
            <Link
              key={href}
              href={href}
              title={label}
              className={`w-11 h-11 flex items-center justify-center rounded-xl transition-colors ${
                isActive(path)
                  ? "bg-white/10 text-white"
                  : "text-gray-600 hover:text-gray-300 hover:bg-white/[0.05]"
              }`}
            >
              <Icon />
            </Link>
          ))}
        </nav>
      </aside>

      {/* Mobile: bottom tab bar */}
      <nav className="md:hidden fixed bottom-0 left-0 right-0 z-20 bg-[#0d0d0d] border-t border-white/[0.06] flex items-center justify-around px-2 h-16">
        {links.map(({ href, Icon, label, isActive }) => (
          <Link
            key={href}
            href={href}
            className={`flex flex-col items-center gap-1 flex-1 py-2 rounded-xl transition-colors ${
              isActive(path)
                ? "text-white"
                : "text-gray-600 hover:text-gray-300"
            }`}
          >
            <Icon />
            <span className="text-[10px] font-medium">{label}</span>
          </Link>
        ))}
      </nav>
    </>
  );
}
