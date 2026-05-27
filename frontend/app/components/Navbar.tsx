"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";

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

const links = [
  { href: "/",        Icon: IconGames,    label: "NBA"     },
  { href: "/bracket", Icon: IconBracket,  label: "Bracket" },
  { href: "/matchup", Icon: IconMatchup,  label: "Matchup" },
  { href: "/stats",   Icon: IconStats,    label: "Stats"   },
];

export default function Sidebar() {
  const path = usePathname();
  return (
    <aside className="fixed left-0 top-0 h-screen w-[68px] bg-[#0d0d0d] flex flex-col items-center pt-5 pb-6 z-20 border-r border-white/[0.06]">
      <nav className="flex flex-col gap-1 mt-2">
        {links.map(({ href, Icon, label }) => (
          <Link
            key={href}
            href={href}
            title={label}
            className={`w-11 h-11 flex items-center justify-center rounded-xl transition-colors ${
              path === href ||
              (href === "/bracket" && path.startsWith("/team"))
                ? "bg-white/10 text-white"
                : "text-gray-600 hover:text-gray-300 hover:bg-white/[0.05]"
            }`}
          >
            <Icon />
          </Link>
        ))}
      </nav>
    </aside>
  );
}
