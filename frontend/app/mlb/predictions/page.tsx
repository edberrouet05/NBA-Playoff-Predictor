"use client";
import { useEffect, useState } from "react";
import Link from "next/link";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// ── Types ──────────────────────────────────────────────────────────────────────

interface MLBPredEntry {
  game_id:          number;
  date:             string;
  month:            string;
  away_team:        string;
  home_team:        string;
  predicted_winner: string;
  predicted_prob:   number;
  actual_winner:    string;
  correct:          boolean;
  away_score:       number | null;
  home_score:       number | null;
  away_win_prob:    number;
  home_win_prob:    number;
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

function getNick(t: string) { return t.split(" ").slice(-1)[0]; }

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

// ── Team logo ──────────────────────────────────────────────────────────────────

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

// ── Page ───────────────────────────────────────────────────────────────────────

type Filter = "today" | "yesterday" | "week" | "all";

const MONTH_ORDER = ["March", "April", "May", "June", "July", "August", "September", "October"];

function toLocalDateStr(utcDate: string): string {
  // "2026-05-29" → compare against local today/yesterday
  return utcDate.slice(0, 10);
}

export default function MLBPredictionsPage() {
  const [log,     setLog]     = useState<MLBPredEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter,  setFilter]  = useState<Filter>("all");

  useEffect(() => {
    fetch(`${API}/api/mlb/predictions_log?n=500`, { cache: "no-store" })
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

  // Accuracy by month (always from full log, not filtered slice)
  const monthMap: Record<string, { correct: number; total: number }> = {};
  for (const e of log) {
    const m = e.month ?? "Unknown";
    if (!monthMap[m]) monthMap[m] = { correct: 0, total: 0 };
    monthMap[m].total++;
    if (e.correct) monthMap[m].correct++;
  }
  const months = MONTH_ORDER.filter(m => monthMap[m]);

  const confTiers = [55, 60, 65].map(min => {
    const subset = log.filter(e => e.predicted_prob >= min);
    const c = subset.filter(e => e.correct).length;
    const pct = subset.length > 0 ? Math.round((c / subset.length) * 100) : null;
    return { label: `${min}%+`, total: subset.length, correct: c, pct };
  });


  return (
    <main className="px-4 md:px-6 py-6 md:py-8">

      {/* Header */}
      <div className="mb-6 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
        <div className="flex items-center gap-3">
          <Link href="/mlb"
            className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 transition-colors">
            <svg width="18" height="18" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
              <path d="M10 12L6 8l4-4" />
            </svg>
          </Link>
          <div>
            <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Predictions log</h1>
            <p className="text-sm text-gray-500 mt-0.5">All completed regular-season games · MLB 2026</p>
          </div>
        </div>

        {/* Filter tabs */}
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

      {/* Two-column layout */}
      <div className="grid grid-cols-1 xl:grid-cols-[1fr_300px] gap-6">

        {/* ── Left: game list ── */}
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
              {visible.map((e, i) => (
                <Link key={i} href={`/mlb/game/${e.game_id}?away=${encodeURIComponent(e.away_team)}&home=${encodeURIComponent(e.home_team)}&status=Final`} className="flex items-center gap-4 px-5 py-3.5 hover:bg-gray-50 dark:hover:bg-gray-800/50 transition-colors">

                  {/* Date */}
                  <span className="text-xs text-gray-400 w-14 flex-shrink-0">{fmtDate(e.date)}</span>

                  {/* Matchup */}
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

                  {/* Prediction */}
                  <div className="text-right flex-shrink-0">
                    <p className="text-xs text-gray-700 dark:text-gray-300">
                      {getNick(e.predicted_winner)}{" "}
                      <span className="text-gray-400">{e.predicted_prob}%</span>
                    </p>
                  </div>

                  {/* Result badge */}
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
              ))}
            </div>
          )}
        </div>

        {/* ── Right: summary sidebar ── */}
        <div className="flex flex-col gap-4">

          {/* Stat cards */}
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

              {/* Accuracy by month */}
              {months.length > 0 && (
                <div className="bg-white dark:bg-gray-900 border border-gray-100 dark:border-transparent shadow-sm rounded-2xl p-5">
                  <p className="text-xs text-gray-400 font-semibold uppercase tracking-widest mb-4">By month</p>
                  <div className="flex flex-col gap-3">
                    {months.map(m => {
                      const { correct: mc, total: mt } = monthMap[m];
                      const pct = Math.round((mc / mt) * 100);
                      return (
                        <div key={m}>
                          <div className="flex justify-between items-center mb-1">
                            <span className="text-xs text-gray-600 dark:text-gray-400 font-medium">{m}</span>
                            <span className="text-xs font-bold" style={{ color: gradientColor(pct) }}>{pct}% <span className="text-gray-400 font-normal">{mc}/{mt}</span></span>
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

              {/* Accuracy by confidence tier */}
              {confTiers.some(t => t.total > 0) && (
                <div className="bg-white dark:bg-gray-900 border border-gray-100 dark:border-transparent shadow-sm rounded-2xl p-5">
                  <p className="text-xs text-gray-400 font-semibold uppercase tracking-widest mb-4">By confidence</p>
                  <div className="flex flex-col gap-3">
                    {confTiers.map(t => (
                      <div key={t.label}>
                        <div className="flex justify-between items-center mb-1">
                          <span className="text-xs text-gray-600 dark:text-gray-400 font-medium">{t.label}</span>
                          {t.pct === null ? (
                            <span className="text-xs text-gray-400">—</span>
                          ) : (
                            <span className="text-xs font-bold" style={{ color: gradientColor(t.pct) }}>{t.pct}% <span className="text-gray-400 font-normal">{t.correct}/{t.total}</span></span>
                          )}
                        </div>
                        {t.pct !== null && (
                          <div className="h-1.5 bg-gray-100 dark:bg-gray-800 rounded-full overflow-hidden">
                            <div className="h-full rounded-full" style={{ width: `${t.pct}%`, background: gradientBarColor(t.pct) }} />
                          </div>
                        )}
                      </div>
                    ))}
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
