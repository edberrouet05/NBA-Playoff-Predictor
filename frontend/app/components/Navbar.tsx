"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";

const links = [
  { href: "/",        label: "Bracket"  },
  { href: "/matchup", label: "Matchup"  },
  { href: "/stats",   label: "Stats"    },
];

export default function Navbar() {
  const path = usePathname();
  return (
    <nav className="bg-white border-b border-gray-200 sticky top-0 z-10">
      <div className="max-w-2xl mx-auto px-4 h-14 flex items-center justify-between">
        <span className="font-bold text-gray-900 tracking-tight">
          CourtEdge
        </span>
        <div className="flex gap-1">
          {links.map((l) => (
            <Link
              key={l.href}
              href={l.href}
              className={`px-4 py-1.5 rounded-lg text-sm font-medium transition-colors ${
                path === l.href
                  ? "bg-red-600 text-white"
                  : "text-gray-500 hover:text-gray-900 hover:bg-gray-100"
              }`}
            >
              {l.label}
            </Link>
          ))}
        </div>
      </div>
    </nav>
  );
}
