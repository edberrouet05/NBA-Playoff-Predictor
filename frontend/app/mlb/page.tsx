"use client";
import { useEffect, useState } from "react";

const API = "http://localhost:8000";

// ── Types ──────────────────────────────────────────────────────────────────────

interface MLBGame {
  game_id: number;
  status: string;
  game_time_utc: string;
  venue: string;
  away_team: string;
  home_team: string;
  away_score: number | null;
  home_score: number | null;
  away_win_prob: number;
  home_win_prob: number;
  predicted_winner: string;
  away_pitcher: string;
  home_pitcher: string;
}

// ── Team metadata ──────────────────────────────────────────────────────────────

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

const MLB_COLORS: Record<string, string> = {
  ARI: "#A71930", ATL: "#CE1141", BAL: "#DF4601", BOS: "#BD3039",
  CHC: "#0E3386", CWS: "#27251F", CIN: "#C6011F", CLE: "#E31937",
  COL: "#333366", DET: "#0C2340", HOU: "#002D62", KC:  "#004687",
  LAA: "#BA0021", LAD: "#005A9C", MIA: "#00A3E0", MIL: "#12284B",
  MIN: "#002B5C", NYM: "#002D72", NYY: "#003087", OAK: "#003831",
  PHI: "#E81828", PIT: "#FDB827", SD:  "#2F241D", SF:  "#FD5A1E",
  SEA: "#0C2C56", STL: "#C41E3A", TB:  "#092C5C", TEX: "#003278",
  TOR: "#134A8E", WSH: "#AB0003",
};

const MLB_LOGO_IDS: Record<string, number> = {
  ARI: 109, ATL: 144, BAL: 110, BOS: 111, CHC: 112, CWS: 145,
  CIN: 113, CLE: 114, COL: 115, DET: 116, HOU: 117, KC:  118,
  LAA: 108, LAD: 119, MIA: 146, MIL: 158, MIN: 142, NYM: 121,
  NYY: 147, OAK: 133, PHI: 143, PIT: 134, SD:  135, SF:  137,
  SEA: 136, STL: 138, TB:  139, TEX: 140, TOR: 141, WSH: 120,
};

function getAbbr(t: string)  { return MLB_ABBR[t] ?? t.split(" ").pop()?.slice(0, 3).toUpperCase() ?? "???"; }
function getColor(t: string) { return MLB_COLORS[getAbbr(t)] ?? "#555"; }
function getNick(t: string)  { return t.split(" ").slice(-1)[0]; }

function getLogoUrl(t: string): string {
  const id = MLB_LOGO_IDS[getAbbr(t)];
  return id ? `https://www.mlbstatic.com/team-logos/${id}.svg` : "";
}

function formatGameTime(iso: string): string {
  if (!iso) return "TBD";
  try {
    return new Date(iso).toLocaleTimeString("en-US", {
      hour: "numeric", minute: "2-digit", timeZoneName: "short",
    });
  } catch { return "TBD"; }
}

function formatDate(dateStr: string): string {
  try {
    const [y, m, d] = dateStr.split("-").map(Number);
    return new Date(y, m - 1, d).toLocaleDateString("en-US", {
      weekday: "long", month: "long", day: "numeric",
    });
  } catch { return dateStr; }
}

// ── Team logo ──────────────────────────────────────────────────────────────────

function TeamLogo({ team, size }: { team: string; size: string }) {
  const [err, setErr] = useState(false);
  const url = getLogoUrl(team);
  if (!url || err) {
    return (
      <div
        className={`${size} rounded-full flex-shrink-0 flex items-center justify-center text-white text-[9px] font-bold`}
        style={{ background: getColor(team) }}
      >
        {getAbbr(team).slice(0, 2)}
      </div>
    );
  }
  return (
    <img src={url} alt={team} className={`${size} object-contain flex-shrink-0`} onError={() => setErr(true)} />
  );
}

// ── Game card ──────────────────────────────────────────────────────────────────

function GameCard({ game }: { game: MLBGame }) {
  const isLive   = game.status === "Live" || game.status === "In Progress";
  const isFinal  = game.status === "Final" || game.status === "Game Over";
  const showScore = isLive || isFinal;
  const awayWins  = isFinal && game.away_score !== null && game.home_score !== null && game.away_score > game.home_score;
  const homeWins  = isFinal && game.away_score !== null && game.home_score !== null && game.home_score > game.away_score;

  return (
    <div className="bg-white dark:bg-gray-900 border border-gray-100 dark:border-transparent shadow-sm rounded-2xl overflow-hidden">

      {/* Status row */}
      <div className="px-5 pt-4 flex items-center justify-between">
        <span className="text-xs text-gray-500">
          {isLive || isFinal ? game.status : formatGameTime(game.game_time_utc)}
        </span>
        {isLive && (
          <span className="flex items-center gap-1.5 text-xs font-bold text-red-400">
            <span className="w-1.5 h-1.5 rounded-full bg-red-500 animate-pulse inline-block" />
            Live
          </span>
        )}
        {isFinal && <span className="text-xs text-gray-500 font-medium">Final</span>}
      </div>

      {/* Teams + probabilities */}
      <div className="px-5 pt-4 pb-3 grid grid-cols-[1fr_auto_1fr] items-center gap-4">
        <div className="flex flex-col items-center gap-1.5">
          <TeamLogo team={game.away_team} size="w-12 h-12" />
          <span className="text-gray-900 dark:text-white text-sm font-bold">{getAbbr(game.away_team)}</span>
          <span className={`text-sm font-bold ${game.predicted_winner === game.away_team ? "text-green-600 dark:text-green-400" : "text-gray-500"}`}>
            {game.away_win_prob}%
          </span>
          {showScore && game.away_score !== null && (
            <span className={`text-lg font-bold ${awayWins ? "text-gray-900 dark:text-white" : "text-gray-500"}`}>
              {game.away_score}
            </span>
          )}
        </div>

        <span className="text-gray-300 dark:text-gray-700 font-bold text-sm">VS</span>

        <div className="flex flex-col items-center gap-1.5">
          <TeamLogo team={game.home_team} size="w-12 h-12" />
          <span className="text-gray-900 dark:text-white text-sm font-bold">{getAbbr(game.home_team)}</span>
          <span className={`text-sm font-bold ${game.predicted_winner === game.home_team ? "text-green-600 dark:text-green-400" : "text-gray-500"}`}>
            {game.home_win_prob}%
          </span>
          {showScore && game.home_score !== null && (
            <span className={`text-lg font-bold ${homeWins ? "text-gray-900 dark:text-white" : "text-gray-500"}`}>
              {game.home_score}
            </span>
          )}
        </div>
      </div>

      {/* Probability bar */}
      <div className="mx-5 h-[3px] flex rounded-full overflow-hidden">
        <div className="h-full" style={{ width: `${game.away_win_prob}%`, background: getColor(game.away_team) }} />
        <div className="h-full flex-1" style={{ background: getColor(game.home_team) }} />
      </div>

      {/* Pitcher matchup row */}
      <div className="px-5 pt-2.5 pb-1 flex items-center justify-between gap-2">
        <span className="text-[11px] text-gray-400 truncate max-w-[44%]">{game.away_pitcher}</span>
        <span className="text-[10px] font-bold text-gray-300 dark:text-gray-600 uppercase tracking-widest flex-shrink-0">vs</span>
        <span className="text-[11px] text-gray-400 truncate max-w-[44%] text-right">{game.home_pitcher}</span>
      </div>

      {/* Predicted winner */}
      <div className="px-5 py-3">
        <span className="text-xs text-green-600 dark:text-green-400">Predicted: {game.predicted_winner}</span>
      </div>
    </div>
  );
}

// ── Sidebar: recent predictions log ───────────────────────────────────────────

interface MLBPredEntry {
  game_id: number;
  date: string;
  away_team: string;
  home_team: string;
  predicted_winner: string;
  predicted_prob: number;
  actual_winner: string;
  correct: boolean;
  away_score: number | null;
  home_score: number | null;
  away_win_prob: number;
  home_win_prob: number;
}

function fmtShortDate(d: string): string {
  try {
    const [y, mo, day] = d.split("-").map(Number);
    return new Date(y, mo - 1, day).toLocaleDateString("en-US", { month: "short", day: "numeric" });
  } catch { return d; }
}

function PredictionsLog({ log }: { log: MLBPredEntry[] }) {
  const [expanded, setExpanded] = useState(false);
  const visible = expanded ? log : log.slice(0, 3);

  return (
    <div className="bg-white dark:bg-gray-900 border border-gray-100 dark:border-transparent shadow-sm rounded-2xl p-4">
      <button onClick={() => setExpanded(e => !e)}
        className="w-full flex items-center justify-between mb-3 group">
        <div className="flex items-center gap-2">
          <svg width="15" height="15" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" className="text-gray-400">
            <circle cx="8" cy="8" r="6.5" /><path d="M8 4.5V8l2.5 2" />
          </svg>
          <p className="text-sm font-bold text-gray-900 dark:text-white group-hover:text-red-600 dark:group-hover:text-red-400 transition-colors">
            Recent predictions log
          </p>
        </div>
        <svg width="13" height="13" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
          className={`text-gray-400 transition-transform ${expanded ? "rotate-180" : ""}`}>
          <path d="M4 6l4 4 4-4" />
        </svg>
      </button>

      {log.length === 0 ? (
        <p className="text-xs text-gray-400 text-center py-3">No completed games yet.</p>
      ) : (
        <div className="flex flex-col divide-y divide-gray-100 dark:divide-gray-800">
          {visible.map((e, i) => (
            <div key={i} className="flex items-center justify-between py-2 gap-3">
              <p className="text-xs text-gray-500 truncate">
                {fmtShortDate(e.date)} · {getNick(e.away_team)} vs {getNick(e.home_team)}
              </p>
              <div className="flex items-center gap-2 flex-shrink-0">
                <span className="text-xs text-gray-700 dark:text-gray-300 whitespace-nowrap">
                  {getNick(e.predicted_winner)} {e.predicted_prob}%
                </span>
                <span className={`text-[10px] px-2 py-0.5 rounded-full font-semibold whitespace-nowrap ${
                  e.correct
                    ? "bg-green-100 dark:bg-green-500/20 text-green-700 dark:text-green-400"
                    : "bg-red-100 dark:bg-red-500/20 text-red-700 dark:text-red-400"
                }`}>
                  {e.correct ? "Correct" : "Wrong"}
                </span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Sidebar: top confidence picks ─────────────────────────────────────────────

function ConfidencePicks({ games }: { games: MLBGame[] }) {
  const picks = games
    .map(g => ({
      team: g.predicted_winner,
      opp:  g.predicted_winner === g.away_team ? g.home_team : g.away_team,
      prob: Math.max(g.away_win_prob, g.home_win_prob),
    }))
    .sort((a, b) => b.prob - a.prob)
    .slice(0, 5);

  function conf(p: number) {
    if (p >= 60) return { label: "High", cls: "bg-green-100 dark:bg-green-500/20 text-green-700 dark:text-green-400", val: "text-green-600 dark:text-green-400" };
    if (p >= 54) return { label: "Med",  cls: "bg-yellow-100 dark:bg-yellow-500/20 text-yellow-700 dark:text-yellow-400", val: "text-yellow-600 dark:text-yellow-400" };
    return              { label: "Low",  cls: "bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-400", val: "text-gray-500" };
  }

  return (
    <div className="bg-white dark:bg-gray-900 border border-gray-100 dark:border-transparent shadow-sm rounded-2xl p-4">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <svg width="15" height="15" viewBox="0 0 16 16" fill="currentColor" className="text-gray-400">
            <path d="M8 1.5a.5.5 0 0 1 .448.276l1.715 3.474 3.833.557a.5.5 0 0 1 .277.853l-2.773 2.702.655 3.817a.5.5 0 0 1-.726.527L8 11.175l-3.429 1.531a.5.5 0 0 1-.726-.527l.655-3.817L1.727 5.66a.5.5 0 0 1 .277-.853l3.833-.557L7.552 1.776A.5.5 0 0 1 8 1.5z" />
          </svg>
          <p className="text-sm font-bold text-gray-900 dark:text-white">Top confidence picks</p>
        </div>
      </div>

      {picks.length === 0 ? (
        <p className="text-xs text-gray-400 text-center py-3">No games today.</p>
      ) : (
        <div className="flex flex-col gap-2">
          {picks.map((pick, i) => {
            const c = conf(pick.prob);
            return (
              <div key={i} className="flex items-center justify-between bg-gray-50 dark:bg-gray-800/50 rounded-xl px-3 py-2.5">
                <span className="text-sm text-gray-800 dark:text-gray-200 font-medium">{getNick(pick.team)}</span>
                <span className={`text-sm font-bold ${c.val}`}>{pick.prob}%</span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ── Sidebar: venue & park factors ─────────────────────────────────────────────

function ParkFactorPanel({ games }: { games: MLBGame[] }) {
  if (games.length === 0) return null;

  // Static park factor labels (sourced from model training data)
  const PARK_LABELS: Record<string, { label: string; cls: string }> = {
    COL: { label: "Hitter-friendly", cls: "bg-red-100 dark:bg-red-500/20 text-red-700 dark:text-red-400" },
    CIN: { label: "Hitter-friendly", cls: "bg-orange-100 dark:bg-orange-500/20 text-orange-700 dark:text-orange-400" },
    BOS: { label: "Slight hitter",   cls: "bg-yellow-100 dark:bg-yellow-500/20 text-yellow-700 dark:text-yellow-400" },
    SD:  { label: "Pitcher-friendly",cls: "bg-blue-100 dark:bg-blue-500/20 text-blue-700 dark:text-blue-400" },
    SEA: { label: "Pitcher-friendly",cls: "bg-blue-100 dark:bg-blue-500/20 text-blue-700 dark:text-blue-400" },
    OAK: { label: "Pitcher-friendly",cls: "bg-blue-100 dark:bg-blue-500/20 text-blue-700 dark:text-blue-400" },
  };

  const notable = games
    .map(g => ({ game: g, abbr: getAbbr(g.home_team) }))
    .filter(({ abbr }) => PARK_LABELS[abbr])
    .slice(0, 3);

  if (notable.length === 0) return null;

  return (
    <div className="bg-white dark:bg-gray-900 border border-gray-100 dark:border-transparent shadow-sm rounded-2xl p-4">
      <div className="flex items-center gap-2 mb-3">
        <svg width="15" height="15" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" className="text-gray-400">
          <path d="M2 14 L8 2 L14 14" /><path d="M4 10 h8" />
        </svg>
        <p className="text-sm font-bold text-gray-900 dark:text-white">Park factors</p>
      </div>
      <div className="flex flex-col gap-2">
        {notable.map(({ game, abbr }, i) => {
          const info = PARK_LABELS[abbr]!;
          return (
            <div key={i} className="flex items-center justify-between bg-gray-50 dark:bg-gray-800/50 rounded-xl px-3 py-2">
              <div className="flex items-center gap-2">
                <TeamLogo team={game.home_team} size="w-5 h-5" />
                <span className="text-xs font-medium text-gray-700 dark:text-gray-300">{game.venue || abbr}</span>
              </div>
              <span className={`text-[10px] px-2 py-0.5 rounded-full font-semibold ${info.cls}`}>
                {info.label}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── Page ───────────────────────────────────────────────────────────────────────

export default function MLBPage() {
  const [games,   setGames]   = useState<MLBGame[]>([]);
  const [date,    setDate]    = useState("");
  const [loading, setLoading] = useState(true);
  const [error,   setError]   = useState("");
  const [predLog, setPredLog] = useState<MLBPredEntry[]>([]);

  useEffect(() => {
    const load = () =>
      fetch(`${API}/api/mlb/today`)
        .then(r => {
          if (!r.ok) throw new Error(`HTTP ${r.status}`);
          return r.json();
        })
        .then(d => { setGames(d.games ?? []); setDate(d.date ?? ""); })
        .catch(e => setError(`Could not load MLB games. Is the backend running? (${e.message})`))
        .finally(() => setLoading(false));

    load();
    const id = setInterval(load, 120_000);

    fetch(`${API}/api/mlb/predictions_log?n=10`, { cache: "no-store" })
      .then(r => r.json())
      .then(d => setPredLog(d.log ?? []))
      .catch(() => {});

    return () => clearInterval(id);
  }, []);

  return (
    <main className="px-6 py-8">
      <div className="grid grid-cols-[1fr_340px] gap-6">

        {/* ── Left: game cards ── */}
        <div>
          <div className="mb-6">
            <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Today&apos;s Games</h1>
            <p className="text-gray-500 text-sm mt-1">
              Win probability · pitcher matchups · MLB 2026 regular season
            </p>
          </div>

          {error && (
            <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800/40 rounded-xl p-4 text-red-600 dark:text-red-400 text-sm mb-6">
              {error}
            </div>
          )}

          {!error && loading && (
            <div className="bg-white dark:bg-gray-900 border border-gray-100 dark:border-transparent shadow-sm rounded-2xl p-8 text-center text-gray-400 dark:text-gray-500 text-sm">
              Loading today&apos;s games…
            </div>
          )}

          {!error && !loading && games.length === 0 && (
            <div className="bg-white dark:bg-gray-900 border border-gray-100 dark:border-transparent shadow-sm rounded-2xl p-8 text-center text-gray-400 dark:text-gray-500 text-sm">
              No MLB games scheduled for today.
            </div>
          )}

          {games.length > 0 && (
            <div>
              <p className="text-xs text-gray-400 font-semibold mb-3 uppercase tracking-widest">
                {formatDate(date)}
              </p>
              <div className="flex flex-col gap-4">
                {games.map(g => <GameCard key={g.game_id} game={g} />)}
              </div>
            </div>
          )}
        </div>

        {/* ── Right: insight panels ── */}
        <div className="flex flex-col gap-4">
          <PredictionsLog log={predLog} />
          <ConfidencePicks games={games} />
          <ParkFactorPanel games={games} />
        </div>

      </div>
    </main>
  );
}
