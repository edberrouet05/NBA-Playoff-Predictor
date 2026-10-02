"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { probClass, ValueBadge, type ValueFields } from "../components/PredictionBits";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// ── Types ──────────────────────────────────────────────────────────────────────

interface NFLGame extends ValueFields {
  game_id: string;
  status: string;
  status_state: string;
  game_time_utc: string;
  venue: string;
  away_team: string;
  home_team: string;
  away_score: number | null;
  home_score: number | null;
  away_win_prob: number;
  home_win_prob: number;
  predicted_winner: string;
  away_odds: number | null;
  home_odds: number | null;
}

interface NFLPredEntry {
  game_id: string;
  date: string;
  week: number;
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

// ── Team metadata ──────────────────────────────────────────────────────────────

export const NFL_ABBR: Record<string, string> = {
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

export const NFL_COLORS: Record<string, string> = {
  ARI: "#a40227", ATL: "#a71930", BAL: "#29126f", BUF: "#00338d",
  CAR: "#0085ca", CHI: "#0b1c3a", CIN: "#fb4f14", CLE: "#472a08",
  DAL: "#002a5c", DEN: "#0a2343", DET: "#0076b6", GB:  "#204e32",
  HOU: "#021018", IND: "#003b75", JAX: "#007487", KC:  "#e31837",
  LV:  "#000000", LAC: "#0080c6", LAR: "#003594", MIA: "#008e97",
  MIN: "#4f2683", NE:  "#002a5c", NO:  "#d3bc8d", NYG: "#003c7f",
  NYJ: "#115740", PHI: "#06424d", PIT: "#000000", SF:  "#aa0000",
  SEA: "#002a5c", TB:  "#bd1c36", TEN: "#4495d2", WSH: "#5a1414",
};

export function getAbbr(t: string) { return NFL_ABBR[t] ?? t.split(" ").pop()?.slice(0, 3).toUpperCase() ?? "???"; }
export function getColor(t: string) { return NFL_COLORS[getAbbr(t)] ?? "#555"; }
export function getNick(t: string) { return t.split(" ").slice(-1)[0]; }
export function getLogoUrl(t: string): string {
  const abbr = getAbbr(t);
  return abbr === "???" ? "" : `https://a.espncdn.com/i/teamlogos/nfl/500/${abbr.toLowerCase()}.png`;
}

export function gameUrl(g: NFLGame): string {
  const p = new URLSearchParams({
    away:       g.away_team,
    home:       g.home_team,
    status:     g.status,
    away_prob:  String(g.away_win_prob),
    home_prob:  String(g.home_win_prob),
    winner:     g.predicted_winner,
    away_score: g.away_score !== null ? String(g.away_score) : "",
    home_score: g.home_score !== null ? String(g.home_score) : "",
  });
  return `/nfl/game/${g.game_id}?${p.toString()}`;
}

function formatGameTime(iso: string): string {
  if (!iso) return "TBD";
  try {
    return new Date(iso).toLocaleString("en-US", {
      hour: "numeric", minute: "2-digit", timeZoneName: "short",
    });
  } catch { return "TBD"; }
}

function formatDayLabel(iso: string): string {
  if (!iso) return "TBD";
  try {
    return new Date(iso).toLocaleDateString("en-US", { weekday: "long", month: "short", day: "numeric" });
  } catch { return "TBD"; }
}

function groupGamesByDay(games: NFLGame[]): { day: string; games: NFLGame[] }[] {
  const groups: { key: string; day: string; games: NFLGame[] }[] = [];
  for (const g of games) {
    const key = g.game_time_utc ? new Date(g.game_time_utc).toDateString() : "TBD";
    let group = groups.find(gr => gr.key === key);
    if (!group) {
      group = { key, day: formatDayLabel(g.game_time_utc), games: [] };
      groups.push(group);
    }
    group.games.push(g);
  }
  return groups;
}

// ── Team logo ──────────────────────────────────────────────────────────────────

export function TeamLogo({ team, size }: { team: string; size: string }) {
  const [err, setErr] = useState(false);
  const url = getLogoUrl(team);
  if (!url || err) {
    return (
      <div className={`${size} rounded-full flex-shrink-0 flex items-center justify-center text-white text-[9px] font-bold`}
        style={{ background: getColor(team) }}>
        {getAbbr(team).slice(0, 2)}
      </div>
    );
  }
  return <img src={url} alt={team} className={`${size} object-contain flex-shrink-0`} onError={() => setErr(true)} />;
}

// ── Game card ──────────────────────────────────────────────────────────────────

function GameCard({ game }: { game: NFLGame }) {
  const isLive  = game.status_state === "in";
  const isFinal = game.status_state === "post";
  const showScore = isLive || isFinal;
  const awayWins = isFinal && game.away_score !== null && game.home_score !== null && game.away_score > game.home_score;
  const homeWins = isFinal && game.away_score !== null && game.home_score !== null && game.home_score > game.away_score;

  return (
    <Link href={gameUrl(game)} className="block group">
      <div className="bg-white dark:bg-gray-900 border border-gray-100 dark:border-transparent shadow-sm rounded-2xl overflow-hidden group-hover:bg-gray-50 dark:group-hover:bg-gray-800 transition-colors">

        <div className="px-5 pt-4 flex items-center justify-between">
          <span className="text-xs text-gray-500">{isFinal ? "Final" : isLive ? game.status : formatGameTime(game.game_time_utc)}</span>
          {isLive && (
            <span className="flex items-center gap-1.5 text-xs font-bold text-red-400">
              <span className="w-1.5 h-1.5 rounded-full bg-red-500 animate-pulse inline-block" />
              Live
            </span>
          )}
        </div>

        <div className="px-5 pt-4 pb-3 grid grid-cols-[1fr_auto_1fr] items-center gap-4">
          <div className="flex flex-col items-center gap-1.5">
            <TeamLogo team={game.away_team} size="w-12 h-12" />
            <span className="text-gray-900 dark:text-white text-sm font-bold">{getAbbr(game.away_team)}</span>
            <span className={`text-sm font-bold ${probClass(game.predicted_winner === game.away_team, homeWins)}`}>
              {game.away_win_prob}%
            </span>
            {game.away_odds && <span className="text-[11px] text-gray-400">x{game.away_odds}</span>}
            {showScore && game.away_score !== null && (
              <span className={`text-lg font-bold ${awayWins ? "text-gray-900 dark:text-white" : "text-gray-500"}`}>{game.away_score}</span>
            )}
          </div>

          <span className="text-gray-300 dark:text-gray-700 font-bold text-sm">@</span>

          <div className="flex flex-col items-center gap-1.5">
            <TeamLogo team={game.home_team} size="w-12 h-12" />
            <span className="text-gray-900 dark:text-white text-sm font-bold">{getAbbr(game.home_team)}</span>
            <span className={`text-sm font-bold ${probClass(game.predicted_winner === game.home_team, awayWins)}`}>
              {game.home_win_prob}%
            </span>
            {game.home_odds && <span className="text-[11px] text-gray-400">x{game.home_odds}</span>}
            {showScore && game.home_score !== null && (
              <span className={`text-lg font-bold ${homeWins ? "text-gray-900 dark:text-white" : "text-gray-500"}`}>{game.home_score}</span>
            )}
          </div>
        </div>

        <div className="mx-5 h-[3px] flex rounded-full overflow-hidden">
          <div className="h-full" style={{ width: `${game.away_win_prob}%`, background: getColor(game.away_team) }} />
          <div className="h-full flex-1" style={{ background: getColor(game.home_team) }} />
        </div>

        {!isFinal && (
          <div className="px-5 py-3 flex items-center justify-between">
            <span className="text-xs text-green-600 dark:text-green-400">Predicted: {game.predicted_winner}</span>
            <ValueBadge game={game} awayAbbr={getAbbr(game.away_team)} homeAbbr={getAbbr(game.home_team)} />
          </div>
        )}
      </div>
    </Link>
  );
}

// ── Sidebar: recent predictions log ───────────────────────────────────────────

function fmtShortDate(d: string): string {
  try {
    const [y, mo, day] = d.split("-").map(Number);
    return new Date(y, mo - 1, day).toLocaleDateString("en-US", { month: "short", day: "numeric" });
  } catch { return d; }
}

function predEntryUrl(e: NFLPredEntry): string {
  const p = new URLSearchParams({
    away:       e.away_team,
    home:       e.home_team,
    status:     "Final",
    away_prob:  String(e.away_win_prob),
    home_prob:  String(e.home_win_prob),
    winner:     e.predicted_winner,
    away_score: e.away_score !== null ? String(e.away_score) : "",
    home_score: e.home_score !== null ? String(e.home_score) : "",
  });
  return `/nfl/game/${e.game_id}?${p.toString()}`;
}

function PredictionsLog({ log, loading }: { log: NFLPredEntry[]; loading: boolean }) {
  const [expanded, setExpanded] = useState(false);
  const visible = log.slice(0, expanded ? 10 : 3);

  return (
    <div className="bg-white dark:bg-gray-900 border border-gray-100 dark:border-transparent shadow-sm rounded-2xl p-4">
      <button onClick={() => setExpanded(e => !e)} className="w-full flex items-center justify-between mb-3 group">
        <div className="flex items-center gap-2">
          <svg width="15" height="15" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" className="text-gray-400">
            <circle cx="8" cy="8" r="6.5" /><path d="M8 4.5V8l2.5 2" />
          </svg>
          <p className="text-sm font-bold text-gray-900 dark:text-white">Recent predictions log</p>
        </div>
        <svg width="13" height="13" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
          className={`text-gray-400 transition-transform ${expanded ? "rotate-180" : ""}`}>
          <path d="M4 6l4 4 4-4" />
        </svg>
      </button>

      {loading && log.length === 0 ? (
        <p className="text-xs text-gray-400 text-center py-3">Loading…</p>
      ) : log.length === 0 ? (
        <p className="text-xs text-gray-400 text-center py-3">No completed games yet this season.</p>
      ) : (
        <>
          <div className="flex flex-col divide-y divide-gray-100 dark:divide-gray-800">
            {visible.map((e, i) => (
              <Link key={i} href={predEntryUrl(e)}
                className="flex items-center justify-between py-2 gap-3 hover:bg-gray-50 dark:hover:bg-gray-800/50 -mx-1 px-1 rounded-lg transition-colors">
                <p className="text-xs text-gray-500 truncate">
                  {fmtShortDate(e.date)} · {getNick(e.away_team)} @ {getNick(e.home_team)}
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
              </Link>
            ))}
          </div>

          <Link href="/nfl/predictions"
            className="mt-3 flex items-center justify-center gap-1 text-xs font-semibold text-gray-500 dark:text-gray-400 hover:text-gray-800 dark:hover:text-gray-200 transition-colors pt-2 border-t border-gray-100 dark:border-gray-800">
            See all predictions
            <svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M6 4l4 4-4 4" />
            </svg>
          </Link>
        </>
      )}
    </div>
  );
}

// ── Sidebar: top confidence picks ─────────────────────────────────────────────

function ConfidencePicks({ games, loading }: { games: NFLGame[]; loading: boolean }) {
  const picks = games
    .filter(g => g.status_state !== "post")
    .map(g => ({ team: g.predicted_winner, prob: Math.max(g.away_win_prob, g.home_win_prob), href: gameUrl(g) }))
    .sort((a, b) => b.prob - a.prob)
    .slice(0, 5);

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

      {loading ? (
        <p className="text-xs text-gray-400 text-center py-3">Loading…</p>
      ) : picks.length === 0 ? (
        <p className="text-xs text-gray-400 text-center py-3">No games in progress this week.</p>
      ) : (
        <div className="flex flex-col gap-2">
          {picks.map((pick, i) => (
            <Link key={i} href={pick.href} className="flex items-center justify-between bg-gray-50 dark:bg-gray-800/50 rounded-xl px-3 py-2.5 hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors">
              <span className="text-sm text-gray-800 dark:text-gray-200 font-medium">{getNick(pick.team)}</span>
              <span className={`text-sm font-bold ${pick.prob >= 65 ? "text-green-600 dark:text-green-400" : pick.prob >= 58 ? "text-yellow-600 dark:text-yellow-400" : "text-gray-500"}`}>
                {pick.prob}%
              </span>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Page ───────────────────────────────────────────────────────────────────────

export default function NFLPage() {
  const [games,   setGames]   = useState<NFLGame[]>([]);
  const [season,  setSeason]  = useState<number | null>(null);
  const [week,    setWeek]    = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [error,   setError]   = useState("");
  const [predLog,    setPredLog]    = useState<NFLPredEntry[]>([]);
  const [logLoading, setLogLoading] = useState(true);

  useEffect(() => {
    fetch(`${API}/api/nfl/week`)
      .then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); })
      .then(d => { setGames(d.games ?? []); setSeason(d.season ?? null); setWeek(d.week ?? null); })
      .catch(e => setError(`Could not load NFL games. Is the backend running? (${e.message})`))
      .finally(() => setLoading(false));

    fetch(`${API}/api/nfl/predictions_log?n=10`, { cache: "no-store" })
      .then(r => r.json())
      .then(d => setPredLog(d.log ?? []))
      .catch(() => {})
      .finally(() => setLogLoading(false));
  }, []);

  const active   = games.filter(g => g.status_state !== "post");
  const finished = games.filter(g => g.status_state === "post");

  return (
    <main className="px-4 md:px-6 pt-4 pb-8">
      <div className="grid grid-cols-1 xl:grid-cols-[1fr_340px] gap-6">

        {/* ── Left: game cards ── */}
        <div>
          <div className="mb-6">
            <h1 className="text-2xl font-bold text-gray-900 dark:text-white">This Week&apos;s Games</h1>
            <p className="text-gray-500 text-sm mt-1">
              Win probability · {season && week ? `${season} season · Week ${week}` : "NFL regular season"}
            </p>
          </div>

          {error && (
            <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800/40 rounded-xl p-4 text-red-600 dark:text-red-400 text-sm mb-6">
              {error}
            </div>
          )}

          {!error && loading && (
            <div className="bg-white dark:bg-gray-900 border border-gray-100 dark:border-transparent shadow-sm rounded-2xl p-8 text-center text-gray-400 dark:text-gray-500 text-sm">
              Loading this week&apos;s games…
            </div>
          )}

          {!error && !loading && games.length === 0 && (
            <div className="bg-white dark:bg-gray-900 border border-gray-100 dark:border-transparent shadow-sm rounded-2xl p-8 text-center text-gray-400 dark:text-gray-500 text-sm">
              No NFL games scheduled this week.
            </div>
          )}

          {active.length > 0 && (
            <div className="flex flex-col gap-6">
              {groupGamesByDay(active).map(group => (
                <div key={group.day}>
                  <p className="text-xs text-gray-400 font-semibold mb-3 uppercase tracking-widest">
                    {group.day}
                  </p>
                  <div className="flex flex-col gap-4">
                    {group.games.map(g => <GameCard key={g.game_id} game={g} />)}
                  </div>
                </div>
              ))}
            </div>
          )}

          {finished.length > 0 && (
            <>
              <p className="text-xs text-gray-400 font-semibold mt-6 mb-3 uppercase tracking-widest">
                Completed · {finished.length} game{finished.length > 1 ? "s" : ""}
              </p>
              <div className="flex flex-col gap-6">
                {groupGamesByDay(finished).map(group => (
                  <div key={group.day}>
                    <p className="text-xs text-gray-400 font-semibold mb-3 uppercase tracking-widest">
                      {group.day}
                    </p>
                    <div className="flex flex-col gap-4">
                      {group.games.map(g => <GameCard key={g.game_id} game={g} />)}
                    </div>
                  </div>
                ))}
              </div>
            </>
          )}
        </div>

        {/* ── Right: insight panels ── */}
        <div className="flex flex-col gap-4">
          <PredictionsLog log={predLog} loading={logLoading} />
          <ConfidencePicks games={games} loading={loading} />
        </div>

      </div>
    </main>
  );
}
