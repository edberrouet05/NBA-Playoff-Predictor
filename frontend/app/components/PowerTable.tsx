"use client";
import { useMemo, useState, useSyncExternalStore } from "react";
import Link from "next/link";
import { teamHref } from "./teamLinks";

// Sortable team table and cells shared by the NFL and NBA power-index pages.

const noSubscribe = () => () => {};

/** The page tab, opened from ?tab=… (shareable links) until the user picks one; picking one
 *  updates the URL. The server render (no URL) shows `fallback`. */
export function useUrlTab<T extends string>(tabs: readonly T[], fallback: T): [T, (t: T) => void] {
  const fromUrl = useSyncExternalStore(
    noSubscribe,
    () => new URLSearchParams(window.location.search).get("tab"),
    () => null,
  );
  const [picked, setPicked] = useState<T | null>(null);
  const tab = picked ?? (tabs.find(t => t === fromUrl) ?? fallback);
  const select = (t: T) => {
    setPicked(t);
    const url = new URL(window.location.href);
    if (t === fallback) url.searchParams.delete("tab"); else url.searchParams.set("tab", t);
    window.history.replaceState(null, "", url);
  };
  return [tab, select];
}

export const signed = (v: number, d = 1) => `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v).toFixed(d)}`;

export function fmtPct(v: number): string {
  if (v >= 99.95) return ">99%";
  if (v > 0 && v < 0.5) return "<1%";
  return `${Math.round(v)}%`;
}

export function PctCell({ v }: { v: number }) {
  // Magnitude as a single-hue fill behind the number; the number stays in text ink
  const alpha = 0.06 + (v / 100) * 0.34;
  return (
    <span className="inline-block min-w-[3.25rem] px-1.5 py-0.5 rounded-md text-xs font-semibold tabular-nums text-gray-800 dark:text-gray-100"
      style={{ background: `rgba(59, 130, 246, ${alpha})` }}>
      {fmtPct(v)}
    </span>
  );
}

export function Rank({ r }: { r: number }) {
  return <span className="ml-1 text-[10px] text-gray-400 tabular-nums">#{r}</span>;
}

export interface Col<T> {
  key: string;
  label: string;
  title: string;                // header tooltip / glossary text
  value: (r: T) => number | string | null;
  render: (r: T) => React.ReactNode;
  lowerIsBetter?: boolean;      // default sort direction
  group?: string;
  highlight?: boolean;
}

export function SortTable<T extends { team: string }>({ rows, cols, initial, league, logo }: {
  rows: T[]; cols: Col<T>[]; initial: string; league: "nfl" | "nba"; logo: (r: T) => React.ReactNode;
}) {
  const [sortKey, setSortKey] = useState(initial);
  const [asc, setAsc] = useState(!!cols.find(c => c.key === initial)?.lowerIsBetter);
  const col = cols.find(c => c.key === sortKey) ?? cols[0];
  const sorted = useMemo(() => [...rows].sort((a, b) => {
    const va = col.value(a), vb = col.value(b);
    if (va === null) return 1;
    if (vb === null) return -1;
    const cmp = typeof va === "string" ? va.localeCompare(String(vb)) : (va as number) - (vb as number);
    return asc ? cmp : -cmp;
  }), [rows, col, asc]);

  const groups: { name: string; span: number }[] = [];
  cols.forEach(c => {
    const g = c.group ?? "";
    if (groups.length && groups[groups.length - 1].name === g) groups[groups.length - 1].span++;
    else groups.push({ name: g, span: 1 });
  });
  const hasGroups = groups.some(g => g.name);

  const onSort = (c: Col<T>) => {
    if (c.key === sortKey) setAsc(a => !a);
    else { setSortKey(c.key); setAsc(!!c.lowerIsBetter); }
  };

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          {hasGroups && (
            <tr>
              <th className="sticky left-0 bg-white dark:bg-gray-900" />
              {groups.map((g, i) => (
                <th key={i} colSpan={g.span}
                  className={`px-2 pt-3 pb-1 text-[10px] font-bold uppercase tracking-widest text-gray-400 text-center ${g.name ? "border-b border-gray-100 dark:border-gray-800" : ""}`}>
                  {g.name}
                </th>
              ))}
            </tr>
          )}
          <tr className="border-b border-gray-100 dark:border-gray-800">
            <th className="sticky left-0 z-10 bg-white dark:bg-gray-900 px-4 py-2 text-left text-xs font-semibold text-gray-400">Team</th>
            {cols.map(c => (
              <th key={c.key} title={c.title}
                className={`px-2 py-2 text-right text-xs font-semibold whitespace-nowrap cursor-pointer select-none ${
                  c.key === sortKey ? "text-gray-900 dark:text-white" : "text-gray-400 hover:text-gray-600 dark:hover:text-gray-200"
                } ${c.highlight ? "bg-blue-50/70 dark:bg-blue-500/10" : ""}`}
                onClick={() => onSort(c)}>
                <span className="underline decoration-dotted decoration-gray-300 underline-offset-2">{c.label}</span>
                {c.key === sortKey && <span className="ml-0.5">{asc ? "▲" : "▼"}</span>}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sorted.map(r => (
            <tr key={r.team} className="border-b last:border-0 border-gray-50 dark:border-gray-800/60 hover:bg-gray-50 dark:hover:bg-gray-800/40">
              <td className="sticky left-0 z-10 bg-white dark:bg-gray-900 px-4 py-2.5">
                <div className="flex items-center gap-2.5 min-w-[11rem]">
                  {logo(r)}
                  <Link href={teamHref(league, r.team)} className="font-medium text-gray-800 dark:text-gray-200 whitespace-nowrap inline-block transition-transform hover:scale-105 origin-left">{r.team}</Link>
                </div>
              </td>
              {cols.map(c => (
                <td key={c.key} className={`px-2 py-2.5 text-right tabular-nums text-gray-700 dark:text-gray-300 whitespace-nowrap ${c.highlight ? "bg-blue-50/70 dark:bg-blue-500/10 font-semibold text-gray-900 dark:text-white" : ""}`}>
                  {c.render(r)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function Glossary({ cols }: { cols: { key: string; label: string; title: string }[] }) {
  return (
    <div>
      <h2 className="text-[11px] font-bold uppercase tracking-widest text-gray-700 dark:text-gray-300 mb-2">Glossary</h2>
      <dl className="grid sm:grid-cols-2 gap-x-8 gap-y-1.5">
        {cols.map(c => (
          <div key={c.key}><dt className="inline font-semibold text-gray-700 dark:text-gray-300">{c.label}: </dt><dd className="inline">{c.title}</dd></div>
        ))}
      </dl>
    </div>
  );
}
