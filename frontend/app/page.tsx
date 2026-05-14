"use client";
import { useEffect, useState } from "react";
import Link from "next/link";

const API = "http://localhost:8000";

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

function getAbbr(t: string) { return TEAM_ABBR[t] ?? t.split(" ").pop()?.substring(0, 3).toUpperCase() ?? "???"; }
function getColor(t: string) { return TEAM_COLORS[getAbbr(t)] ?? "#555"; }

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
  const [error, setError]       = useState("");

  useEffect(() => {
    fetch(`${API}/api/schedule?days=1`)
      .then(r => r.json())
      .then(d => setSchedule(d.schedule ?? []))
      .catch(() => setError("Could not load schedule. Make sure the backend is running."));
  }, []);

  return (
    <main className="max-w-2xl mx-auto px-4 py-10">
      <div className="mb-8">
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

      {!error && schedule.length === 0 && (
        <div className="bg-white dark:bg-gray-900 border border-gray-100 dark:border-transparent shadow-sm rounded-2xl p-8 text-center text-gray-400 dark:text-gray-500 text-sm">
          Loading tonight&apos;s games…
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
    </main>
  );
}

function GameCard({ game }: { game: TodayGame }) {
  const isLive  = game.status === "Live";
  const isFinal = game.status === "Final";
  const showScore = isLive || isFinal;
  const awayWins = isFinal && game.away_score !== null && game.home_score !== null && game.away_score > game.home_score;
  const homeWins = isFinal && game.away_score !== null && game.home_score !== null && game.home_score > game.away_score;

  return (
    <Link href={gameUrl(game)} className="block group">
      <div className="bg-white dark:bg-gray-900 border border-gray-100 dark:border-transparent shadow-sm rounded-2xl overflow-hidden group-hover:bg-gray-50 dark:group-hover:bg-gray-800 transition-colors">

        {/* Status row */}
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

        {/* Teams */}
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

        {/* Split probability bar */}
        <div className="mx-5 h-[3px] flex rounded-full overflow-hidden">
          <div className="h-full" style={{ width: `${game.away_win_prob}%`, background: getColor(game.away_team) }} />
          <div className="h-full flex-1" style={{ background: getColor(game.home_team) }} />
        </div>

        {/* Prediction */}
        <div className="px-5 py-3">
          <span className="text-xs text-green-600 dark:text-green-400">Predicted: {game.predicted_winner}</span>
        </div>
      </div>
    </Link>
  );
}

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
