"use client";
import { use, useEffect, useState } from "react";
import Link from "next/link";
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid,
  ResponsiveContainer, Tooltip, LabelList,
} from "recharts";

const API = "https://nba-playoff-predictor-u8bj.onrender.com";

interface TeamStats {
  off_rtg: number; def_rtg: number; net_rtg: number; pace: number;
  ts_pct: number; tov_pct: number; oreb_pct: number; srs: number;
  point_diff: number; fg3_rate: number; ftr: number; win_streak: number;
}
interface CompareResult {
  team_a: string; team_b: string;
  team_a_stats: TeamStats; team_b_stats: TeamStats;
}
interface HistoryPoint  { game: string; team_a_prob: number; team_b_prob: number; series: string; }
interface InjuryPlayer { name: string; status: string; pts_per_game: number | null; }
interface InjuryData   { factor: number; players: InjuryPlayer[]; }
type InjuryReport = Record<string, InjuryData>;

const STATS = [
  { key: "net_rtg",  label: "Net Rating",     better:  1, pct: false },
  { key: "off_rtg",  label: "Off Rating",      better:  1, pct: false },
  { key: "def_rtg",  label: "Def Rating",      better: -1, pct: false },
  { key: "ts_pct",   label: "True Shoot %",    better:  1, pct: true  },
  { key: "tov_pct",  label: "Turnover %",      better: -1, pct: true  },
  { key: "srs",      label: "SRS",             better:  1, pct: false },
];

const STATUS_COLOR: Record<string, string> = {
  Out:          "bg-red-100 dark:bg-red-500/25 text-red-600 dark:text-red-400",
  Doubtful:     "bg-orange-100 dark:bg-orange-500/25 text-orange-600 dark:text-orange-400",
  Questionable: "bg-yellow-100 dark:bg-yellow-500/25 text-yellow-600 dark:text-yellow-400",
  "Day-To-Day": "bg-yellow-100 dark:bg-yellow-500/25 text-yellow-600 dark:text-yellow-400",
};

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
function lastName(t: string) { return t.split(" ").pop() ?? t; }
function fmt(v: number, pct: boolean) { return pct ? (v * 100).toFixed(1) + "%" : v.toFixed(1); }

function barPcts(a: number, b: number, better: number) {
  if (better === 0) return { aPct: 50, bPct: 50 };
  const lo = Math.min(a, b), hi = Math.max(a, b);
  if (hi === lo) return { aPct: 50, bPct: 50 };
  const s = better === 1 ? (a - lo) / (hi - lo) : (hi - a) / (hi - lo);
  return { aPct: 20 + s * 60, bPct: 20 + (1 - s) * 60 };
}

export default function GamePage({
  params,
  searchParams,
}: {
  params: Promise<{ game_id: string }>;
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
}) {
  const sp       = use(searchParams);
  const away     = (sp.away     as string) ?? "";
  const home     = (sp.home     as string) ?? "";
  const time     = (sp.time     as string) ?? "";
  const status   = (sp.status   as string) ?? "";
  const winner   = (sp.winner   as string) ?? "";
  const awayProb = parseFloat((sp.away_prob as string) ?? "50");
  const homeProb = parseFloat((sp.home_prob as string) ?? "50");
  const awayScore = sp.away_score ? parseInt(sp.away_score as string) : null;
  const homeScore = sp.home_score ? parseInt(sp.home_score as string) : null;

  const isLive    = status === "Live";
  const isFinal   = status === "Final";
  const showScore = isLive || isFinal;
  const awayWins  = isFinal && awayScore !== null && homeScore !== null && awayScore > homeScore;
  const homeWins  = isFinal && awayScore !== null && homeScore !== null && homeScore > awayScore;

  const [compare,  setCompare]  = useState<CompareResult | null>(null);
  const [injuries, setInjuries] = useState<InjuryReport | null>(null);
  const [history,  setHistory]  = useState<HistoryPoint[]>([]);
  const [loading,  setLoading]  = useState(true);
  const [fetchErr, setFetchErr] = useState(false);

  useEffect(() => {
    if (!away || !home) { setLoading(false); return; }

    const qa = `team_a=${encodeURIComponent(away)}&team_b=${encodeURIComponent(home)}`;

    // ── Primary fetch: compare only (instant from backend cache) ──
    const ctrl  = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), 8000);

    fetch(`${API}/api/compare?${qa}`, { signal: ctrl.signal })
      .then(r => { if (!r.ok) throw new Error(String(r.status)); return r.json(); })
      .then(cmp => setCompare(cmp as CompareResult))
      .catch((err) => {
        if ((err as Error)?.name === "AbortError") return;
        console.error("[GamePage] compare fetch error:", err);
        setFetchErr(true);
      })
      .finally(() => { clearTimeout(timer); setLoading(false); });

    // ── Series history — slow (Monte Carlo + nba_api), fetched independently ──
    const histCtrl  = new AbortController();
    const histTimer = setTimeout(() => histCtrl.abort(), 60000);

    fetch(`${API}/api/series_history?${qa}`, { signal: histCtrl.signal })
      .then(r => { if (!r.ok) throw new Error(String(r.status)); return r.json(); })
      .then(hist => setHistory((hist as { history: HistoryPoint[] }).history ?? []))
      .catch(() => {})
      .finally(() => clearTimeout(histTimer));

    // ── Injuries — fetched independently so ESPN latency doesn't block stats ──
    const injCtrl  = new AbortController();
    const injTimer = setTimeout(() => injCtrl.abort(), 30000);

    fetch(`${API}/api/injuries?${qa}`, { signal: injCtrl.signal })
      .then(r => { if (!r.ok) throw new Error(String(r.status)); return r.json(); })
      .then(inj => setInjuries(inj as InjuryReport))
      .catch(() => {})
      .finally(() => clearTimeout(injTimer));

    return () => {
      ctrl.abort();     clearTimeout(timer);
      histCtrl.abort(); clearTimeout(histTimer);
      injCtrl.abort();  clearTimeout(injTimer);
    };
  }, [away, home]);

  return (
    <main className="px-8 pt-5 pb-4 flex flex-col gap-3">

      {/* Back */}
      <Link href="/" className="inline-flex items-center gap-1.5 text-xs text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 transition-colors">
        <svg width="13" height="13" viewBox="0 0 13 13" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
          <path d="M8 2L3 6.5l5 4.5" />
        </svg>
        Games
      </Link>

      {/* ── Hero card ── */}
      <div className="bg-white dark:bg-gray-900 border border-gray-100 dark:border-transparent shadow-sm rounded-2xl overflow-hidden">
        <div className="px-8 pt-4 flex items-center justify-between">
          <p className="text-[11px] font-semibold text-gray-500 uppercase tracking-widest">{time}</p>
          {isLive && (
            <span className="flex items-center gap-1.5 text-xs font-bold text-red-400">
              <span className="w-1.5 h-1.5 rounded-full bg-red-500 animate-pulse inline-block" />
              Live
            </span>
          )}
        </div>

        <div className="px-8 pt-4 pb-3 grid grid-cols-[1fr_auto_1fr] items-center gap-6">

          {/* Away */}
          <div className="flex items-center gap-4">
            <TeamLogo team={away} size="w-14 h-14" />
            <div>
              <p className="text-gray-900 dark:text-white font-bold text-xl leading-tight">{lastName(away)}</p>
              {showScore && awayScore !== null ? (
                <p className={`text-2xl font-black mt-1 ${awayWins ? "text-gray-900 dark:text-white" : "text-gray-500"}`}>{awayScore}</p>
              ) : (
                <p className={`text-base font-bold mt-1 ${winner === away ? "text-green-600 dark:text-green-400" : "text-gray-500"}`}>{awayProb}%</p>
              )}
            </div>
          </div>

          {/* Center */}
          <div className="flex flex-col items-center gap-1 px-8">
            <p className="text-[10px] font-semibold text-gray-500 uppercase tracking-widest">Win Prob</p>
            <p className="text-2xl font-black tracking-tight">
              <span style={{ color: winner === away ? "#16a34a" : "#6b7280" }}>{awayProb}%</span>
              <span className="text-gray-300 dark:text-gray-700 mx-2">·</span>
              <span style={{ color: winner === home ? "#16a34a" : "#6b7280" }}>{homeProb}%</span>
            </p>
          </div>

          {/* Home */}
          <div className="flex items-center gap-4 flex-row-reverse">
            <TeamLogo team={home} size="w-14 h-14" />
            <div className="text-right">
              <p className="text-gray-900 dark:text-white font-bold text-xl leading-tight">{lastName(home)}</p>
              {showScore && homeScore !== null ? (
                <p className={`text-2xl font-black mt-1 ${homeWins ? "text-gray-900 dark:text-white" : "text-gray-500"}`}>{homeScore}</p>
              ) : (
                <p className={`text-base font-bold mt-1 ${winner === home ? "text-green-600 dark:text-green-400" : "text-gray-500"}`}>{homeProb}%</p>
              )}
            </div>
          </div>
        </div>

        {/* Probability bar */}
        <div className="mx-8 mb-5 h-[3px] flex rounded-full overflow-hidden">
          <div className="h-full" style={{ width: `${awayProb}%`, background: getColor(away) }} />
          <div className="h-full flex-1" style={{ background: getColor(home) }} />
        </div>
      </div>

      {loading && (
        <div className="bg-white dark:bg-gray-900 border border-gray-100 dark:border-transparent shadow-sm rounded-2xl p-5 text-center text-xs text-gray-400 dark:text-gray-600">
          Loading stats…
        </div>
      )}

      {!loading && fetchErr && (
        <div className="bg-white dark:bg-gray-900 border border-gray-100 dark:border-transparent shadow-sm rounded-2xl p-5 text-center text-xs text-gray-400 dark:text-gray-600">
          Could not load stats — make sure the backend is running on port 8000.
        </div>
      )}

      {!loading && !fetchErr && (
        <>
          {/* ── Win Prob chart + Injuries side by side ── */}
          <div className="grid grid-cols-[5fr_2fr] gap-3 items-start">
            {history.length > 0 && (
              <ProbChart data={history} awayTeam={away} homeTeam={home} />
            )}
            {injuries && (
              <div className="bg-white dark:bg-gray-900 border border-gray-100 dark:border-transparent shadow-sm rounded-2xl p-5">
                <p className="text-[10px] font-semibold text-gray-500 uppercase tracking-widest mb-3">
                  Injury Report
                </p>
                <div className="flex flex-col gap-4">
                  <InjuryColumn team={away} data={injuries[away]} />
                  <InjuryColumn team={home} data={injuries[home]} />
                </div>
              </div>
            )}
          </div>

          {/* ── Stats full width ── */}
          {compare && (
            <div className="bg-white dark:bg-gray-900 border border-gray-100 dark:border-transparent shadow-sm rounded-2xl p-5">
              <p className="text-[10px] font-semibold text-gray-500 uppercase tracking-widest mb-3">
                Stats Comparison
              </p>
              <div className="flex flex-col gap-3">
                {STATS.map(({ key, label, better, pct }) => {
                  const a = compare.team_a_stats[key as keyof TeamStats] ?? 0;
                  const b = compare.team_b_stats[key as keyof TeamStats] ?? 0;
                  const aWins = better !== 0 && (better === 1 ? a > b : a < b);
                  const bWins = better !== 0 && (better === 1 ? b > a : b < a);
                  const { aPct, bPct } = barPcts(a, b, better);
                  return (
                    <div key={key}>
                      <div className="flex items-center mb-1">
                        <span className={`w-12 text-xs font-bold ${aWins ? "text-green-600 dark:text-green-400" : "text-gray-500"}`}>
                          {fmt(a, pct)}
                        </span>
                        <span className="flex-1 text-center text-[10px] text-gray-500 uppercase tracking-wide">
                          {label}
                        </span>
                        <span className={`w-12 text-xs font-bold text-right ${bWins ? "text-green-600 dark:text-green-400" : "text-gray-500"}`}>
                          {fmt(b, pct)}
                        </span>
                      </div>
                      <div className="flex h-[3px] gap-[2px]">
                        <div className="flex-1 bg-gray-100 dark:bg-gray-800 rounded-l-full overflow-hidden flex justify-end">
                          <div className={`h-full rounded-l-full ${aWins ? "bg-green-500" : "bg-gray-300 dark:bg-gray-600"}`} style={{ width: `${aPct}%` }} />
                        </div>
                        <div className="flex-1 bg-gray-100 dark:bg-gray-800 rounded-r-full overflow-hidden">
                          <div className={`h-full rounded-r-full ${bWins ? "bg-green-500" : "bg-gray-300 dark:bg-gray-600"}`} style={{ width: `${bPct}%` }} />
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </>
      )}
    </main>
  );
}

function ProbChart({ data, awayTeam, homeTeam }: {
  data: HistoryPoint[]; awayTeam: string; homeTeam: string;
}) {
  const ac   = getColor(awayTeam);
  const hc   = getColor(homeTeam);
  const last = data[data.length - 1];

  // Approximate pixel y for each endpoint (chart height=150, topMargin=8, domain [0,100])
  const PLOT_H = 142;
  const aY = 8 + (1 - (last?.team_a_prob ?? 50) / 100) * PLOT_H;
  const bY = 8 + (1 - (last?.team_b_prob ?? 50) / 100) * PLOT_H;
  const diff = bY - aY;
  const MIN_GAP = 42;
  let aOff = 0, bOff = 0;
  if (Math.abs(diff) < MIN_GAP) {
    const push = (MIN_GAP - Math.abs(diff)) / 2;
    if (diff >= 0) { aOff = -push; bOff = push; }
    else           { aOff =  push; bOff = -push; }
  }

  const EndDot = (color: string) => (props: { cx?: number; cy?: number; index?: number }) => {
    const { cx = 0, cy = 0, index = 0 } = props;
    if (index !== data.length - 1) return <g />;
    return <circle cx={cx} cy={cy} r={5} fill={color} />;
  };

  const EndLabel = (team: string, color: string, yOff: number) =>
    (props: { x?: number; y?: number; index?: number; value?: number }) => {
      const { x = 0, y = 0, index = 0, value = 0 } = props;
      if (index !== data.length - 1) return null;
      const adjY = Number(y) + yOff;
      return (
        <g>
          <text x={Number(x) + 10} y={adjY - 5} fill={color} fontSize={9} fontWeight="700" fontFamily="inherit">{getAbbr(team)}</text>
          <text x={Number(x) + 10} y={adjY + 9} fill={color} fontSize={14} fontWeight="900" fontFamily="inherit">{value}%</text>
        </g>
      );
    };

  return (
    <div className="bg-white dark:bg-gray-900 border border-gray-100 dark:border-transparent shadow-sm rounded-2xl px-6 pt-5 pb-4">
      <div className="flex items-start justify-between mb-3">
        <p className="text-[10px] font-semibold text-gray-500 uppercase tracking-widest">
          Series Win Probability
        </p>
        <div className="flex gap-5">
          <div className="text-right">
            <p className="text-[10px] font-bold" style={{ color: ac }}>{getAbbr(awayTeam)}</p>
            <p className="text-lg font-black leading-none" style={{ color: ac }}>{last?.team_a_prob}%</p>
          </div>
          <div className="text-right">
            <p className="text-[10px] font-bold" style={{ color: hc }}>{getAbbr(homeTeam)}</p>
            <p className="text-lg font-black leading-none" style={{ color: hc }}>{last?.team_b_prob}%</p>
          </div>
        </div>
      </div>

      <ResponsiveContainer width="100%" height={150}>
        <LineChart data={data} margin={{ top: 8, right: 70, bottom: 0, left: -8 }}>
          <CartesianGrid strokeDasharray="2 5" stroke="var(--chart-grid)" vertical={false} />
          <XAxis
            dataKey="game"
            tick={{ fill: "var(--chart-tick)", fontSize: 10 }}
            axisLine={false}
            tickLine={false}
            interval={0}
          />
          <YAxis
            domain={[0, 100]}
            ticks={[0, 25, 50, 75, 100]}
            tick={{ fill: "var(--chart-tick)", fontSize: 10 }}
            axisLine={false}
            tickLine={false}
            tickFormatter={v => `${v}%`}
            width={30}
          />
          <Tooltip
            contentStyle={{ background: "var(--tooltip-bg)", border: "1px solid var(--tooltip-border)", borderRadius: 8, fontSize: 11, color: "var(--tooltip-text)" }}
            labelStyle={{ color: "#6b7280", marginBottom: 4 }}
            labelFormatter={(label, payload) => {
              const s = (payload?.[0]?.payload as HistoryPoint | undefined)?.series;
              return s ? `${label} — ${s}` : label;
            }}
            formatter={(v: unknown, name: string | undefined) => [
              `${v}%`,
              name === "team_a_prob" ? getAbbr(awayTeam) : getAbbr(homeTeam),
            ]}
          />
          <Line type="monotone" dataKey="team_a_prob" stroke={ac} strokeWidth={2} dot={EndDot(ac)} activeDot={{ r: 4 }}>
            <LabelList dataKey="team_a_prob" content={EndLabel(awayTeam, ac, aOff) as never} />
          </Line>
          <Line type="monotone" dataKey="team_b_prob" stroke={hc} strokeWidth={2} dot={EndDot(hc)} activeDot={{ r: 4 }}>
            <LabelList dataKey="team_b_prob" content={EndLabel(homeTeam, hc, bOff) as never} />
          </Line>
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

function InjuryColumn({ team, data }: { team: string; data: InjuryData | undefined }) {
  return (
    <div>
      <p className="text-gray-900 dark:text-white font-bold text-xs mb-2">{lastName(team)}</p>
      {!data || data.players.length === 0 ? (
        <p className="text-[11px] text-gray-400 dark:text-gray-600">No injuries reported</p>
      ) : (
        <div className="flex flex-col gap-1.5">
          {data.players.map(p => (
            <div key={p.name} className="flex items-center gap-1.5">
              <span className={`text-[10px] px-1 py-0.5 rounded font-bold flex-shrink-0 ${STATUS_COLOR[p.status] ?? "bg-white/10 text-gray-400"}`}>
                {p.status === "Day-To-Day" ? "D2D" : p.status}
              </span>
              <span className="text-[11px] text-gray-600 dark:text-gray-300 truncate">{p.name.split(" ").pop()}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
