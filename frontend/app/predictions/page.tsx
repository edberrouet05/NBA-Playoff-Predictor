"use client";
import { useEffect, useState } from "react";
import Link from "next/link";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

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

const ROUND_ORDER = ["Regular Season", "First Round", "Conference Semifinals", "Conference Finals", "NBA Finals"];

function getAbbr(t: string) {
  return TEAM_ABBR[t] ?? t.split(" ").pop()?.substring(0, 3).toUpperCase() ?? "???";
}
function getNick(t: string) { return t.split(" ").pop() ?? t; }
function getLogoUrl(t: string): string {
  const id = TEAM_IDS[getAbbr(t)];
  return id ? `https://cdn.nba.com/logos/nba/${id}/global/L/logo.svg` : "";
}

function gradientColor(pct: number): string {
  const hue = Math.max(0, Math.min(120, ((pct - 40) / 35) * 120));
  return `hsl(${Math.round(hue)}, 80%, 42%)`;
}
function gradientBarColor(pct: number): string {
  const hue = Math.max(0, Math.min(120, ((pct - 40) / 35) * 120));
  return `hsl(${Math.round(hue)}, 75%, 50%)`;
}

function fmtDate(d: string): string {
  try {
    const [y, mo, day] = d.split("-").map(Number);
    return new Date(y, mo - 1, day).toLocaleDateString("en-US", { month: "short", day: "numeric" });
  } catch { return d; }
}

function toLocalDateStr(d: string): string {
  return d.slice(0, 10);
}

function TeamLogo({ team }: { team: string }) {
  const [err, setErr] = useState(false);
  const url = getLogoUrl(team);
  if (!url || err) {
    return (
      <span className="w-5 h-5 flex-shrink-0 text-[9px] font-bold text-gray-400 flex items-center justify-center">
        {getAbbr(team).slice(0, 2)}
      </span>
    );
  }
  return <img src={url} alt={team} className="w-5 h-5 object-contain flex-shrink-0" onError={() => setErr(true)} />;
}

type Filter = "today" | "yesterday" | "week" | "all";

export default function NBAPredictionsPage() {
  const [log,     setLog]     = useState<PredictionEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter,  setFilter]  = useState<Filter>("all");

  useEffect(() => {
    fetch(`${API}/api/predictions_log?n=500`, { cache: "no-store" })
      .then(r => r.json())
      .then(d => setLog(d.log ?? []))
      .finally(() => setLoading(false));
  }, []);

  const todayStr     = new Date().toLocaleDateString("en-CA");
  const yesterdayStr = new Date(Date.now() - 86400000).toLocaleDateString("en-CA");
  const weekAgoStr   = new Date(Date.now() - 7 * 86400000).toLocaleDateString("en-CA");

  const visible = filter === "all"
    ? log
    : filter === "today"
    ? log.filter(e => toLocalDateStr(e.date) === todayStr)
    : filter === "yesterday"
    ? log.filter(e => toLocalDateStr(e.date) === yesterdayStr)
    : log.filter(e => toLocalDateStr(e.date) >= weekAgoStr);

  const correct  = visible.filter(e => e.correct).length;
  const accuracy = visible.length > 0 ? Math.round((correct / visible.length) * 100) : 0;

  const roundMap: Record<string, { correct: number; total: number }> = {};
  for (const e of log) {
    const r = e.round ?? "Playoffs";
    if (!roundMap[r]) roundMap[r] = { correct: 0, total: 0 };
    roundMap[r].total++;
    if (e.correct) roundMap[r].correct++;
  }
  const rounds = ROUND_ORDER.filter(r => roundMap[r]);


  return (
    <main className="px-4 md:px-6 py-6 md:py-8">

      <div className="mb-6 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
        <div className="flex items-center gap-3">
          <Link href="/"
            className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 transition-colors">
            <svg width="18" height="18" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
              <path d="M10 12L6 8l4-4" />
            </svg>
          </Link>
          <div>
            <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Predictions log</h1>
            <p className="text-sm text-gray-500 mt-0.5">All completed playoff games · NBA 2025–26</p>
          </div>
        </div>

        <div className="flex items-center gap-1 bg-gray-100 dark:bg-gray-800 rounded-xl p-1 self-start sm:self-auto">
          {(["today", "yesterday", "week", "all"] as Filter[]).map(f => (
            <button key={f} onClick={() => setFilter(f)}
              className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-colors ${
                filter === f
                  ? "bg-white dark:bg-gray-700 text-gray-900 dark:text-white shadow-sm"
                  : "text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200"
              }`}>
              {f === "all" ? "All" : f === "week" ? "Week" : f.charAt(0).toUpperCase() + f.slice(1)}
            </button>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-[1fr_300px] gap-6">

        <div className="bg-white dark:bg-gray-900 border border-gray-100 dark:border-transparent shadow-sm rounded-2xl overflow-hidden min-h-[300px] flex flex-col">
          {loading ? (
            <div className="flex-1 flex items-center justify-center text-gray-400 text-sm">Loading…</div>
          ) : visible.length === 0 ? (
            <div className="flex-1 flex items-center justify-center text-gray-400 text-sm">
              {filter === "today" ? "No completed games today."
                : filter === "yesterday" ? "No completed games yesterday."
                : filter === "week" ? "No completed games this week."
                : "No completed games yet this season."}
            </div>
          ) : (
            <div className="divide-y divide-gray-100 dark:divide-gray-800">
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
                    className="flex items-center gap-4 px-5 py-3.5 hover:bg-gray-50 dark:hover:bg-gray-800/50 transition-colors">

                    <span className="text-xs text-gray-400 w-14 flex-shrink-0">{fmtDate(e.date)}</span>

                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-1.5">
                        <TeamLogo team={e.away_team} />
                        <span className="text-sm font-medium text-gray-900 dark:text-white">{getAbbr(e.away_team)}</span>
                        <span className="text-xs text-gray-400 mx-0.5">@</span>
                        <TeamLogo team={e.home_team} />
                        <span className="text-sm font-medium text-gray-900 dark:text-white">{getAbbr(e.home_team)}</span>
                      </div>
                      {e.away_score !== null && e.home_score !== null && (
                        <p className="text-xs text-gray-400 mt-0.5 ml-0.5">{e.away_score} – {e.home_score}</p>
                      )}
                    </div>

                    <div className="text-right flex-shrink-0">
                      <p className="text-xs text-gray-700 dark:text-gray-300">
                        {getNick(e.predicted_winner)}{" "}
                        <span className="text-gray-400">{e.predicted_prob}%</span>
                      </p>
                      <p className="text-[10px] text-gray-400 mt-0.5">{e.round ?? "Playoffs"}</p>
                    </div>

                    <div className={`w-6 h-6 rounded-full flex items-center justify-center flex-shrink-0 ${
                      e.correct ? "bg-green-100 dark:bg-green-500/20" : "bg-red-100 dark:bg-red-500/20"
                    }`}>
                      {e.correct ? (
                        <svg width="10" height="10" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-green-600 dark:text-green-400">
                          <path d="M2 6l3 3 5-5" />
                        </svg>
                      ) : (
                        <svg width="8" height="8" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" className="text-red-500 dark:text-red-400">
                          <path d="M2 2l8 8M10 2l-8 8" />
                        </svg>
                      )}
                    </div>

                  </Link>
                );
              })}
            </div>
          )}
        </div>

        <div className="flex flex-col gap-4">
          {!loading && (
            <>
              <div className="bg-white dark:bg-gray-900 border border-gray-100 dark:border-transparent shadow-sm rounded-2xl p-5">
                <p className="text-xs text-gray-400 font-semibold uppercase tracking-widest mb-4">Season summary</p>
                <div className="flex flex-col gap-3">
                  <div className="flex justify-between items-center">
                    <span className="text-xs text-gray-500">Games predicted</span>
                    <span className="text-sm font-bold text-gray-900 dark:text-white">{visible.length}</span>
                  </div>
                  <div className="flex justify-between items-center">
                    <span className="text-xs text-gray-500">Correct</span>
                    <span className="text-sm font-bold text-green-600 dark:text-green-400">{correct}</span>
                  </div>
                  <div className="flex justify-between items-center">
                    <span className="text-xs text-gray-500">Accuracy</span>
                    <span className="text-sm font-bold" style={{ color: gradientColor(accuracy) }}>{accuracy}%</span>
                  </div>
                  {visible.length > 0 && (
                    <div className="mt-1 h-2 bg-gray-100 dark:bg-gray-800 rounded-full overflow-hidden">
                      <div className="h-full rounded-full" style={{ width: `${accuracy}%`, background: gradientBarColor(accuracy) }} />
                    </div>
                  )}
                </div>
              </div>

              {rounds.length > 0 && (
                <div className="bg-white dark:bg-gray-900 border border-gray-100 dark:border-transparent shadow-sm rounded-2xl p-5">
                  <p className="text-xs text-gray-400 font-semibold uppercase tracking-widest mb-4">By round</p>
                  <div className="flex flex-col gap-3">
                    {rounds.map(r => {
                      const { correct: rc, total: rt } = roundMap[r];
                      const pct = Math.round((rc / rt) * 100);
                      return (
                        <div key={r}>
                          <div className="flex justify-between items-center mb-1">
                            <span className="text-xs text-gray-600 dark:text-gray-400 font-medium">{r}</span>
                            <span className="text-xs font-bold" style={{ color: gradientColor(pct) }}>{pct}% <span className="text-gray-400 font-normal">{rc}/{rt}</span></span>
                          </div>
                          <div className="h-1.5 bg-gray-100 dark:bg-gray-800 rounded-full overflow-hidden">
                            <div className="h-full rounded-full" style={{ width: `${pct}%`, background: gradientBarColor(pct) }} />
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}
            </>
          )}
        </div>

      </div>
    </main>
  );
}
