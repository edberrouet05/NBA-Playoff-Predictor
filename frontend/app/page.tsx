"use client";
import { useEffect, useState } from "react";
import Link from "next/link";

const API = "http://localhost:8000";

interface InjuryPlayerMin { name: string; status: string; }

interface TodayGame {
  game_id: string;
  status: string;
  status_text: string;
  away_team: string;
  home_team: string;
  away_score: number | null;
  home_score: number | null;
  away_win_prob: number;
  home_win_prob: number;
  predicted_winner: string;
  away_injury_impact: number;
  home_injury_impact: number;
  away_injury_players: InjuryPlayerMin[];
  home_injury_players: InjuryPlayerMin[];
}

interface PredictionEntry {
  game_id: string;
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

const TEAM_ABBR: Record<string, string> = {
  "Atlanta Hawks": "ATL", "Boston Celtics": "BOS", "Brooklyn Nets": "BKN",
  "Charlotte Hornets": "CHA", "Chicago Bulls": "CHI", "Cleveland Cavaliers": "CLE",
  "Dallas Mavericks": "DAL", "Denver Nuggets": "DEN", "Detroit Pistons": "DET",
  "Golden State Warriors": "GSW", "Houston Rockets": "HOU", "Indiana Pacers": "IND",
  "LA Clippers": "LAC", "Los Angeles Lakers": "LAL", "Memphis Grizzlies": "MEM",
  "Miami Heat": "MIA", "Milwaukee Bucks": "MIL", "Minnesota Timberwolves": "MIN",
  "New Orleans Pelicans": "NOP", "New York Knicks": "NYK", "Oklahoma City Thunder": "OKC",
  "Orlando Magic": "ORL", "Philadelphia 76ers": "PHI", "Phoenix Suns": "PHX",
  "Portland Trail Blazers": "POR", "Sacramento Kings": "SAC", "San Antonio Spurs": "SAS",
  "Toronto Raptors": "TOR", "Utah Jazz": "UTA", "Washington Wizards": "WAS",
};
const TEAM_COLORS: Record<string, string> = {
  ATL: "#E03A3E", BOS: "#007A33", BKN: "#9EA0A2",
  CHA: "#00788C", CHI: "#CE1141", CLE: "#860038",
  DAL: "#00538C", DEN: "#FEC524", DET: "#1D428A",
  GSW: "#FFC72C", HOU: "#CE1141", IND: "#FDBB30",
  LAC: "#C8102E", LAL: "#FDB927", MEM: "#5D76A9",
  MIA: "#F9A01B", MIL: "#00471B", MIN: "#236192",
  NOP: "#C8A956", NYK: "#F58426", OKC: "#007AC1",
  ORL: "#0077C0", PHI: "#006BB6", PHX: "#E56020",
  POR: "#E03A3E", SAC: "#5A2D81", SAS: "#9EA0A2",
  TOR: "#CE1141", UTA: "#F9A01B", WAS: "#E31837",
};
const TEAM_IDS: Record<string, number> = {
  ATL: 1610612737, BOS: 1610612738, BKN: 1610612751,
  CHA: 1610612766, CHI: 1610612741, CLE: 1610612739,
  DAL: 1610612742, DEN: 1610612743, DET: 1610612765,
  GSW: 1610612744, HOU: 1610612745, IND: 1610612754,
  LAC: 1610612746, LAL: 1610612747, MEM: 1610612763,
  MIA: 1610612748, MIL: 1610612749, MIN: 1610612750,
  NOP: 1610612740, NYK: 1610612752, OKC: 1610612760,
  ORL: 1610612753, PHI: 1610612755, PHX: 1610612756,
  POR: 1610612757, SAC: 1610612758, SAS: 1610612759,
  TOR: 1610612761, UTA: 1610612762, WAS: 1610612764,
};

function getAbbr(t: string) { return TEAM_ABBR[t] ?? t.split(" ").pop()?.substring(0, 3).toUpperCase() ?? "???"; }
function getColor(t: string) { return TEAM_COLORS[getAbbr(t)] ?? "#555"; }
function getNick(t: string)  { return t.split(" ").pop() ?? t; }
function getLogoUrl(t: string) {
  const id = TEAM_IDS[getAbbr(t)];
  return id ? `https://cdn.nba.com/logos/nba/${id}/global/L/logo.svg` : "";
}

function formatDate(dateStr: string): string {
  const [y, m, d] = dateStr.split("T")[0].split("-").map(Number);
  return new Date(y, m - 1, d).toLocaleDateString("en-US", {
    weekday: "long", month: "long", day: "numeric",
  });
}

function fmtShortDate(d: string): string {
  const [y, mo, day] = d.split("-").map(Number);
  return new Date(y, mo - 1, day).toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

function gameUrl(g: TodayGame): string {
  const p = new URLSearchParams({
    away:       g.away_team,
    home:       g.home_team,
    time:       g.status_text,
    status:     g.status,
    away_prob:  String(g.away_win_prob),
    home_prob:  String(g.home_win_prob),
    winner:     g.predicted_winner,
    away_score: g.away_score !== null ? String(g.away_score) : "",
    home_score: g.home_score !== null ? String(g.home_score) : "",
  });
  return `/game/${g.game_id}?${p.toString()}`;
}

export default function GamesPage() {
  const [schedule, setSchedule] = useState<{ date: string; games: TodayGame[] }[]>([]);
  const [predLog,  setPredLog]  = useState<PredictionEntry[]>([]);
  const [loading,  setLoading]  = useState(true);
  const [error,    setError]    = useState("");

  useEffect(() => {
    fetch(`${API}/api/schedule?days=1`)
      .then(r => r.json())
      .then(d => setSchedule(d.schedule ?? []))
      .catch(() => setError("Could not load schedule. Make sure the backend is running."))
      .finally(() => setLoading(false));

    fetch(`${API}/api/predictions_log?n=10`, { cache: "no-store" })
      .then(r => r.json())
      .then(d => setPredLog(d.log ?? []))
      .catch(() => {});
  }, []);

  const allGames = schedule.flatMap(d => d.games);

  return (
    <main className="px-6 py-8">
      <div className="grid grid-cols-[1fr_340px] gap-6">

        {/* ── Left: game cards ── */}
        <div>
          <div className="mb-6">
            <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Tonight&apos;s Games</h1>
            <p className="text-gray-500 text-sm mt-1">
              Live win probability · injury-adjusted · click a game for details
            </p>
          </div>

          {error && (
            <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800/40 rounded-xl p-4 text-red-600 dark:text-red-400 text-sm mb-6">
              {error}
            </div>
          )}

          {!error && loading && (
            <div className="bg-white dark:bg-gray-900 border border-gray-100 dark:border-transparent shadow-sm rounded-2xl p-8 text-center text-gray-400 dark:text-gray-500 text-sm">
              Loading tonight&apos;s games…
            </div>
          )}

          {!error && !loading && schedule.length === 0 && (
            <div className="bg-white dark:bg-gray-900 border border-gray-100 dark:border-transparent shadow-sm rounded-2xl p-8 text-center text-gray-400 dark:text-gray-500 text-sm">
              No games scheduled for today.
            </div>
          )}

          {schedule.map(day => (
            <div key={day.date} className="mb-6">
              <p className="text-xs text-gray-400 font-semibold mb-3 uppercase tracking-widest">
                {formatDate(day.date)}
              </p>
              <div className="flex flex-col gap-4">
                {day.games.map(g => <GameCard key={g.game_id} game={g} />)}
              </div>
            </div>
          ))}
        </div>

        {/* ── Right: insight panels ── */}
        <div className="flex flex-col gap-4">
          <PredictionsLog log={predLog} />
          <ConfidencePicks games={allGames} />
          <InjuryImpactPanel games={allGames} />
        </div>

      </div>
    </main>
  );
}

// ── Game card ──────────────────────────────────────────────────────────────────

function GameCard({ game }: { game: TodayGame }) {
  const isLive  = game.status === "Live";
  const isFinal = game.status === "Final";
  const showScore = isLive || isFinal;
  const awayWins = isFinal && game.away_score !== null && game.home_score !== null && game.away_score > game.home_score;
  const homeWins = isFinal && game.away_score !== null && game.home_score !== null && game.home_score > game.away_score;

  return (
    <Link href={gameUrl(game)} className="block group">
      <div className="bg-white dark:bg-gray-900 border border-gray-100 dark:border-transparent shadow-sm rounded-2xl overflow-hidden group-hover:bg-gray-50 dark:group-hover:bg-gray-800 transition-colors">

        <div className="px-5 pt-4 flex items-center justify-between">
          <span className="text-xs text-gray-500">{game.status_text}</span>
          {isLive && (
            <span className="flex items-center gap-1.5 text-xs font-bold text-red-400">
              <span className="w-1.5 h-1.5 rounded-full bg-red-500 animate-pulse inline-block" />
              Live
            </span>
          )}
          {isFinal && <span className="text-xs text-gray-500 font-medium">Final</span>}
        </div>

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

        <div className="mx-5 h-[3px] flex rounded-full overflow-hidden">
          <div className="h-full" style={{ width: `${game.away_win_prob}%`, background: getColor(game.away_team) }} />
          <div className="h-full flex-1" style={{ background: getColor(game.home_team) }} />
        </div>

        <div className="px-5 py-3">
          <span className="text-xs text-green-600 dark:text-green-400">Predicted: {game.predicted_winner}</span>
        </div>
      </div>
    </Link>
  );
}

// ── Team logo with color-circle fallback ──────────────────────────────────────

function TeamLogo({ team, size }: { team: string; size: string }) {
  const [err, setErr] = useState(false);
  const url = getLogoUrl(team);
  if (!url || err) {
    return <div className={`${size} rounded-full flex-shrink-0`} style={{ background: getColor(team) }} />;
  }
  return (
    <img src={url} alt={team} className={`${size} object-contain flex-shrink-0`} onError={() => setErr(true)} />
  );
}

// ── Insight panel: recent predictions log ─────────────────────────────────────

function PredictionsLog({ log }: { log: PredictionEntry[] }) {
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
        <p className="text-xs text-gray-400 text-center py-3">No completed games yet this season.</p>
      ) : (
        <>
        <div className="flex flex-col divide-y divide-gray-100 dark:divide-gray-800">
          {visible.map((e, i) => {
            const params = new URLSearchParams({
              away:       e.away_team,
              home:       e.home_team,
              time:       "Final",
              status:     "Final",
              away_prob:  String(e.away_win_prob),
              home_prob:  String(e.home_win_prob),
              winner:     e.predicted_winner,
              away_score: e.away_score !== null ? String(e.away_score) : "",
              home_score: e.home_score !== null ? String(e.home_score) : "",
            });
            return (
              <Link key={i} href={`/game/${e.game_id}?${params.toString()}`}
                className="flex items-center justify-between py-2 gap-3 hover:bg-gray-50 dark:hover:bg-gray-800/50 rounded-lg px-1 -mx-1 transition-colors">
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
              </Link>
            );
          })}
        </div>
        <Link href="/predictions"
          className="mt-3 flex items-center justify-center gap-1.5 w-full py-2 rounded-xl text-xs font-semibold text-gray-500 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-800/50 hover:text-gray-700 dark:hover:text-gray-200 border border-gray-100 dark:border-gray-800 transition-colors">
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

// ── Insight panel: top confidence picks ───────────────────────────────────────

function ConfidencePicks({ games }: { games: TodayGame[] }) {
  const picks = games
    .map(g => ({ team: g.predicted_winner, prob: Math.max(g.away_win_prob, g.home_win_prob) }))
    .sort((a, b) => b.prob - a.prob)
    .slice(0, 5);

  function conf(prob: number) {
    if (prob >= 60) return { label: "High", cls: "bg-green-100 dark:bg-green-500/20 text-green-700 dark:text-green-400", val: "text-green-600 dark:text-green-400" };
    if (prob >= 54) return { label: "Med",  cls: "bg-yellow-100 dark:bg-yellow-500/20 text-yellow-700 dark:text-yellow-400", val: "text-yellow-600 dark:text-yellow-400" };
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
                <span className="text-sm text-gray-800 dark:text-gray-200 font-medium">{pick.team}</span>
                <span className={`text-sm font-bold ${c.val}`}>{pick.prob}%</span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ── Insight panel: injury impact ──────────────────────────────────────────────

function InjuryImpactPanel({ games }: { games: TodayGame[] }) {
  const entries: { team: string; players: InjuryPlayerMin[]; impact: number }[] = [];
  for (const g of games) {
    if (g.away_injury_players.length > 0)
      entries.push({ team: g.away_team, players: g.away_injury_players, impact: g.away_injury_impact });
    if (g.home_injury_players.length > 0)
      entries.push({ team: g.home_team, players: g.home_injury_players, impact: g.home_injury_impact });
  }
  if (entries.length === 0) return null;

  function playerLabel(p: InjuryPlayerMin) {
    const last = p.name.split(" ").pop() ?? p.name;
    const tag  = p.status === "Out" ? "Out" : p.status === "Day-To-Day" ? "GTD" : p.status.slice(0, 3);
    return `${last} ${tag}`;
  }

  return (
    <div className="bg-white dark:bg-gray-900 border border-gray-100 dark:border-transparent shadow-sm rounded-2xl p-4">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <svg width="15" height="15" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" className="text-gray-400">
            <circle cx="8" cy="4" r="2.5" /><path d="M3 14c0-3 2-5 5-5s5 2 5 5" />
          </svg>
          <p className="text-sm font-bold text-gray-900 dark:text-white">Injury impact</p>
        </div>
      </div>

      <div className="flex flex-col gap-2">
        {entries.map((item, i) => (
          <div key={i} className="bg-gray-50 dark:bg-gray-800/50 rounded-xl px-3 py-2">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <p className="text-sm font-bold text-gray-900 dark:text-white">{item.team}</p>
                <p className="text-[11px] text-gray-500 mt-0.5 truncate">
                  {item.players.slice(0, 3).map(playerLabel).join(" · ")}
                </p>
              </div>
              {item.impact !== 0 && (
                <div className="text-right flex-shrink-0">
                  <p className="text-[10px] text-gray-400">Prob impact</p>
                  <p className={`text-sm font-bold ${item.impact < 0 ? "text-red-600 dark:text-red-400" : "text-green-600 dark:text-green-400"}`}>
                    {item.impact > 0 ? "+" : ""}{item.impact}%
                  </p>
                </div>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
