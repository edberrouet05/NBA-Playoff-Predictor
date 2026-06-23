"use client";
import { use, useEffect, useState } from "react";
import Link from "next/link";
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid,
  ResponsiveContainer, Tooltip, ReferenceLine, LabelList,
} from "recharts";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// ── Types ──────────────────────────────────────────────────────────────────────

interface WinProbPoint { label: string; away_prob: number; home_prob: number; }
interface InningRow    { num: number; away_r: number | null; home_r: number | null; }

interface MLBGameDetail {
  game_id:          number;
  status:           string;
  game_time_utc:    string;
  venue:            string;
  away_team:        string;
  home_team:        string;
  away_score:       number;
  home_score:       number;
  away_hits:        number;
  home_hits:        number;
  away_errors:      number;
  home_errors:      number;
  current_inning:   number;
  inning_state:     string;
  away_pitcher:     string;
  home_pitcher:     string;
  away_win_prob:    number;
  home_win_prob:    number;
  win_prob_history: WinProbPoint[];
  innings:          InningRow[];
  away_stats:       Record<string, number>;
  home_stats:       Record<string, number>;
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

function ordinalSuffix(n: number): string {
  if (n % 10 === 1 && n % 100 !== 11) return `${n}st`;
  if (n % 10 === 2 && n % 100 !== 12) return `${n}nd`;
  if (n % 10 === 3 && n % 100 !== 13) return `${n}rd`;
  return `${n}th`;
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
    <img src={url} alt={team} className={`${size} object-contain flex-shrink-0`}
      onError={() => setErr(true)} />
  );
}

// ── Stats comparison config ────────────────────────────────────────────────────

const MLB_STAT_DEFS = [
  { key: "era",         label: "ERA",      better: -1, fmt: (v: number) => v.toFixed(2) },
  { key: "whip",        label: "WHIP",     better: -1, fmt: (v: number) => v.toFixed(2) },
  { key: "k_per9",      label: "K/9",      better:  1, fmt: (v: number) => v.toFixed(1) },
  { key: "ops",         label: "OPS",      better:  1, fmt: (v: number) => v.toFixed(3) },
  { key: "batting_avg", label: "AVG",      better:  1, fmt: (v: number) => v.toFixed(3) },
  { key: "run_diff",    label: "Run Diff", better:  1, fmt: (v: number) => v >= 0 ? `+${Math.round(v)}` : `${Math.round(v)}` },
];

function barPcts(a: number, b: number, better: number) {
  if (better === 0) return { aPct: 50, bPct: 50 };
  const lo = Math.min(a, b), hi = Math.max(a, b);
  if (hi === lo) return { aPct: 50, bPct: 50 };
  const s = better === 1 ? (a - lo) / (hi - lo) : (hi - a) / (hi - lo);
  return { aPct: 20 + s * 60, bPct: 20 + (1 - s) * 60 };
}

// ── Win probability chart ─────────────────────────────────────────────────────

function WinProbChart({ data, awayTeam, homeTeam }: {
  data: WinProbPoint[]; awayTeam: string; homeTeam: string;
}) {
  const ac        = getColor(awayTeam);
  const hc        = getColor(homeTeam);
  const first     = data[0];
  const last      = data[data.length - 1];
  const preOnly   = data.length === 1;   // game hasn't started yet

  const PLOT_H = 142;
  const aY = 8 + (1 - (last?.away_prob ?? 50) / 100) * PLOT_H;
  const bY = 8 + (1 - (last?.home_prob ?? 50) / 100) * PLOT_H;
  const diff = bY - aY;
  const MIN_GAP = 42;
  let aOff = 0, bOff = 0;
  if (Math.abs(diff) < MIN_GAP) {
    const push = (MIN_GAP - Math.abs(diff)) / 2;
    if (diff >= 0) { aOff = -push; bOff =  push; }
    else           { aOff =  push; bOff = -push; }
  }

  // Render dot only on the last point; for pre-game (single point) make it larger
  const Dot = (color: string) => (props: { cx?: number; cy?: number; index?: number }) => {
    const { cx = 0, cy = 0, index = 0 } = props;
    if (index !== data.length - 1) return <g />;
    return <circle cx={cx} cy={cy} r={preOnly ? 6 : 5} fill={color} />;
  };

  const EndLabel = (team: string, color: string, yOff: number) =>
    (props: { x?: number; y?: number; index?: number; value?: number }) => {
      const { x = 0, y = 0, index = 0, value = 0 } = props;
      if (index !== data.length - 1) return null;
      const adjY = Number(y) + yOff;
      return (
        <g>
          <text x={Number(x) + 10} y={adjY - 5} fill={color} fontSize={9} fontWeight="700" fontFamily="inherit">
            {getAbbr(team)}
          </text>
          <text x={Number(x) + 10} y={adjY + 9} fill={color} fontSize={14} fontWeight="900" fontFamily="inherit">
            {value}%
          </text>
        </g>
      );
    };

  return (
    <div className="bg-white dark:bg-gray-900 border border-gray-100 dark:border-transparent shadow-sm rounded-2xl px-6 pt-5 pb-4">
      <div className="flex items-start justify-between mb-3">
        <div>
          <p className="text-[10px] font-semibold text-gray-500 uppercase tracking-widest">
            {preOnly ? "Win Probability" : "Live Win Probability"}
          </p>
          {preOnly && (
            <p className="text-[10px] text-gray-400 mt-0.5">Pre-game · updates as innings are played</p>
          )}
        </div>
        <div className="flex gap-5">
          <div className="text-right">
            <p className="text-[10px] font-bold" style={{ color: ac }}>{getAbbr(awayTeam)}</p>
            <p className="text-lg font-black leading-none" style={{ color: ac }}>{first?.away_prob}%</p>
          </div>
          <div className="text-right">
            <p className="text-[10px] font-bold" style={{ color: hc }}>{getAbbr(homeTeam)}</p>
            <p className="text-lg font-black leading-none" style={{ color: hc }}>{first?.home_prob}%</p>
          </div>
        </div>
      </div>

      <ResponsiveContainer width="100%" height={150}>
        <LineChart data={data} margin={{ top: 8, right: 70, bottom: 0, left: -8 }}>
          <CartesianGrid strokeDasharray="2 5" stroke="var(--chart-grid)" vertical={false} />
          <ReferenceLine y={50} stroke="var(--chart-grid)" strokeDasharray="3 3" />
          <XAxis
            dataKey="label"
            tick={{ fill: "var(--chart-tick)", fontSize: 10 }}
            axisLine={false} tickLine={false}
            interval={0}
          />
          <YAxis
            domain={[0, 100]}
            ticks={[0, 25, 50, 75, 100]}
            tick={{ fill: "var(--chart-tick)", fontSize: 10 }}
            axisLine={false} tickLine={false}
            tickFormatter={v => `${v}%`}
            width={30}
          />
          <Tooltip
            content={({ active, payload, label }) => {
              if (!active || !payload?.length) return null;
              const away = payload.find(p => p.dataKey === "away_prob");
              const home = payload.find(p => p.dataKey === "home_prob");
              return (
                <div style={{
                  background: "var(--tooltip-bg)", border: "1px solid var(--tooltip-border)",
                  borderRadius: 8, fontSize: 11, color: "var(--tooltip-text)",
                  padding: "6px 10px",
                }}>
                  <p style={{ color: "#6b7280", marginBottom: 4 }}>{label}</p>
                  {[
                    { entry: away, abbr: getAbbr(awayTeam), color: ac },
                    { entry: home, abbr: getAbbr(homeTeam), color: hc },
                  ]
                    .filter(x => x.entry)
                    .sort((a, b) => Number(b.entry!.value) - Number(a.entry!.value))
                    .map(({ entry, abbr, color }) => (
                      <p key={abbr} style={{ color, margin: "2px 0" }}>
                        <span style={{ display: "inline-block", width: 8, height: 8, borderRadius: "50%", background: color, marginRight: 5 }} />
                        {abbr} : {entry!.value}%
                      </p>
                    ))
                  }
                </div>
              );
            }}
          />
          <Line type="monotone" dataKey="away_prob" stroke={ac} strokeWidth={2}
            dot={Dot(ac)} activeDot={{ r: 4 }}>
            {!preOnly && <LabelList dataKey="away_prob" content={EndLabel(awayTeam, ac, aOff) as never} />}
          </Line>
          <Line type="monotone" dataKey="home_prob" stroke={hc} strokeWidth={2}
            dot={Dot(hc)} activeDot={{ r: 4 }}>
            {!preOnly && <LabelList dataKey="home_prob" content={EndLabel(homeTeam, hc, bOff) as never} />}
          </Line>
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

// ── Linescore table ────────────────────────────────────────────────────────────

function Linescore({
  innings, awayTeam, homeTeam,
  awayScore, homeScore, awayHits, homeHits, awayErrors, homeErrors, isFinal,
}: {
  innings: InningRow[]; awayTeam: string; homeTeam: string;
  awayScore: number; homeScore: number;
  awayHits: number; homeHits: number;
  awayErrors: number; homeErrors: number;
  isFinal: boolean;
}) {
  const played = innings.length > 0 ? Math.max(...innings.map(i => i.num)) : 0;
  const cols   = Array.from({ length: Math.max(9, played) }, (_, i) => i + 1);

  const getAwayR = (n: number) => innings.find(i => i.num === n)?.away_r ?? null;
  const getHomeR = (n: number) => innings.find(i => i.num === n)?.home_r ?? null;

  const awayWins = awayScore > homeScore;
  const homeWins = homeScore > awayScore;

  const fmtHomeCell = (n: number) => {
    const r = getHomeR(n);
    if (r !== null) return String(r);
    // Home team's last inning not played: show "x" in final games when home team wins
    if (isFinal && homeWins && n === played) return "x";
    return "";
  };

  const fmtAwayCell = (n: number) => {
    const r = getAwayR(n);
    if (r !== null) return String(r);
    return "";
  };

  return (
    <div className="bg-white dark:bg-gray-900 border border-gray-100 dark:border-transparent shadow-sm rounded-2xl p-5 overflow-x-auto">
      <p className="text-[10px] font-semibold text-gray-500 uppercase tracking-widest mb-4">
        Linescore
      </p>
      <table className="text-xs tabular-nums min-w-full">
        <thead>
          <tr>
            <th className="text-left text-gray-400 font-semibold pb-2 pr-4 min-w-[40px]" />
            {cols.map(n => (
              <th key={n} className="text-center text-gray-400 font-semibold pb-2 w-7 min-w-[28px]">{n}</th>
            ))}
            <th className="text-center text-gray-400 font-semibold pb-2 pl-3 border-l border-gray-200 dark:border-gray-700 min-w-[28px]">R</th>
            <th className="text-center text-gray-400 font-semibold pb-2 min-w-[28px]">H</th>
            <th className="text-center text-gray-400 font-semibold pb-2 min-w-[28px]">E</th>
          </tr>
        </thead>
        <tbody>
          <tr className="border-t border-gray-100 dark:border-gray-800">
            <td className={`pr-4 py-2 font-bold ${awayWins ? "text-gray-900 dark:text-white" : "text-gray-500"}`}>
              {getAbbr(awayTeam)}
            </td>
            {cols.map(n => (
              <td key={n} className="text-center py-2 text-gray-700 dark:text-gray-300">
                {fmtAwayCell(n)}
              </td>
            ))}
            <td className={`text-center py-2 pl-3 font-bold border-l border-gray-200 dark:border-gray-700 ${awayWins ? "text-gray-900 dark:text-white" : "text-gray-500"}`}>
              {awayScore}
            </td>
            <td className="text-center py-2 text-gray-500">{awayHits}</td>
            <td className="text-center py-2 text-gray-500">{awayErrors}</td>
          </tr>
          <tr className="border-t border-gray-100 dark:border-gray-800">
            <td className={`pr-4 py-2 font-bold ${homeWins ? "text-gray-900 dark:text-white" : "text-gray-500"}`}>
              {getAbbr(homeTeam)}
            </td>
            {cols.map(n => (
              <td key={n} className="text-center py-2 text-gray-600 dark:text-gray-400 italic">
                {fmtHomeCell(n)}
              </td>
            ))}
            <td className={`text-center py-2 pl-3 font-bold border-l border-gray-200 dark:border-gray-700 ${homeWins ? "text-gray-900 dark:text-white" : "text-gray-500"}`}>
              {homeScore}
            </td>
            <td className="text-center py-2 text-gray-500">{homeHits}</td>
            <td className="text-center py-2 text-gray-500">{homeErrors}</td>
          </tr>
        </tbody>
      </table>
    </div>
  );
}

// ── Page ───────────────────────────────────────────────────────────────────────

export default function MLBGamePage({
  params,
  searchParams,
}: {
  params: Promise<{ game_id: string }>;
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
}) {
  const { game_id } = use(params);
  const sp          = use(searchParams);

  // Instant data from URL params (shown before API response)
  const awayParam   = (sp.away   as string) ?? "";
  const homeParam   = (sp.home   as string) ?? "";
  const statusParam = (sp.status as string) ?? "";

  const [gameData, setGameData] = useState<MLBGameDetail | null>(null);
  const [loading,  setLoading]  = useState(true);
  const [fetchErr, setFetchErr] = useState(false);

  useEffect(() => {
    let active = true;

    const fetchData = () => {
      fetch(`${API}/api/mlb/game/${game_id}`)
        .then(r => { if (!r.ok) throw new Error(String(r.status)); return r.json(); })
        .then((d: MLBGameDetail) => { if (active) { setGameData(d); setLoading(false); } })
        .catch(() => { if (active) { setFetchErr(true); setLoading(false); } });
    };

    fetchData();
    // Refresh every 30 s (cache serves instantly for Final games)
    const id = setInterval(fetchData, 30_000);
    return () => { active = false; clearInterval(id); };
  }, [game_id]);

  const g       = gameData;
  const away    = g?.away_team  ?? awayParam;
  const home    = g?.home_team  ?? homeParam;
  const status  = g?.status     ?? statusParam;
  const isLive  = status === "Live" || status === "In Progress";
  const isFinal = status.startsWith("Final") || status === "Game Over" || status === "Completed";
  const showScore = isLive || isFinal;
  const awayWins  = isFinal && !!g && g.away_score > g.home_score;
  const homeWins  = isFinal && !!g && g.home_score > g.away_score;
  const lastPoint = g?.win_prob_history?.at(-1);
  const awayProb  = lastPoint?.away_prob ?? g?.away_win_prob ?? 50;
  const homeProb  = lastPoint?.home_prob ?? g?.home_win_prob ?? 50;

  const statusLabel = (() => {
    if (!g) return statusParam || "Scheduled";
    if (isFinal) return "Final";
    if (isLive && g.current_inning) {
      return `${g.inning_state} ${ordinalSuffix(g.current_inning)}`.trim();
    }
    return formatGameTime(g.game_time_utc);
  })();

  // Show chart as soon as we have the Pre point (even before first pitch)
  const hasChart = (g?.win_prob_history?.length ?? 0) >= 1;
  const hasStats = g && Object.keys(g.away_stats ?? {}).length > 0;

  return (
    <main className="px-4 lg:px-8 pt-4 lg:pt-5 pb-8 flex flex-col gap-3">

      {/* Back */}
      <Link href="/mlb"
        className="inline-flex items-center gap-1.5 text-xs text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 transition-colors">
        <svg width="13" height="13" viewBox="0 0 13 13" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
          <path d="M8 2L3 6.5l5 4.5" />
        </svg>
        Games
      </Link>

      {/* ── Hero card ── */}
      <div className="bg-white dark:bg-gray-900 border border-gray-100 dark:border-transparent shadow-sm rounded-2xl overflow-hidden">

        {/* Status bar */}
        <div className="px-4 pt-4 flex items-center justify-between">
          <p className="text-[11px] font-semibold text-gray-500 uppercase tracking-widest">{statusLabel}</p>
          {isLive && (
            <span className="flex items-center gap-1.5 text-xs font-bold text-red-400">
              <span className="w-1.5 h-1.5 rounded-full bg-red-500 animate-pulse inline-block" />
              Live
            </span>
          )}
          {g?.venue && <span className="text-[11px] text-gray-400 hidden sm:block">{g.venue}</span>}
        </div>

        {/* Mobile + tablet: two stacked rows */}
        <div className="lg:hidden px-4 pt-3 pb-0 flex flex-col gap-2">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <TeamLogo team={away} size="w-10 h-10" />
              <div>
                <p className={`font-bold text-base leading-tight ${isFinal && !awayWins ? "text-gray-400 dark:text-gray-600" : "text-gray-900 dark:text-white"}`}>
                  {getNick(away)}
                </p>
                <p className="text-xs text-gray-400 mt-0.5">{awayProb}%</p>
              </div>
            </div>
            {showScore && g ? (
              <p className={`text-3xl font-black ${awayWins ? "text-gray-900 dark:text-white" : "text-gray-400 dark:text-gray-600"}`}>{g.away_score}</p>
            ) : (
              <p className={`text-xl font-black ${awayProb > homeProb ? "text-green-600 dark:text-green-400" : "text-gray-400"}`}>{awayProb}%</p>
            )}
          </div>
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <TeamLogo team={home} size="w-10 h-10" />
              <div>
                <p className={`font-bold text-base leading-tight ${isFinal && !homeWins ? "text-gray-400 dark:text-gray-600" : "text-gray-900 dark:text-white"}`}>
                  {getNick(home)}
                </p>
                <p className="text-xs text-gray-400 mt-0.5">{homeProb}%</p>
              </div>
            </div>
            {showScore && g ? (
              <p className={`text-3xl font-black ${homeWins ? "text-gray-900 dark:text-white" : "text-gray-400 dark:text-gray-600"}`}>{g.home_score}</p>
            ) : (
              <p className={`text-xl font-black ${homeProb > awayProb ? "text-green-600 dark:text-green-400" : "text-gray-400"}`}>{homeProb}%</p>
            )}
          </div>
        </div>

        {/* Desktop (lg+): 3-col grid */}
        <div className="hidden lg:grid px-8 pt-4 pb-3 grid-cols-[1fr_auto_1fr] items-center gap-6">
          <div className="flex items-center gap-4">
            <TeamLogo team={away} size="w-14 h-14" />
            <div>
              <p className={`font-bold text-xl leading-tight ${isFinal && !awayWins ? "text-gray-400 dark:text-gray-600" : "text-gray-900 dark:text-white"}`}>{getNick(away)}</p>
              {showScore && g ? (
                <p className={`text-3xl font-black mt-1 ${awayWins ? "text-gray-900 dark:text-white" : "text-gray-400 dark:text-gray-600"}`}>{g.away_score}</p>
              ) : (
                <p className={`text-base font-bold mt-1 ${awayProb > homeProb ? "text-green-600 dark:text-green-400" : "text-gray-500"}`}>{awayProb}%</p>
              )}
            </div>
          </div>
          <div className="flex flex-col items-center gap-1 px-6">
            <p className="text-[10px] font-semibold text-gray-500 uppercase tracking-widest">Win Prob</p>
            <p className="text-2xl font-black tracking-tight whitespace-nowrap">
              <span style={{ color: awayWins ? "#16a34a" : "#6b7280" }}>{awayProb}%</span>
              <span className="text-gray-300 dark:text-gray-700 mx-2">·</span>
              <span style={{ color: homeWins ? "#16a34a" : "#6b7280" }}>{homeProb}%</span>
            </p>
          </div>
          <div className="flex items-center gap-4 flex-row-reverse">
            <TeamLogo team={home} size="w-14 h-14" />
            <div className="text-right">
              <p className={`font-bold text-xl leading-tight ${isFinal && !homeWins ? "text-gray-400 dark:text-gray-600" : "text-gray-900 dark:text-white"}`}>{getNick(home)}</p>
              {showScore && g ? (
                <p className={`text-3xl font-black mt-1 ${homeWins ? "text-gray-900 dark:text-white" : "text-gray-400 dark:text-gray-600"}`}>{g.home_score}</p>
              ) : (
                <p className={`text-base font-bold mt-1 ${homeProb > awayProb ? "text-green-600 dark:text-green-400" : "text-gray-500"}`}>{homeProb}%</p>
              )}
            </div>
          </div>
        </div>

        {/* Probability bar */}
        <div className="mx-4 lg:mx-8 mt-3 h-[3px] flex rounded-full overflow-hidden">
          <div className="h-full" style={{ width: `${awayProb}%`, background: getColor(away) }} />
          <div className="h-full flex-1" style={{ background: getColor(home) }} />
        </div>

        {/* Pitcher row */}
        <div className="px-4 lg:px-8 pt-2.5 pb-4 flex items-center justify-between gap-2">
          <span className="text-[11px] text-gray-400 truncate max-w-[44%]">{g?.away_pitcher ?? "—"}</span>
          <span className="text-[10px] font-bold text-gray-300 dark:text-gray-600 uppercase tracking-widest flex-shrink-0">vs</span>
          <span className="text-[11px] text-gray-400 truncate max-w-[44%] text-right">{g?.home_pitcher ?? "—"}</span>
        </div>
      </div>

      {/* Loading / error */}
      {loading && (
        <div className="bg-white dark:bg-gray-900 border border-gray-100 dark:border-transparent shadow-sm rounded-2xl p-6 text-center text-xs text-gray-400">
          Loading game data…
        </div>
      )}
      {!loading && fetchErr && (
        <div className="bg-white dark:bg-gray-900 border border-gray-100 dark:border-transparent shadow-sm rounded-2xl p-6 text-center text-xs text-gray-400">
          Could not load game data — make sure the backend is running on port 8000.
        </div>
      )}

      {!loading && !fetchErr && g && (
        <>
          {/* ── Chart + Stats side by side ── */}
          {(hasChart || hasStats) && (
            <div className={`grid gap-3 items-start ${hasChart && hasStats ? "grid-cols-1 lg:grid-cols-[5fr_2fr]" : ""}`}>
              {hasChart && (
                <WinProbChart
                  data={g.win_prob_history}
                  awayTeam={away}
                  homeTeam={home}
                />
              )}
              {hasStats && (
                <div className="bg-white dark:bg-gray-900 border border-gray-100 dark:border-transparent shadow-sm rounded-2xl p-5">
                  <p className="text-[10px] font-semibold text-gray-500 uppercase tracking-widest mb-3">
                    Stats Comparison
                  </p>
                  <div className="flex flex-col gap-3">
                    {MLB_STAT_DEFS.map(({ key, label, better, fmt }) => {
                      const a = g.away_stats[key] ?? 0;
                      const b = g.home_stats[key] ?? 0;
                      const aWins = better !== 0 && (better === 1 ? a > b : a < b);
                      const bWins = better !== 0 && (better === 1 ? b > a : b < a);
                      const { aPct, bPct } = barPcts(a, b, better);
                      return (
                        <div key={key}>
                          <div className="flex items-center mb-1">
                            <span className={`w-12 text-xs font-bold ${aWins ? "text-green-600 dark:text-green-400" : "text-gray-500"}`}>
                              {fmt(a)}
                            </span>
                            <span className="flex-1 text-center text-[10px] text-gray-500 uppercase tracking-wide">
                              {label}
                            </span>
                            <span className={`w-12 text-xs font-bold text-right ${bWins ? "text-green-600 dark:text-green-400" : "text-gray-500"}`}>
                              {fmt(b)}
                            </span>
                          </div>
                          <div className="flex h-[3px] gap-[2px]">
                            <div className="flex-1 bg-gray-100 dark:bg-gray-800 rounded-l-full overflow-hidden flex justify-end">
                              <div className={`h-full rounded-l-full ${aWins ? "bg-green-500" : "bg-gray-300 dark:bg-gray-600"}`}
                                style={{ width: `${aPct}%` }} />
                            </div>
                            <div className="flex-1 bg-gray-100 dark:bg-gray-800 rounded-r-full overflow-hidden">
                              <div className={`h-full rounded-r-full ${bWins ? "bg-green-500" : "bg-gray-300 dark:bg-gray-600"}`}
                                style={{ width: `${bPct}%` }} />
                            </div>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}
            </div>
          )}

          {/* ── Linescore — only shown once the game has started ── */}
          {(isLive || isFinal) && g.innings.length > 0 && (
            <Linescore
              innings={g.innings}
              awayTeam={away}
              homeTeam={home}
              awayScore={g.away_score}
              homeScore={g.home_score}
              awayHits={g.away_hits}
              homeHits={g.home_hits}
              awayErrors={g.away_errors}
              homeErrors={g.home_errors}
              isFinal={isFinal}
            />
          )}
        </>
      )}

    </main>
  );
}
