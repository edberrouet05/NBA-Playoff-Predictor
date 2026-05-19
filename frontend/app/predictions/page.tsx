"use client";
import { useEffect, useState } from "react";
import Link from "next/link";

const API = "http://localhost:8000";

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
  round: string;
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

const ROUND_ORDER = ["First Round", "Conference Semifinals", "Conference Finals", "NBA Finals"];

function getNick(t: string) { return t.split(" ").pop() ?? t; }
function getAbbr(t: string) { return TEAM_ABBR[t] ?? t.split(" ").pop()?.substring(0, 3).toUpperCase() ?? "???"; }

function fmtDate(d: string): string {
  const [y, mo, day] = d.split("-").map(Number);
  return new Date(y, mo - 1, day).toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

type Filter = 5 | 10 | "all";

export default function PredictionsPage() {
  const [log, setLog]         = useState<PredictionEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter]   = useState<Filter>("all");

  useEffect(() => {
    fetch(`${API}/api/predictions_log?n=500`, { cache: "no-store" })
      .then(r => r.json())
      .then(d => setLog(d.log ?? []))
      .finally(() => setLoading(false));
  }, []);

  const visible  = filter === "all" ? log : log.slice(0, filter);
  const correct  = visible.filter(e => e.correct).length;
  const accuracy = visible.length > 0 ? Math.round((correct / visible.length) * 100) : 0;

  // Accuracy by round (always computed from full log)
  const roundMap: Record<string, { correct: number; total: number }> = {};
  for (const e of log) {
    const r = e.round ?? "Playoffs";
    if (!roundMap[r]) roundMap[r] = { correct: 0, total: 0 };
    roundMap[r].total++;
    if (e.correct) roundMap[r].correct++;
  }
  const rounds = ROUND_ORDER.filter(r => roundMap[r]);

  return (
    <main className="px-6 py-8 max-w-3xl mx-auto">
      {/* Header */}
      <div className="mb-6 flex items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <Link href="/" className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 transition-colors">
            <svg width="18" height="18" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
              <path d="M10 12L6 8l4-4" />
            </svg>
          </Link>
          <div>
            <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Predictions log</h1>
            <p className="text-sm text-gray-500 mt-0.5">All completed playoff games this season</p>
          </div>
        </div>
        <div className="flex items-center gap-1 bg-gray-100 dark:bg-gray-800 rounded-xl p-1">
          {([5, 10, "all"] as Filter[]).map(f => (
            <button key={String(f)} onClick={() => setFilter(f)}
              className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-colors ${
                filter === f
                  ? "bg-white dark:bg-gray-700 text-gray-900 dark:text-white shadow-sm"
                  : "text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200"
              }`}>
              {f === "all" ? "All" : `Last ${f}`}
            </button>
          ))}
        </div>
      </div>

      {/* Overall stats */}
      {!loading && visible.length > 0 && (
        <div className="grid grid-cols-3 gap-3 mb-4">
          <StatCard label="Games predicted" value={String(visible.length)} />
          <StatCard label="Correct" value={String(correct)} color="text-green-600 dark:text-green-400" />
          <StatCard label="Accuracy" value={`${accuracy}%`}
            color={accuracy >= 60 ? "text-green-600 dark:text-green-400" : "text-yellow-600 dark:text-yellow-400"} />
        </div>
      )}

      {/* Accuracy by round */}
      {!loading && rounds.length > 0 && (
        <div className="bg-white dark:bg-gray-900 border border-gray-100 dark:border-transparent shadow-sm rounded-2xl px-5 py-4 mb-6">
          <p className="text-sm font-bold text-gray-900 dark:text-white mb-3">Accuracy by round</p>
          <div className="flex flex-col gap-2.5">
            {rounds.map(r => {
              const { correct: rc, total: rt } = roundMap[r];
              const pct = Math.round((rc / rt) * 100);
              return (
                <div key={r} className="flex items-center gap-3">
                  <span className="text-xs text-gray-500 w-44 flex-shrink-0">{r}</span>
                  <div className="flex-1 h-2 bg-gray-100 dark:bg-gray-800 rounded-full overflow-hidden">
                    <div className={`h-full rounded-full ${pct >= 60 ? "bg-green-500" : pct >= 50 ? "bg-yellow-400" : "bg-red-400"}`}
                      style={{ width: `${pct}%` }} />
                  </div>
                  <span className={`text-xs font-bold w-10 text-right flex-shrink-0 ${
                    pct >= 60 ? "text-green-600 dark:text-green-400" : pct >= 50 ? "text-yellow-600 dark:text-yellow-400" : "text-red-500"
                  }`}>{pct}%</span>
                  <span className="text-xs text-gray-400 w-12 flex-shrink-0">{rc}/{rt}</span>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Game list */}
      <div className="bg-white dark:bg-gray-900 border border-gray-100 dark:border-transparent shadow-sm rounded-2xl overflow-hidden">
        {loading ? (
          <div className="p-8 text-center text-gray-400 text-sm">Loading…</div>
        ) : visible.length === 0 ? (
          <div className="p-8 text-center text-gray-400 text-sm">No completed games yet this season.</div>
        ) : (
          <div className="divide-y divide-gray-100 dark:divide-gray-800">
            {visible.map((e, i) => {
              const params = new URLSearchParams({
                away: e.away_team, home: e.home_team, time: "Final", status: "Final",
                away_prob: String(e.away_win_prob), home_prob: String(e.home_win_prob),
                winner: e.predicted_winner,
                away_score: e.away_score !== null ? String(e.away_score) : "",
                home_score: e.home_score !== null ? String(e.home_score) : "",
              });
              return (
                <Link key={i} href={`/game/${e.game_id}?${params.toString()}`}
                  className="flex items-center gap-4 px-5 py-3.5 hover:bg-gray-50 dark:hover:bg-gray-800/50 transition-colors">
                  <span className="text-xs text-gray-400 w-16 flex-shrink-0">{fmtDate(e.date)}</span>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-gray-900 dark:text-white truncate">
                      {getAbbr(e.away_team)} <span className="text-gray-400 font-normal">@</span> {getAbbr(e.home_team)}
                    </p>
                    {e.away_score !== null && e.home_score !== null && (
                      <p className="text-xs text-gray-500 mt-0.5">{e.away_score} – {e.home_score}</p>
                    )}
                  </div>
                  <div className="text-right flex-shrink-0">
                    <p className="text-xs text-gray-700 dark:text-gray-300">
                      {getNick(e.predicted_winner)} <span className="text-gray-400">{e.predicted_prob}%</span>
                    </p>
                    <p className="text-[10px] text-gray-400 mt-0.5">{e.round ?? "Playoffs"}</p>
                  </div>
                  <span className={`text-[10px] px-2 py-0.5 rounded-full font-semibold flex-shrink-0 ${
                    e.correct
                      ? "bg-green-100 dark:bg-green-500/20 text-green-700 dark:text-green-400"
                      : "bg-red-100 dark:bg-red-500/20 text-red-700 dark:text-red-400"
                  }`}>
                    {e.correct ? "✓" : "✗"}
                  </span>
                </Link>
              );
            })}
          </div>
        )}
      </div>
    </main>
  );
}

function StatCard({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div className="bg-white dark:bg-gray-900 border border-gray-100 dark:border-transparent shadow-sm rounded-xl px-4 py-3">
      <p className="text-xs text-gray-400">{label}</p>
      <p className={`text-xl font-bold mt-0.5 ${color ?? "text-gray-900 dark:text-white"}`}>{value}</p>
    </div>
  );
}
