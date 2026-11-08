"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { teamHref } from "../../components/teamLinks";
import { nhlLogo } from "../nhlTeams";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// ── Types (mirror /api/nhl/standings) ─────────────────────────────────────────

interface StandingsTeam {
  team: string; abbr: string; conference: string; gp: number; w: number; l: number; otl: number;
  pts: number; pts_pct: number; goal_diff: number; streak: number; elo: number; rank: number; elo_rank: number;
}
interface Division { division: string; conference: "East" | "West"; teams: StandingsTeam[] }
interface StandingsData { season: string; divisions: Division[] }

type View = "division" | "conference";

function TeamLogo({ team }: { team: string }) {
  // Remember which URL failed, so a new team gets a fresh attempt
  const [failedSrc, setFailedSrc] = useState<string | null>(null);
  const url = nhlLogo(team);
  if (failedSrc === url) return <span className="w-6 h-6 flex-shrink-0" />;
  // eslint-disable-next-line @next/next/no-img-element
  return <img src={url} alt="" className="w-6 h-6 object-contain flex-shrink-0" onError={() => setFailedSrc(url)} />;
}

const th = "px-2 py-2 text-center text-xs font-semibold text-gray-400 dark:text-gray-500 whitespace-nowrap";
const td = "px-2 py-2.5 text-center tabular-nums text-gray-700 dark:text-gray-300 whitespace-nowrap";

/** One standings table; `cutoff` draws a line after that many teams (playoff spots). */
function StandingsTable({ title, teams, cutoff }: { title: string; teams: StandingsTeam[]; cutoff?: number }) {
  return (
    <div className="bg-white dark:bg-gray-900 border border-gray-100 dark:border-transparent shadow-sm rounded-2xl overflow-hidden">
      <p className="px-5 pt-4 pb-1 text-[11px] font-bold text-gray-500 uppercase tracking-widest">{title}</p>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-100 dark:border-gray-800">
              <th className="pl-5 pr-2 py-2 text-left text-xs font-semibold text-gray-400 dark:text-gray-500 w-full">Team</th>
              <th className={th}>GP</th><th className={th}>W</th><th className={th}>L</th><th className={th}>OTL</th>
              <th className={th}>PTS</th><th className={th} title="Points won out of points possible">P%</th>
              <th className={th} title="Goal differential">DIFF</th><th className={th}>STRK</th>
              <th className={th} title="Our team rating rank (Elo), 1 = best in the league">ELO</th>
            </tr>
          </thead>
          <tbody>
            {teams.map((t, i) => (
              <tr key={t.team} className={`border-b border-gray-50 dark:border-gray-800/60 last:border-0 ${
                cutoff && i === cutoff - 1 ? "border-b-2 border-b-gray-200 dark:border-b-gray-700" : ""}`}>
                <td className="pl-5 pr-2 py-2.5">
                  <Link href={teamHref("nhl", t.team)} className="flex items-center gap-2.5 min-w-0 hover:underline">
                    <span className="w-4 text-xs text-gray-400 tabular-nums">{i + 1}</span>
                    <TeamLogo team={t.team} />
                    <span className="font-semibold text-gray-900 dark:text-white whitespace-nowrap">{t.team}</span>
                  </Link>
                </td>
                <td className={td}>{t.gp}</td><td className={td}>{t.w}</td><td className={td}>{t.l}</td><td className={td}>{t.otl}</td>
                <td className={`${td} font-bold text-gray-900 dark:text-white`}>{t.pts}</td>
                <td className={td}>{t.pts_pct.toFixed(3).replace(/^0/, "")}</td>
                <td className={`${td} ${t.goal_diff > 0 ? "text-green-600 dark:text-green-400" : t.goal_diff < 0 ? "text-red-500 dark:text-red-400" : ""}`}>
                  {t.goal_diff > 0 ? "+" : ""}{t.goal_diff}
                </td>
                <td className={`${td} font-semibold ${t.streak > 0 ? "text-green-600 dark:text-green-400" : "text-red-500 dark:text-red-400"}`}>
                  {t.streak > 0 ? `W${t.streak}` : t.streak < 0 ? `L${-t.streak}` : "–"}
                </td>
                <td className={td}>{t.elo_rank}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default function NHLStandingsPage() {
  const [data, setData] = useState<StandingsData | null>(null);
  const [error, setError] = useState("");
  const [view, setView] = useState<View>("division");

  useEffect(() => {
    fetch(`${API}/api/nhl/standings`)
      .then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); })
      .then(setData)
      .catch(e => setError(e.message));
  }, []);

  const sortTeams = (ts: StandingsTeam[]) => [...ts].sort((a, b) => b.pts - a.pts || a.gp - b.gp || b.w - a.w || b.goal_diff - a.goal_diff);

  return (
    <main className="px-4 md:px-6 py-6 md:py-8">
      <div className="flex flex-wrap items-end justify-between gap-3 mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Standings</h1>
          <p className="text-gray-500 text-sm mt-1">NHL {data?.season ?? ""} · 2 points for a win, 1 for an overtime or shootout loss</p>
        </div>
        <div className="inline-flex gap-1 bg-gray-100 dark:bg-gray-800 rounded-xl p-1">
          {(["division", "conference"] as View[]).map(v => (
            <button key={v} onClick={() => setView(v)}
              className={`px-4 py-1.5 rounded-lg text-xs font-semibold capitalize transition-colors ${
                view === v ? "bg-white dark:bg-gray-900 text-gray-900 dark:text-white shadow-sm" : "text-gray-500 hover:text-gray-800 dark:hover:text-gray-200"}`}>
              {v}
            </button>
          ))}
        </div>
      </div>

      {error && <p className="text-sm text-red-500">Could not load standings ({error}).</p>}
      {!data && !error && <p className="text-sm text-gray-400">Loading…</p>}

      {data && (
        <div className="grid grid-cols-1 xl:grid-cols-2 gap-5">
          {view === "division"
            ? data.divisions.map(d => <StandingsTable key={d.division} title={`${d.division} · ${d.conference}`} teams={d.teams} cutoff={3} />)
            : (["East", "West"] as const).map(c => (
                <StandingsTable key={c} title={`${c}ern Conference`}
                  teams={sortTeams(data.divisions.filter(d => d.conference === c).flatMap(d => d.teams))} cutoff={8} />
              ))}
        </div>
      )}
      <p className="text-xs text-gray-400 mt-4">
        The line marks playoff spots: top 3 of each division, then two wild cards per conference (8 teams in all).
        ELO = our rating rank across the league.
      </p>
    </main>
  );
}
