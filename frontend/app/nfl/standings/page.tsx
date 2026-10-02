"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { teamHref } from "../../components/teamLinks";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// ── Types ──────────────────────────────────────────────────────────────────────

interface StandingsTeam {
  name: string;
  w: number;
  l: number;
  t: number;
  pct: string;
  pf: number;
  pa: number;
  point_diff: number;
  streak: string;
  win_pct_last5: number | null;
  point_diff_last5: number | null;
}

interface Division { name: string; teams: StandingsTeam[]; }
interface StandingsData { afc: Division[]; nfc: Division[]; }

interface Projection {
  team: string;
  projected_wins: number;
  playoff_pct: number;
  division_pct: number;
  top_seed_pct: number;
}
interface ProjectionsData { week: number; simulations: number; games_remaining: number; teams: Projection[]; }

function fmtPct(v: number | undefined): string {
  if (v === undefined) return "—";
  if (v >= 99.95) return ">99%";
  if (v > 0 && v < 0.5) return "<1%";
  return `${Math.round(v)}%`;
}

function PctCell({ v }: { v: number | undefined }) {
  // Magnitude as a single-hue fill behind the number; the number itself stays in text ink
  const alpha = v === undefined ? 0 : 0.08 + (v / 100) * 0.32;
  return (
    <td className="px-2 py-3 text-center">
      <span className="inline-block min-w-[3.25rem] px-1.5 py-0.5 rounded-md text-xs font-semibold tabular-nums text-gray-800 dark:text-gray-100"
        style={{ background: `rgba(59, 130, 246, ${alpha})` }}>
        {fmtPct(v)}
      </span>
    </td>
  );
}

// ── Team metadata ──────────────────────────────────────────────────────────────

const NFL_ABBR: Record<string, string> = {
  "Arizona Cardinals": "ARI", "Atlanta Falcons": "ATL", "Baltimore Ravens": "BAL",
  "Buffalo Bills": "BUF", "Carolina Panthers": "CAR", "Chicago Bears": "CHI",
  "Cincinnati Bengals": "CIN", "Cleveland Browns": "CLE", "Dallas Cowboys": "DAL",
  "Denver Broncos": "DEN", "Detroit Lions": "DET", "Green Bay Packers": "GB",
  "Houston Texans": "HOU", "Indianapolis Colts": "IND", "Jacksonville Jaguars": "JAX",
  "Kansas City Chiefs": "KC", "Las Vegas Raiders": "LV", "Los Angeles Chargers": "LAC",
  "Los Angeles Rams": "LAR", "Miami Dolphins": "MIA", "Minnesota Vikings": "MIN",
  "New England Patriots": "NE", "New Orleans Saints": "NO", "New York Giants": "NYG",
  "New York Jets": "NYJ", "Philadelphia Eagles": "PHI", "Pittsburgh Steelers": "PIT",
  "San Francisco 49ers": "SF", "Seattle Seahawks": "SEA", "Tampa Bay Buccaneers": "TB",
  "Tennessee Titans": "TEN", "Washington Commanders": "WSH",
};

function getAbbr(t: string) { return NFL_ABBR[t] ?? t.split(" ").pop()?.slice(0, 3).toUpperCase() ?? "???"; }
function getLogoUrl(t: string): string {
  const abbr = getAbbr(t);
  return abbr === "???" ? "" : `https://a.espncdn.com/i/teamlogos/nfl/500/${abbr.toLowerCase()}.png`;
}

// ── Team logo ──────────────────────────────────────────────────────────────────

function TeamLogo({ team }: { team: string }) {
  const [err, setErr] = useState(false);
  const url = getLogoUrl(team);
  if (!url || err) {
    return (
      <span className="w-6 h-6 flex-shrink-0 flex items-center justify-center text-[9px] font-bold text-gray-500">
        {getAbbr(team).slice(0, 2)}
      </span>
    );
  }
  return <img src={url} alt={team} className="w-6 h-6 object-contain flex-shrink-0" onError={() => setErr(true)} />;
}

// ── Streak badge ───────────────────────────────────────────────────────────────

function StreakBadge({ streak }: { streak: string }) {
  const isWin = streak.startsWith("W");
  return (
    <span className={`text-xs font-semibold px-1.5 py-0.5 rounded-md ${
      isWin
        ? "bg-green-100 dark:bg-green-500/20 text-green-700 dark:text-green-400"
        : "bg-red-100 dark:bg-red-500/20 text-red-600 dark:text-red-400"
    }`}>
      {streak}
    </span>
  );
}

// ── Division table ─────────────────────────────────────────────────────────────

function DivisionTable({ division, proj }: { division: Division; proj: Record<string, Projection> }) {
  const hasProj = Object.keys(proj).length > 0;
  return (
    <div className="bg-white dark:bg-gray-900 border border-gray-100 dark:border-transparent shadow-sm rounded-2xl overflow-hidden">

      <div className="px-5 py-3 border-b border-gray-100 dark:border-gray-800">
        <h3 className="text-xs font-bold text-gray-500 dark:text-gray-400 uppercase tracking-widest">
          {division.name}
        </h3>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-100 dark:border-gray-800">
              <th className="px-5 py-2 text-left text-xs font-semibold text-gray-400 dark:text-gray-500 w-full">Team</th>
              <th className="px-3 py-2 text-center text-xs font-semibold text-gray-400 dark:text-gray-500 whitespace-nowrap">W</th>
              <th className="px-3 py-2 text-center text-xs font-semibold text-gray-400 dark:text-gray-500 whitespace-nowrap">L</th>
              <th className="px-3 py-2 text-center text-xs font-semibold text-gray-400 dark:text-gray-500 whitespace-nowrap">T</th>
              <th className="px-3 py-2 text-center text-xs font-semibold text-gray-400 dark:text-gray-500 whitespace-nowrap">PCT</th>
              <th className="px-3 py-2 text-center text-xs font-semibold text-gray-400 dark:text-gray-500 whitespace-nowrap">PF</th>
              <th className="px-3 py-2 text-center text-xs font-semibold text-gray-400 dark:text-gray-500 whitespace-nowrap">PA</th>
              <th className="px-3 py-2 text-center text-xs font-semibold text-gray-400 dark:text-gray-500 whitespace-nowrap">DIFF</th>
              <th className="px-3 py-2 text-center text-xs font-semibold text-gray-400 dark:text-gray-500 whitespace-nowrap">STRK</th>
              {hasProj && <>
                <th className="px-2 py-2 text-center text-xs font-semibold text-gray-400 dark:text-gray-500 whitespace-nowrap border-l border-gray-100 dark:border-gray-800" title="Average final wins across simulations">PROJ W</th>
                <th className="px-2 py-2 text-center text-xs font-semibold text-gray-400 dark:text-gray-500 whitespace-nowrap" title="Chance to win the division">DIV</th>
                <th className="px-2 py-2 text-center text-xs font-semibold text-gray-400 dark:text-gray-500 whitespace-nowrap pr-5" title="Chance to make the playoffs">PLAYOFFS</th>
              </>}
            </tr>
          </thead>
          <tbody>
            {division.teams.map((team, i) => {
              const isFirst = i === 0;
              return (
                <tr
                  key={team.name}
                  className={`border-b last:border-0 border-gray-50 dark:border-gray-800/60 transition-colors hover:bg-gray-50 dark:hover:bg-gray-800/40 ${
                    isFirst ? "bg-gray-50/50 dark:bg-gray-800/20" : ""
                  }`}
                >
                  <td className="px-5 py-3">
                    <div className="flex items-center gap-3">
                      <TeamLogo team={team.name} />
                      <Link href={teamHref("nfl", team.name)} className={`text-sm font-semibold hover:underline ${isFirst ? "text-gray-900 dark:text-white" : "text-gray-700 dark:text-gray-300"}`}>
                        {team.name}
                      </Link>
                    </div>
                  </td>
                  <td className="px-3 py-3 text-center">
                    <span className={`text-sm font-bold ${isFirst ? "text-gray-900 dark:text-white" : "text-gray-700 dark:text-gray-300"}`}>{team.w}</span>
                  </td>
                  <td className="px-3 py-3 text-center"><span className="text-sm text-gray-500 dark:text-gray-400">{team.l}</span></td>
                  <td className="px-3 py-3 text-center"><span className="text-sm text-gray-500 dark:text-gray-400">{team.t}</span></td>
                  <td className="px-3 py-3 text-center">
                    <span className={`text-sm font-medium ${isFirst ? "text-blue-600 dark:text-blue-400" : "text-gray-600 dark:text-gray-400"}`}>{team.pct}</span>
                  </td>
                  <td className="px-3 py-3 text-center"><span className="text-sm text-gray-500 dark:text-gray-400">{team.pf}</span></td>
                  <td className="px-3 py-3 text-center"><span className="text-sm text-gray-500 dark:text-gray-400">{team.pa}</span></td>
                  <td className="px-3 py-3 text-center">
                    <span className={`text-xs font-medium ${
                      team.point_diff > 0 ? "text-green-600 dark:text-green-400"
                      : team.point_diff < 0 ? "text-red-500 dark:text-red-400"
                      : "text-gray-500"
                    }`}>
                      {team.point_diff > 0 ? "+" : ""}{team.point_diff}
                    </span>
                  </td>
                  <td className="px-3 py-3 text-center">
                    <StreakBadge streak={team.streak} />
                  </td>
                  {hasProj && <>
                    <td className="px-2 py-3 text-center border-l border-gray-100 dark:border-gray-800">
                      <span className="text-sm text-gray-700 dark:text-gray-300 tabular-nums">{proj[team.name]?.projected_wins.toFixed(1) ?? "—"}</span>
                    </td>
                    <PctCell v={proj[team.name]?.division_pct} />
                    <PctCell v={proj[team.name]?.playoff_pct} />
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

export default function NFLStandingsPage() {
  const [data,    setData]    = useState<StandingsData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error,   setError]   = useState("");
  const [conf,    setConf]    = useState<"afc" | "nfc">("afc");
  const [proj,    setProj]    = useState<ProjectionsData | null>(null);

  useEffect(() => {
    fetch(`${API}/api/nfl/standings`)
      .then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); })
      .then(d => setData(d))
      .catch(e => setError(`Could not load standings. (${e.message})`))
      .finally(() => setLoading(false));
    // Projections are slower (10k season simulations) — load separately, never block the table
    fetch(`${API}/api/nfl/projections`)
      .then(r => (r.ok ? r.json() : null))
      .then(d => setProj(d))
      .catch(() => setProj(null));
  }, []);

  const projMap: Record<string, Projection> = Object.fromEntries((proj?.teams ?? []).map(t => [t.team, t]));

  const divisions = data ? data[conf] : [];

  return (
    <main className="px-4 md:px-6 py-6 md:py-8">

      <div className="mb-6 flex items-end justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Standings</h1>
          <p className="text-gray-500 text-sm mt-1">AFC &amp; NFC standings · NFL 2026 regular season</p>
        </div>

        <div className="flex items-center bg-gray-100 dark:bg-gray-800 rounded-xl p-1 gap-1">
          {(["afc", "nfc"] as const).map(c => (
            <button
              key={c}
              onClick={() => setConf(c)}
              className={`px-5 py-1.5 rounded-lg text-sm font-bold transition-colors ${
                conf === c
                  ? "bg-white dark:bg-gray-700 text-gray-900 dark:text-white shadow-sm"
                  : "text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200"
              }`}
            >
              {c.toUpperCase()}
            </button>
          ))}
        </div>
      </div>

      {error && (
        <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800/40 rounded-xl p-4 text-red-600 dark:text-red-400 text-sm mb-6">
          {error}
        </div>
      )}

      {loading && (
        <div className="bg-white dark:bg-gray-900 border border-gray-100 dark:border-transparent shadow-sm rounded-2xl p-8 text-center text-gray-400 dark:text-gray-500 text-sm">
          Loading standings…
        </div>
      )}

      {!loading && !error && (
        <div className="flex flex-col gap-5">
          {divisions.map(div => (
            <DivisionTable key={div.name} division={div} proj={projMap} />
          ))}
        </div>
      )}

      {!loading && !error && (
        <div className="mt-6 flex flex-wrap gap-4 text-xs text-gray-400 dark:text-gray-500">
          <span>PF = Points For · PA = Points Against · DIFF = Point Differential</span>
          {proj && (
            <span>
              PROJ W / DIV / PLAYOFFS: {proj.simulations.toLocaleString()} simulations of the {proj.games_remaining} remaining games
              using the model&apos;s win probabilities. Ties in the standings are broken at random, not by official NFL tiebreakers.
            </span>
          )}
        </div>
      )}
    </main>
  );
}
