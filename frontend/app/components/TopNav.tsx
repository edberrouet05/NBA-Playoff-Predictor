"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";

const SPORT_LINKS = [
  { href: "/",    label: "NBA", match: (p: string) => !p.startsWith("/mlb") },
  { href: "/mlb", label: "MLB", match: (p: string) =>  p.startsWith("/mlb") },
  { href: "#",    label: "NHL", match: () => false, disabled: true },
];

export default function TopNav() {
  const path = usePathname();
  return (
    <div className="flex items-center gap-4 ml-2">
      {SPORT_LINKS.map(({ href, label, match, disabled }) => {
        const active = match(path);
        if (disabled) {
          return (
            <span
              key={label}
              className="text-base font-bold text-gray-300 dark:text-gray-600 tracking-wide cursor-default select-none"
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
            className={`text-base font-bold tracking-wide transition-colors ${
              active
                ? "text-red-600"
                : "text-gray-400 dark:text-gray-500 hover:text-gray-700 dark:hover:text-gray-300"
            }`}
          >
            {label}
          </Link>
        );
      })}
    </div>
  );
}
