"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { pickMatchupColors } from "../components/teamColors";
import { probClass, ValueBadge, type ValueFields } from "../components/PredictionBits";
import { useWakeHint, WAKE_HINT } from "../components/useWakeHint";
import { nhlAbbr, nhlColor, nhlColorOptions, nhlLogo, nhlNick } from "./nhlTeams";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const LOG_ROWS_OPEN = 10;   // games in the opened "Recent predictions log"

// ── Types (mirror /api/nhl/today and /api/nhl/predictions_log) ────────────────

interface Goalie { name: string; sv: number; status: "probable" | "started" | "last start" }
interface Side { name: string; abbr: string; score: number | null; record: string | null; logo: string | null; color: string; goalie?: Goalie | null }
interface NHLGame extends ValueFields {
  away_odds: number | null; home_odds: number | null;
  game_id: string; start_utc: string; date: string;
  state: "pre" | "in" | "post"; status: string; detail: string; period: number; clock: string;
  venue: string; home: Side; away: Side;
  home_win_prob: number | null; away_win_prob: number | null; predicted_winner: string | null;
  live_home_prob: number | null; live_away_prob: number | null;
}
interface NHLPredEntry {
  game_id: string; date: string; away_team: string; home_team: string;
  predicted_winner: string; predicted_prob: number; actual_winner: string; correct: boolean;
  away_score: number; home_score: number;
}

function formatGameTime(iso: string): string {
  try {
    return new Date(iso).toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit", timeZone: "America/New_York" }) + " ET";
  } catch { return ""; }
}

function formatDate(day: string): string {
  const [y, m, d] = day.split("-").map(Number);
  return new Date(y, m - 1, d).toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric" });
}

function fmtShortDate(d: string): string {
  const [y, mo, day] = d.split("-").map(Number);
  return new Date(y, mo - 1, day).toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

function TeamLogo({ src, team, size }: { src: string | null; team: string; size: string }) {
  // Remember which URL failed, so a new team gets a fresh attempt
  const [failedSrc, setFailedSrc] = useState<string | null>(null);
  const url = src ?? nhlLogo(team);
  if (failedSrc === url) {
    return (
      <div className={`${size} rounded-full flex-shrink-0 flex items-center justify-center text-white text-[9px] font-bold`}
        style={{ background: nhlColor(team) }}>
        {nhlAbbr(team).slice(0, 3)}
      </div>
    );
  }
  // eslint-disable-next-line @next/next/no-img-element
  return <img src={url} alt={team} className={`${size} object-contain flex-shrink-0`} onError={() => setFailedSrc(url)} />;
}

// ── Game card ──────────────────────────────────────────────────────────────────

function GameCard({ game }: { game: NHLGame }) {
  const isLive = game.state === "in";
  const isFinal = game.state === "post";
  const { home, away } = game;
  const homeWins = isFinal && home.score !== null && away.score !== null && home.score > away.score;
  const awayWins = isFinal && home.score !== null && away.score !== null && away.score > home.score;
  // While the game is on, the bar and the numbers show the live probability
  const awayProb = isLive && game.live_away_prob != null ? game.live_away_prob : game.away_win_prob;
  const homeProb = isLive && game.live_home_prob != null ? game.live_home_prob : game.home_win_prob;

  function side(s: Side, prob: number | null, won: boolean, otherWon: boolean, odds: number | null) {
    return (
      <div className="flex flex-col items-center gap-1.5">
        <TeamLogo src={s.logo} team={s.name} size="w-12 h-12" />
        <span className="text-gray-900 dark:text-white text-sm font-bold">{s.abbr}</span>
        {prob != null && (
          <span className={`text-sm font-bold ${probClass(game.predicted_winner === s.name, otherWon)}`}>{prob}%</span>
        )}
        {odds && !isLive && <span className="text-[11px] text-gray-400" title="Bookmaker decimal odds">x{odds}</span>}
        {(isLive || isFinal) && s.score !== null && (
          <span className={`text-lg font-bold ${won || isLive ? "text-gray-900 dark:text-white" : "text-gray-500"}`}>{s.score}</span>
        )}
        {s.record && !isLive && !isFinal && <span className="text-[11px] text-gray-400">{s.record}</span>}
        {s.goalie && (
          <span className="text-[11px] text-gray-500 text-center"
            title={s.goalie.status === "probable" ? "Probable starting goalie" : s.goalie.status === "started" ? "Starting goalie" : "Last starter (no announced starter yet)"}>
            G: {s.goalie.name.split(" ").slice(-1)[0]} <span className="text-gray-400">{s.goalie.sv.toFixed(3).replace(/^0/, "")}</span>
            {s.goalie.status === "last start" && !isFinal && !isLive && <span className="text-gray-400">?</span>}
          </span>
        )}
      </div>
    );
  }

  const [barAway, barHome] = pickMatchupColors(nhlColorOptions(away.name), nhlColorOptions(home.name));
  return (
    <Link href={`/nhl/game/${game.game_id}`} className="block group h-full">
      <div className="bg-white dark:bg-gray-900 border border-gray-100 dark:border-transparent shadow-sm rounded-2xl overflow-hidden h-full flex flex-col group-hover:bg-gray-50 dark:group-hover:bg-gray-800 transition-colors">
        <div className="px-5 pt-4 flex items-center justify-between">
          <span className="text-xs text-gray-500">{isFinal ? game.detail : isLive ? game.detail : formatGameTime(game.start_utc)}</span>
          {isLive && (
            <span className="flex items-center gap-1.5 text-xs font-bold text-red-400">
              <span className="w-1.5 h-1.5 rounded-full bg-red-500 animate-pulse inline-block" />
              Live
            </span>
          )}
        </div>

        <div className="px-5 pt-4 pb-3 grid grid-cols-[1fr_auto_1fr] items-center gap-4">
          {side(away, awayProb, awayWins, homeWins, game.away_odds)}
          <span className="text-gray-300 dark:text-gray-700 font-bold text-sm">@</span>
          {side(home, homeProb, homeWins, awayWins, game.home_odds)}
        </div>

        {awayProb != null && (
          <div className="mx-5 mt-auto h-[3px] flex rounded-full overflow-hidden">
            <div className="h-full" style={{ width: `${awayProb}%`, background: barAway }} />
            <div className="h-full flex-1" style={{ background: barHome }} />
          </div>
        )}

        <div className="px-5 py-3 flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
          {game.predicted_winner && !isFinal ? (
            <span className="text-xs text-green-600 dark:text-green-400">Predicted: {game.predicted_winner}</span>
          ) : game.predicted_winner && isFinal ? (
            <span className={`text-xs ${(homeWins ? home.name : away.name) === game.predicted_winner ? "text-green-600 dark:text-green-400" : "text-red-500"}`}>
              Our pick: {nhlNick(game.predicted_winner)} {(homeWins ? home.name : away.name) === game.predicted_winner ? "✓" : "✗"}
            </span>
          ) : <span />}
          <div className="flex flex-wrap items-center justify-end gap-x-3 gap-y-1">
            {isLive && game.away_win_prob != null && (
              <span className="text-[11px] text-gray-400">Pre-game {game.away_win_prob}% · {game.home_win_prob}%</span>
            )}
            {game.away_win_prob != null && game.home_win_prob != null && (
              <ValueBadge game={{ ...game, away_win_prob: game.away_win_prob, home_win_prob: game.home_win_prob }}
                awayAbbr={away.abbr} homeAbbr={home.abbr} started={isLive || isFinal} />
            )}
          </div>
        </div>
      </div>
    </Link>
  );
}

// ── Sidebar ────────────────────────────────────────────────────────────────────

function PredictionsLog({ log, loading }: { log: NHLPredEntry[]; loading: boolean }) {
  const [expanded, setExpanded] = useState(false);
  const visible = log.slice(0, expanded ? LOG_ROWS_OPEN : 3);

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
        <p className="text-xs text-gray-400 text-center py-3">No completed games yet.</p>
      ) : (
        <>
          <div className="flex flex-col divide-y divide-gray-100 dark:divide-gray-800">
            {visible.map(e => (
              <Link key={e.game_id} href={`/nhl/game/${e.game_id}`}
                className="flex items-center justify-between py-2 gap-3 hover:bg-gray-50 dark:hover:bg-gray-800/50 -mx-1 px-1 rounded-lg transition-colors">
                <p className="text-xs text-gray-500 truncate">
                  {fmtShortDate(e.date)} · {nhlNick(e.away_team)} @ {nhlNick(e.home_team)}
                </p>
                <div className="flex items-center gap-2 flex-shrink-0">
                  <span className="text-xs text-gray-700 dark:text-gray-300 whitespace-nowrap">
                    {nhlNick(e.predicted_winner)} {e.predicted_prob}%
                  </span>
                  <span className={`text-[10px] px-2 py-0.5 rounded-full font-semibold whitespace-nowrap ${
                    e.correct
                      ? "bg-green-100 dark:bg-green-500/20 text-green-700 dark:text-green-400"
                      : "bg-red-100 dark:bg-red-500/20 text-red-700 dark:text-red-400"}`}>
                    {e.correct ? "Correct" : "Wrong"}
                  </span>
                </div>
              </Link>
            ))}
          </div>
          <Link href="/nhl/predictions"
            className="mt-3 flex items-center justify-center gap-1.5 w-full py-2 rounded-xl text-xs font-semibold text-gray-500 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-800/50 hover:text-gray-700 dark:hover:text-gray-200 border border-gray-100 dark:border-gray-800 transition-colors">
            See all predictions
            <svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M6 4l4 4-4 4" /></svg>
          </Link>
        </>
      )}
    </div>
  );
}

function ConfidencePicks({ games, loading }: { games: NHLGame[]; loading: boolean }) {
  const picks = games
    .filter(g => g.state === "pre" && g.predicted_winner && g.home_win_prob != null)
    .map(g => ({ g, team: g.predicted_winner as string, prob: Math.max(g.home_win_prob ?? 0, g.away_win_prob ?? 0) }))
    .sort((a, b) => b.prob - a.prob)
    .slice(0, 5);

  return (
    <div className="bg-white dark:bg-gray-900 border border-gray-100 dark:border-transparent shadow-sm rounded-2xl p-4">
      <div className="flex items-center gap-2 mb-3">
        <svg width="15" height="15" viewBox="0 0 16 16" fill="currentColor" className="text-gray-400">
          <path d="M8 1.5a.5.5 0 0 1 .448.276l1.715 3.474 3.833.557a.5.5 0 0 1 .277.853l-2.773 2.702.655 3.817a.5.5 0 0 1-.726.527L8 11.175l-3.429 1.531a.5.5 0 0 1-.726-.527l.655-3.817L1.727 5.66a.5.5 0 0 1 .277-.853l3.833-.557L7.552 1.776A.5.5 0 0 1 8 1.5z" />
        </svg>
        <p className="text-sm font-bold text-gray-900 dark:text-white">Top confidence picks</p>
      </div>
      {loading ? (
        <p className="text-xs text-gray-400 text-center py-3">Loading…</p>
      ) : picks.length === 0 ? (
        <p className="text-xs text-gray-400 text-center py-3">No upcoming games today.</p>
      ) : (
        <div className="flex flex-col gap-2">
          {picks.map(({ g, team, prob }) => (
            <Link key={g.game_id} href={`/nhl/game/${g.game_id}`}
              className="flex items-center justify-between bg-gray-50 dark:bg-gray-800/50 rounded-xl px-3 py-2.5 hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors">
              <span className="text-sm text-gray-800 dark:text-gray-200 font-medium">{team}</span>
              <span className={`text-sm font-bold ${prob >= 60 ? "text-green-600 dark:text-green-400" : prob >= 54 ? "text-yellow-600 dark:text-yellow-400" : "text-gray-500"}`}>{prob}%</span>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Page ───────────────────────────────────────────────────────────────────────

export default function NHLPage() {
  const [games, setGames] = useState<NHLGame[]>([]);
  const [date, setDate] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [log, setLog] = useState<NHLPredEntry[]>([]);
  const [logLoading, setLogLoading] = useState(true);
  const waking = useWakeHint(loading);
  const anyLive = games.some(g => g.state === "in");

  useEffect(() => {
    fetch(`${API}/api/nhl/today`)
      .then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); })
      .then(d => { setGames(d.games ?? []); setDate(d.date ?? ""); })
      .catch(e => setError(`Could not load NHL games. Is the backend running? (${e.message})`))
      .finally(() => setLoading(false));
    fetch(`${API}/api/nhl/predictions_log?n=30`)
      .then(r => (r.ok ? r.json() : { log: [] }))
      .then(d => setLog(d.log ?? []))
      .catch(() => {})
      .finally(() => setLogLoading(false));
  }, []);

  // Live scores and probabilities refresh every 30 s while a game is on
  useEffect(() => {
    if (!anyLive) return;
    const id = setInterval(() => {
      fetch(`${API}/api/nhl/today`)
        .then(r => (r.ok ? r.json() : null))
        .then(d => { if (d) setGames(d.games ?? []); })
        .catch(() => {});
    }, 30_000);
    return () => clearInterval(id);
  }, [anyLive]);

  const order = (g: NHLGame) => (g.state === "in" ? 0 : g.state === "pre" ? 1 : 2);
  const active = games.filter(g => g.state !== "post").sort((a, b) => order(a) - order(b));
  const finished = games.filter(g => g.state === "post");

  return (
    <main className="px-4 md:px-6 py-6 md:py-8">
      <div className="grid grid-cols-1 xl:grid-cols-[1fr_340px] gap-6">
        <div>
          <div className="mb-6">
            <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Tonight&apos;s Games</h1>
            <p className="text-gray-500 text-sm mt-1">Win probability · live during games · click a game for details</p>
          </div>

          {error && (
            <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800/40 rounded-xl p-4 text-red-600 dark:text-red-400 text-sm mb-6">{error}</div>
          )}
          {!error && loading && (
            <div className="bg-white dark:bg-gray-900 border border-gray-100 dark:border-transparent shadow-sm rounded-2xl p-8 text-center text-gray-400 text-sm">
              Loading…{waking && <p className="mt-1 text-xs">{WAKE_HINT}</p>}
            </div>
          )}
          {!error && !loading && games.length === 0 && (
            <div className="bg-white dark:bg-gray-900 border border-gray-100 dark:border-transparent shadow-sm rounded-2xl p-8 text-center text-gray-400 text-sm">
              No NHL games scheduled for today.
            </div>
          )}

          {games.length > 0 && (
            <>
              <p className="text-xs text-gray-400 font-semibold mb-3 uppercase tracking-widest">{formatDate(date)}</p>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {active.map(g => <GameCard key={g.game_id} game={g} />)}
              </div>
              {finished.length > 0 && (
                <>
                  <p className="text-xs text-gray-400 font-semibold mt-6 mb-3 uppercase tracking-widest">
                    Completed · {finished.length} game{finished.length > 1 ? "s" : ""}
                  </p>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    {finished.map(g => <GameCard key={g.game_id} game={g} />)}
                  </div>
                </>
              )}
            </>
          )}
        </div>

        <div data-sidebar className="flex flex-col gap-4 xl:sticky xl:top-16 xl:self-start xl:max-h-[calc(100vh-5rem)] xl:overflow-y-auto no-scrollbar xl:pb-1">
          <PredictionsLog log={log} loading={logLoading} />
          <ConfidencePicks games={games} loading={loading} />
        </div>
      </div>
    </main>
  );
}
