"use client";
import { useEffect, useState } from "react";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// ── Types ──────────────────────────────────────────────────────────────────────

interface StandingsTeam {
  name:     string;
  w:        number;
  l:        number;
  pct:      string;
  gb:       string;
  streak:   string;
  run_diff: number;
  home:     string;
  away:     string;
  last10:   string;
  era:      number | null;
  ops:      number | null;
}

interface Division {
  name:  string;
  teams: StandingsTeam[];
}

interface StandingsData {
  al: Division[];
  nl: Division[];
}

// ── Team metadata (shared with mlb/page.tsx) ───────────────────────────────────

const MLB_ABBR: Record<string, string> = {
  "Arizona Diamondbacks":  "ARI", "Atlanta Braves":        "ATL",
  "Baltimore Orioles":     "BAL", "Boston Red Sox":        "BOS",
  "Chicago Cubs":          "CHC", "Chicago White Sox":     "CWS",
  "Cincinnati Reds":       "CIN", "Cleveland Guardians":   "CLE",
  "Colorado Rockies":      "COL", "Detroit Tigers":        "DET",
  "Houston Astros":        "HOU", "Kansas City Royals":    "KC",
  "Los Angeles Angels":    "LAA", "Los Angeles Dodgers":   "LAD",
  "Miami Marlins":         "MIA", "Milwaukee Brewers":     "MIL",
  "Minnesota Twins":       "MIN", "New York Mets":         "NYM",
  "New York Yankees":      "NYY", "Oakland Athletics":     "OAK",
  "Athletics":             "OAK", "Philadelphia Phillies": "PHI",
  "Pittsburgh Pirates":    "PIT", "San Diego Padres":      "SD",
  "San Francisco Giants":  "SF",  "Seattle Mariners":      "SEA",
  "St. Louis Cardinals":   "STL", "Tampa Bay Rays":        "TB",
  "Texas Rangers":         "TEX", "Toronto Blue Jays":     "TOR",
  "Washington Nationals":  "WSH",
};

const MLB_LOGO_IDS: Record<string, number> = {
  ARI: 109, ATL: 144, BAL: 110, BOS: 111, CHC: 112, CWS: 145,
  CIN: 113, CLE: 114, COL: 115, DET: 116, HOU: 117, KC:  118,
  LAA: 108, LAD: 119, MIA: 146, MIL: 158, MIN: 142, NYM: 121,
  NYY: 147, OAK: 133, PHI: 143, PIT: 134, SD:  135, SF:  137,
  SEA: 136, STL: 138, TB:  139, TEX: 140, TOR: 141, WSH: 120,
};

function getAbbr(t: string) {
  return MLB_ABBR[t] ?? t.split(" ").pop()?.slice(0, 3).toUpperCase() ?? "???";
}

function getLogoUrl(t: string): string {
  const id = MLB_LOGO_IDS[getAbbr(t)];
  return id ? `https://www.mlbstatic.com/team-logos/${id}.svg` : "";
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

function DivisionTable({ division }: { division: Division }) {
  return (
    <div className="bg-white dark:bg-gray-900 border border-gray-100 dark:border-transparent shadow-sm rounded-2xl overflow-hidden">

      {/* Division header */}
      <div className="px-5 py-3 border-b border-gray-100 dark:border-gray-800">
        <h3 className="text-xs font-bold text-gray-500 dark:text-gray-400 uppercase tracking-widest">
          {division.name}
        </h3>
      </div>

      {/* Table */}
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-100 dark:border-gray-800">
              <th className="px-5 py-2 text-left text-xs font-semibold text-gray-400 dark:text-gray-500 w-full">Team</th>
              <th className="px-3 py-2 text-center text-xs font-semibold text-gray-400 dark:text-gray-500 whitespace-nowrap">W</th>
              <th className="px-3 py-2 text-center text-xs font-semibold text-gray-400 dark:text-gray-500 whitespace-nowrap">L</th>
              <th className="px-3 py-2 text-center text-xs font-semibold text-gray-400 dark:text-gray-500 whitespace-nowrap">PCT</th>
              <th className="px-3 py-2 text-center text-xs font-semibold text-gray-400 dark:text-gray-500 whitespace-nowrap">GB</th>
              <th className="px-3 py-2 text-center text-xs font-semibold text-gray-400 dark:text-gray-500 whitespace-nowrap">L10</th>
              <th className="px-3 py-2 text-center text-xs font-semibold text-gray-400 dark:text-gray-500 whitespace-nowrap">STRK</th>
              <th className="px-3 py-2 text-center text-xs font-semibold text-gray-400 dark:text-gray-500 whitespace-nowrap">ERA</th>
              <th className="px-3 py-2 text-center text-xs font-semibold text-gray-400 dark:text-gray-500 whitespace-nowrap pr-5">OPS</th>
            </tr>
          </thead>
          <tbody>
            {division.teams.map((team, i) => {
              const isFirst    = i === 0;
              const runDiffPos = team.run_diff > 0;
              return (
                <tr
                  key={team.name}
                  className={`border-b last:border-0 border-gray-50 dark:border-gray-800/60 transition-colors hover:bg-gray-50 dark:hover:bg-gray-800/40 ${
                    isFirst ? "bg-gray-50/50 dark:bg-gray-800/20" : ""
                  }`}
                >
                  {/* Team name */}
                  <td className="px-5 py-3">
                    <div className="flex items-center gap-3">
                      <TeamLogo team={team.name} />
                      <div className="flex flex-col leading-tight">
                        <span className={`text-sm font-semibold ${isFirst ? "text-gray-900 dark:text-white" : "text-gray-700 dark:text-gray-300"}`}>
                          {team.name}
                        </span>
                      </div>
                    </div>
                  </td>

                  {/* W */}
                  <td className="px-3 py-3 text-center">
                    <span className={`text-sm font-bold ${isFirst ? "text-gray-900 dark:text-white" : "text-gray-700 dark:text-gray-300"}`}>
                      {team.w}
                    </span>
                  </td>

                  {/* L */}
                  <td className="px-3 py-3 text-center">
                    <span className="text-sm text-gray-500 dark:text-gray-400">{team.l}</span>
                  </td>

                  {/* PCT */}
                  <td className="px-3 py-3 text-center">
                    <span className={`text-sm font-medium ${isFirst ? "text-blue-600 dark:text-blue-400" : "text-gray-600 dark:text-gray-400"}`}>
                      {team.pct}
                    </span>
                  </td>

                  {/* GB */}
                  <td className="px-3 py-3 text-center">
                    <span className="text-sm text-gray-500 dark:text-gray-400">
                      {team.gb === "0.0" || team.gb === "-" ? "—" : team.gb}
                    </span>
                  </td>

                  {/* Last 10 */}
                  <td className="px-3 py-3 text-center">
                    <span className="text-xs font-medium text-gray-600 dark:text-gray-400">{team.last10}</span>
                  </td>

                  {/* Streak */}
                  <td className="px-3 py-3 text-center">
                    <StreakBadge streak={team.streak} />
                  </td>

                  {/* ERA */}
                  <td className="px-3 py-3 text-center">
                    {team.era !== null ? (
                      <span className={`text-xs font-medium ${
                        team.era <= 3.50 ? "text-green-600 dark:text-green-400"
                        : team.era >= 4.50 ? "text-red-500 dark:text-red-400"
                        : "text-gray-600 dark:text-gray-400"
                      }`}>
                        {team.era.toFixed(2)}
                      </span>
                    ) : <span className="text-gray-300 dark:text-gray-700">—</span>}
                  </td>

                  {/* OPS */}
                  <td className="px-3 py-3 text-center pr-5">
                    {team.ops !== null ? (
                      <span className={`text-xs font-medium ${
                        team.ops >= 0.780 ? "text-green-600 dark:text-green-400"
                        : team.ops <= 0.680 ? "text-red-500 dark:text-red-400"
                        : "text-gray-600 dark:text-gray-400"
                      }`}>
                        {team.ops.toFixed(3)}
                      </span>
                    ) : <span className="text-gray-300 dark:text-gray-700">—</span>}
                  </td>
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

export default function MLBStandingsPage() {
  const [data,    setData]    = useState<StandingsData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error,   setError]   = useState("");
  const [league,  setLeague]  = useState<"al" | "nl">("al");

  useEffect(() => {
    fetch(`${API}/api/mlb/standings`)
      .then(r => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then(d => setData(d))
      .catch(e => setError(`Could not load standings. (${e.message})`))
      .finally(() => setLoading(false));
  }, []);

  const divisions = data ? data[league] : [];

  return (
    <main className="px-4 md:px-6 py-6 md:py-8">

      {/* Header */}
      <div className="mb-6 flex items-end justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Standings</h1>
          <p className="text-gray-500 text-sm mt-1">AL &amp; NL standings · MLB 2026 regular season</p>
        </div>

        {/* AL / NL toggle */}
        <div className="flex items-center bg-gray-100 dark:bg-gray-800 rounded-xl p-1 gap-1">
          {(["al", "nl"] as const).map(lg => (
            <button
              key={lg}
              onClick={() => setLeague(lg)}
              className={`px-5 py-1.5 rounded-lg text-sm font-bold transition-colors ${
                league === lg
                  ? "bg-white dark:bg-gray-700 text-gray-900 dark:text-white shadow-sm"
                  : "text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200"
              }`}
            >
              {lg.toUpperCase()}
            </button>
          ))}
        </div>
      </div>

      {/* Error */}
      {error && (
        <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800/40 rounded-xl p-4 text-red-600 dark:text-red-400 text-sm mb-6">
          {error}
        </div>
      )}

      {/* Loading */}
      {loading && (
        <div className="bg-white dark:bg-gray-900 border border-gray-100 dark:border-transparent shadow-sm rounded-2xl p-8 text-center text-gray-400 dark:text-gray-500 text-sm">
          Loading standings…
        </div>
      )}

      {/* Divisions */}
      {!loading && !error && (
        <div className="flex flex-col gap-5">
          {divisions.map(div => (
            <DivisionTable key={div.name} division={div} />
          ))}
        </div>
      )}

      {/* Legend */}
      {!loading && !error && (
        <div className="mt-6 flex flex-wrap gap-4 text-xs text-gray-400 dark:text-gray-500">
          <span><span className="text-green-600 dark:text-green-400 font-semibold">ERA</span> ≤ 3.50 · <span className="text-red-500 dark:text-red-400 font-semibold">ERA</span> ≥ 4.50</span>
          <span><span className="text-green-600 dark:text-green-400 font-semibold">OPS</span> ≥ .780 · <span className="text-red-500 dark:text-red-400 font-semibold">OPS</span> ≤ .680</span>
          <span>ERA &amp; OPS from 2026 season stats</span>
        </div>
      )}
    </main>
  );
}
