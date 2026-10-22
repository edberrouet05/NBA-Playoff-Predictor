"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { teamHref } from "../../components/teamLinks";
import { PctCell } from "../../components/PowerTable";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// ── Types (mirror /api/nba/standings and /api/nba/projections) ─────────────────

interface StandingsTeam {
  name: string; abbr: string; seed: number | null; w: number; l: number; pct: string; gb: number;
  home: string; road: string; last10: string; streak: string; diff: number;
}
interface Division { name: string; teams: StandingsTeam[]; }
interface Conference { name: "East" | "West"; teams: StandingsTeam[]; divisions: Division[]; }
interface StandingsData { season: string; conferences: Conference[]; }
interface Projection {
  team: string; projected_wins: number; playoff_pct: number; top6_pct: number; top_seed_pct: number; title_pct: number;
}
interface ProjectionsData { simulations: number; teams: Projection[]; }

type View = "conference" | "division";

// ── Cells ──────────────────────────────────────────────────────────────────────

function TeamLogo({ abbr, team }: { abbr: string; team: string }) {
  // Remember which URL failed, so a new team gets a fresh attempt
  const [failedSrc, setFailedSrc] = useState<string | null>(null);
  const url = `https://a.espncdn.com/i/teamlogos/nba/500/${abbr.toLowerCase()}.png`;
  if (failedSrc === url) return <span className="w-6 h-6 flex-shrink-0 text-[9px] font-bold text-gray-500 flex items-center justify-center">{abbr}</span>;
  return <img src={url} alt={team} className="w-6 h-6 object-contain flex-shrink-0" onError={() => setFailedSrc(url)} />;
}

function Streak({ s }: { s: string }) {
  if (!s || s === "-") return <span className="text-gray-400">–</span>;
  const win = s.startsWith("W");
  return <span className={`font-semibold ${win ? "text-green-600 dark:text-green-400" : "text-red-500 dark:text-red-400"}`}>{s}</span>;
}

const th = "px-2 py-2 text-center text-xs font-semibold text-gray-400 dark:text-gray-500 whitespace-nowrap";
const td = "px-2 py-2.5 text-center tabular-nums text-gray-700 dark:text-gray-300 whitespace-nowrap";

/** One standings table. `cutoffs` draws the lines after the 6th (playoffs) and 10th (play-in) teams. */
function StandingsTable({ title, teams, proj, cutoffs }: {
  title: string; teams: StandingsTeam[]; proj: Record<string, Projection>; cutoffs: boolean;
}) {
  const hasProj = Object.keys(proj).length > 0;
  return (
    <div className="bg-white dark:bg-gray-900 border border-gray-100 dark:border-transparent shadow-sm rounded-2xl overflow-hidden">
      <p className="px-5 pt-4 pb-1 text-[11px] font-bold text-gray-500 uppercase tracking-widest">{title}</p>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-100 dark:border-gray-800">
              <th className="pl-5 pr-2 py-2 text-left text-xs font-semibold text-gray-400 dark:text-gray-500 w-full">Team</th>
              <th className={th}>W</th><th className={th}>L</th><th className={th}>PCT</th><th className={th}>GB</th>
              <th className={th}>HOME</th><th className={th}>ROAD</th><th className={th}>L10</th>
              <th className={th}>STRK</th><th className={th} title="Point differential per game">DIFF</th>
              {hasProj && <>
                <th className={`${th} border-l border-gray-100 dark:border-gray-800`} title="Average final wins across the simulations">PROJ W</th>
                <th className={th} title="Chance to make the playoffs: a top-6 seed or through the play-in">PLAYOFFS</th>
                <th className={th} title="Chance of a top-6 seed (no play-in)">TOP 6</th>
                <th className={`${th} pr-5`} title="Chance to win the NBA title">TITLE</th>
              </>}
            </tr>
          </thead>
          <tbody>
            {teams.map((t, i) => {
              const p = proj[t.name];
              const line = cutoffs && (i === 6 || i === 10)
                ? (i === 6 ? "border-t-2 border-gray-300 dark:border-gray-600" : "border-t-2 border-dashed border-gray-300 dark:border-gray-600")
                : "border-t border-gray-50 dark:border-gray-800/60";
              return (
                <tr key={t.name} className={`${line} hover:bg-gray-50 dark:hover:bg-gray-800/40`}>
                  <td className="pl-5 pr-2 py-2.5">
                    <div className="flex items-center gap-2.5 min-w-[12rem]">
                      {cutoffs && <span className="w-5 text-right text-xs font-bold text-gray-400 tabular-nums">{i + 1}</span>}
                      <TeamLogo abbr={t.abbr} team={t.name} />
                      <Link href={teamHref("nba", t.name)} className="font-medium text-gray-800 dark:text-gray-200 whitespace-nowrap hover:underline">{t.name}</Link>
                    </div>
                  </td>
                  <td className={`${td} font-semibold text-gray-900 dark:text-white`}>{t.w}</td>
                  <td className={td}>{t.l}</td>
                  <td className={td}>{t.pct}</td>
                  <td className={td}>{t.gb === 0 ? "–" : t.gb.toFixed(1)}</td>
                  <td className={td}>{t.home}</td>
                  <td className={td}>{t.road}</td>
                  <td className={td}>{t.last10}</td>
                  <td className={td}><Streak s={t.streak} /></td>
                  <td className={`${td} ${t.diff > 0 ? "text-green-600 dark:text-green-400" : t.diff < 0 ? "text-red-500 dark:text-red-400" : ""}`}>
                    {t.diff > 0 ? "+" : ""}{t.diff.toFixed(1)}
                  </td>
                  {hasProj && <>
                    <td className={`${td} border-l border-gray-100 dark:border-gray-800 font-semibold`}>{p ? p.projected_wins.toFixed(1) : "–"}</td>
                    <td className={td}>{p ? <PctCell v={p.playoff_pct} /> : "–"}</td>
                    <td className={td}>{p ? <PctCell v={p.top6_pct} /> : "–"}</td>
                    <td className={`${td} pr-5`}>{p ? <PctCell v={p.title_pct} /> : "–"}</td>
                  </>}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ── Page ───────────────────────────────────────────────────────────────────────

export default function NBAStandingsPage() {
  const [data, setData] = useState<StandingsData | null>(null);
  const [proj, setProj] = useState<Record<string, Projection>>({});
  const [sims, setSims] = useState<number | null>(null);
  const [error, setError] = useState("");
  const [view, setView] = useState<View>("conference");

  useEffect(() => {
    fetch(`${API}/api/nba/standings`)
      .then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); })
      .then(setData)
      .catch(e => setError(`Could not load the standings. (${e.message})`));
    fetch(`${API}/api/nba/projections`)
      .then(r => (r.ok ? r.json() : null))
      .then((d: ProjectionsData | null) => {
        if (!d) return;
        setProj(Object.fromEntries(d.teams.map(t => [t.team, t])));
        setSims(d.simulations);
      })
      .catch(() => {});
  }, []);

  return (
    <main className="px-4 md:px-6 py-6 md:py-8">
      <div className="mb-5 flex flex-col sm:flex-row sm:items-end sm:justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Standings {data?.season ?? ""}</h1>
          <p className="text-gray-500 text-sm mt-1">Records, form and where the season is headed.</p>
        </div>
        <div className="flex gap-1 bg-gray-100 dark:bg-gray-800 rounded-xl p-1 self-start">
          {(["conference", "division"] as View[]).map(v => (
            <button key={v} onClick={() => setView(v)}
              className={`px-4 py-1.5 rounded-lg text-xs font-semibold capitalize transition-colors ${
                view === v ? "bg-white dark:bg-gray-900 text-gray-900 dark:text-white shadow-sm" : "text-gray-500"}`}>
              {v}
            </button>
          ))}
        </div>
      </div>

      {error && (
        <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800/40 rounded-xl p-4 text-red-600 dark:text-red-400 text-sm mb-4">{error}</div>
      )}
      {!data && !error && (
        <div className="bg-white dark:bg-gray-900 border border-gray-100 dark:border-transparent shadow-sm rounded-2xl p-8 text-center text-sm text-gray-400">Loading…</div>
      )}

      {data && (
        <div className="flex flex-col gap-4">
          {data.conferences.map(conf => view === "conference" ? (
            <StandingsTable key={conf.name} title={`${conf.name}ern Conference`} teams={conf.teams} proj={proj} cutoffs />
          ) : (
            <div key={conf.name} className="flex flex-col gap-3">
              <p className="text-xs font-bold text-gray-400 uppercase tracking-widest mt-2">{conf.name}ern Conference</p>
              {conf.divisions.map(d => (
                <StandingsTable key={d.name} title={d.name} teams={d.teams} proj={proj} cutoffs={false} />
              ))}
            </div>
          ))}
        </div>
      )}

      <div className="mt-5 text-xs text-gray-500 dark:text-gray-400 space-y-1.5">
        {view === "conference" && (
          <p>
            Top 6 of each conference go straight to the playoffs (solid line); seeds 7-10 play the play-in (dashed line).
            Teams with the same record are listed in ESPN&apos;s order.
          </p>
        )}
        {sims && (
          <p>
            Projections: {sims.toLocaleString()} simulations of the rest of the season with our model&apos;s game probabilities,
            then the play-in and the playoffs. <Link href="/nba/power?tab=projections" className="underline">All projections →</Link>
          </p>
        )}
      </div>
    </main>
  );
}
