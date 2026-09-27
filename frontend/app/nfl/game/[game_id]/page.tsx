"use client";
import { use, useEffect, useRef, useState } from "react";
import Link from "next/link";
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid,
  ResponsiveContainer, Tooltip, ReferenceLine, LabelList,
} from "recharts";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// ── Types ──────────────────────────────────────────────────────────────────────

interface WinProbPoint {
  idx: number; label: string; away_prob: number; home_prob: number;
  scoring_play?: boolean; away_score?: number | null; home_score?: number | null;
}

interface NFLGameDetail {
  game_id:       string;
  status:        string;
  game_time_utc: string;
  venue:         string;
  away_team:     string;
  home_team:     string;
  away_score:    number | null;
  home_score:    number | null;
  away_quarters: (number | null)[];
  home_quarters: (number | null)[];
  away_win_prob: number;
  home_win_prob: number;
  win_prob_history: WinProbPoint[];
  away_stats:    Record<string, string>;
  home_stats:    Record<string, string>;
  explanation?:  Factor[];
  away_injuries?: Injury[];
  home_injuries?: Injury[];
}

interface Injury {
  name: string; position: string; status: string; injury: string; return_date: string | null;
}

interface Factor {
  feature: string; away_value: number; home_value: number;
  impact: number;  // > 0 favours the away team
}

// ── Team metadata ──────────────────────────────────────────────────────────────

const NFL_ABBR: Record<string, string> = {
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

const NFL_COLORS: Record<string, string> = {
  ARI: "#a40227", ATL: "#a71930", BAL: "#29126f", BUF: "#00338d",
  CAR: "#0085ca", CHI: "#0b1c3a", CIN: "#fb4f14", CLE: "#472a08",
  DAL: "#002a5c", DEN: "#0a2343", DET: "#0076b6", GB:  "#204e32",
  HOU: "#021018", IND: "#003b75", JAX: "#007487", KC:  "#e31837",
  LV:  "#000000", LAC: "#0080c6", LAR: "#003594", MIA: "#008e97",
  MIN: "#4f2683", NE:  "#002a5c", NO:  "#d3bc8d", NYG: "#003c7f",
  NYJ: "#115740", PHI: "#06424d", PIT: "#000000", SF:  "#aa0000",
  SEA: "#002a5c", TB:  "#bd1c36", TEN: "#4495d2", WSH: "#5a1414",
};

function getAbbr(t: string) { return NFL_ABBR[t] ?? t.split(" ").pop()?.slice(0, 3).toUpperCase() ?? "???"; }
function getColor(t: string) { return NFL_COLORS[getAbbr(t)] ?? "#555"; }
function getNick(t: string) { return t.split(" ").slice(-1)[0]; }
function getLogoUrl(t: string): string {
  const abbr = getAbbr(t);
  return abbr === "???" ? "" : `https://a.espncdn.com/i/teamlogos/nfl/500/${abbr.toLowerCase()}.png`;
}

function formatGameTime(iso: string): string {
  if (!iso) return "TBD";
  try {
    return new Date(iso).toLocaleString("en-US", {
      weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit", timeZoneName: "short",
    });
  } catch { return "TBD"; }
}

// ── Team logo ──────────────────────────────────────────────────────────────────

function TeamLogo({ team, size }: { team: string; size: string }) {
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

// ── Box score stat labels ───────────────────────────────────────────────────────

const STAT_LABELS: Record<string, string> = {
  totalYards:          "Total Yards",
  netPassingYards:     "Passing Yards",
  rushingYards:        "Rushing Yards",
  turnovers:           "Turnovers",
  thirdDownEff:        "3rd Down",
  totalPenaltiesYards: "Penalties",
  possessionTime:      "Possession",
};
const STAT_ORDER = ["totalYards", "netPassingYards", "rushingYards", "thirdDownEff", "turnovers", "totalPenaltiesYards", "possessionTime"];
// Lower is better for these (fewer turnovers/penalty yards is good)
const LOWER_IS_BETTER = new Set(["turnovers"]);

// ── Win probability chart ─────────────────────────────────────────────────────

function WinProbChart({ data, awayTeam, homeTeam }: {
  data: WinProbPoint[]; awayTeam: string; homeTeam: string;
}) {
  const ac      = getColor(awayTeam);
  const hc      = getColor(homeTeam);
  const first   = data[0];
  const last    = data[data.length - 1];
  const preOnly = data.length === 1;   // game hasn't started yet

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

  const quarterTicks = data
    .filter(d => d.label)
    .map(d => d.idx);
  const tickLabelByIdx = new Map(data.filter(d => d.label).map(d => [d.idx, d.label]));

  const Dot = (color: string) => (props: { cx?: number; cy?: number; index?: number; payload?: WinProbPoint }) => {
    const { cx = 0, cy = 0, index = 0, payload } = props;
    const isLast = index === data.length - 1;
    if (isLast) return <circle cx={cx} cy={cy} r={preOnly ? 6 : 5} fill={color} />;
    if (payload?.scoring_play) return <circle cx={cx} cy={cy} r={3} fill={color} stroke="var(--card-bg, #fff)" strokeWidth={1} />;
    return <g />;
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
            <p className="text-[10px] text-gray-400 mt-0.5">Pre-game · updates as quarters are played</p>
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
        <LineChart data={data} margin={{ top: 8, right: 70, bottom: 0, left: 0 }}>
          <CartesianGrid strokeDasharray="2 5" stroke="var(--chart-grid)" vertical={false} />
          <ReferenceLine y={50} stroke="var(--chart-grid)" strokeDasharray="3 3" />
          <XAxis
            dataKey="idx"
            type="number"
            domain={[0, "dataMax"]}
            ticks={quarterTicks}
            tickFormatter={(v: number) => tickLabelByIdx.get(v) ?? ""}
            tick={{ fill: "var(--chart-tick)", fontSize: 10 }}
            axisLine={false} tickLine={false}
          />
          <YAxis
            domain={[0, 100]}
            ticks={[0, 25, 50, 75, 100]}
            tick={{ fill: "var(--chart-tick)", fontSize: 10 }}
            axisLine={false} tickLine={false}
            tickFormatter={v => `${v}%`}
            width={38}
          />
          <Tooltip
            content={({ active, payload }) => {
              if (!active || !payload?.length) return null;
              const away  = payload.find(p => p.dataKey === "away_prob");
              const home  = payload.find(p => p.dataKey === "home_prob");
              const point = (payload[0]?.payload ?? {}) as WinProbPoint;
              let quarter = "";
              for (const d of data) {
                if (d.label) { if (d.idx <= point.idx) quarter = d.label; else break; }
              }
              const hasScore = point.away_score !== undefined && point.away_score !== null
                && point.home_score !== undefined && point.home_score !== null;
              return (
                <div style={{
                  background: "var(--tooltip-bg)", border: "1px solid var(--tooltip-border)",
                  borderRadius: 8, fontSize: 11, color: "var(--tooltip-text)",
                  padding: "6px 10px",
                }}>
                  <p style={{ color: "#6b7280", marginBottom: 4 }}>
                    {quarter || "Pre"}
                    {hasScore && ` · ${getAbbr(awayTeam)} ${point.away_score} - ${getAbbr(homeTeam)} ${point.home_score}`}
                    {point.scoring_play && " · Scoring play"}
                  </p>
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

// ── Quarter-by-quarter score table ──────────────────────────────────────────────

// ── Why the model leans ────────────────────────────────────────────────────────

const FACTOR_LABELS: Record<string, { label: string; desc: string; fmt: (v: number) => string }> = {
  elo_diff: {
    label: "Elo rating",
    desc: "Overall team strength. Goes up after wins (more for big wins), down after losses. Shown as the gap vs the opponent.",
    fmt: v => (v > 0 ? "+" : "") + v.toFixed(0),
  },
  qb_epa_diff: {
    label: "Starting QB",
    desc: "How many points per dropback each starting quarterback adds (EPA), based on his recent games. Shown as the gap vs the other QB.",
    fmt: v => (v > 0 ? "+" : "") + v.toFixed(2) + " EPA",
  },
  net_epa_diff: {
    label: "Efficiency (EPA)",
    desc: "Expected points added per play on offense minus what the defense allows, weighted toward recent games. Measures play-by-play quality, not just the final score.",
    fmt: v => (v > 0 ? "+" : "") + v.toFixed(2),
  },
  home: {
    label: "Home field",
    desc: "Home teams win about 55% of NFL games. Neutral-site games (London, Brazil…) give no home edge.",
    fmt: v => (v ? "Home" : "Away"),
  },
  off_bye: {
    label: "Off a bye",
    desc: "Whether the team had its bye week before this game — two weeks to rest and prepare.",
    fmt: v => (v ? "Yes" : "No"),
  },
  qb_changed: {
    label: "QB change",
    desc: "Whether the team is starting a different quarterback than last game, usually because of an injury or a benching.",
    fmt: v => (v ? "Yes" : "No"),
  },
  rest_diff: {
    label: "Extra rest",
    desc: "Days of rest compared with the opponent, e.g. coming off a Thursday game vs a Monday game.",
    fmt: v => (v > 0 ? "+" : "") + v.toFixed(0) + "d",
  },
};

function WhyPanel({ factors, awayTeam, homeTeam }: { factors: Factor[]; awayTeam: string; homeTeam: string }) {
  const shown = factors.filter(f => Math.abs(f.impact) >= 0.01).slice(0, 6);
  if (!shown.length) return null;
  const maxAbs = Math.max(...shown.map(f => Math.abs(f.impact)));
  return (
    <div className="bg-white dark:bg-gray-900 border border-gray-100 dark:border-transparent shadow-sm rounded-2xl p-5">
      <p className="text-[10px] font-semibold text-gray-500 uppercase tracking-widest mb-1">Why the model leans this way</p>
      <p className="text-xs text-gray-400 mb-4">Each bar is that factor&apos;s share of the pre-game edge. Values are from each team&apos;s side.</p>
      <div className="flex justify-between text-[11px] font-bold text-gray-700 dark:text-gray-300 mb-2">
        <span>← favours {getAbbr(awayTeam)}</span><span>favours {getAbbr(homeTeam)} →</span>
      </div>
      <div className="flex flex-col gap-2.5">
        {shown.map(f => {
          const meta = FACTOR_LABELS[f.feature] ?? { label: f.feature, desc: "", fmt: (v: number) => v.toFixed(2) };
          const w = (Math.abs(f.impact) / maxAbs) * 50;
          const favAway = f.impact > 0;
          return (
            <div key={f.feature}>
              <div className="flex items-center justify-between text-[11px] text-gray-500 mb-1 tabular-nums">
                <span className="w-20">{meta.fmt(f.away_value)}</span>
                <span className="relative group/def">
                  <span tabIndex={0} className="font-medium text-gray-700 dark:text-gray-300 cursor-help underline decoration-dotted decoration-gray-400 underline-offset-2">
                    {meta.label}
                  </span>
                  {meta.desc && (
                    <span role="tooltip" className="pointer-events-none absolute bottom-full left-1/2 -translate-x-1/2 mb-2 z-20 w-60 px-3 py-2 rounded-lg shadow-lg bg-gray-900 dark:bg-gray-800 text-white text-[11px] leading-relaxed font-normal text-left opacity-0 group-hover/def:opacity-100 group-focus-within/def:opacity-100 transition-opacity duration-150">
                      {meta.desc}
                    </span>
                  )}
                </span>
                <span className="w-20 text-right">{meta.fmt(f.home_value)}</span>
              </div>
              <div className="relative h-2 bg-gray-100 dark:bg-gray-800 rounded-full">
                <div className="absolute top-0 bottom-0 w-px bg-gray-300 dark:bg-gray-600" style={{ left: "50%" }} />
                <div className="absolute top-0 bottom-0 rounded-full"
                  style={{
                    width: `${w}%`,
                    left: favAway ? `${50 - w}%` : "50%",
                    background: getColor(favAway ? awayTeam : homeTeam),
                  }} />
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── Injuries ───────────────────────────────────────────────────────────────────

function statusStyle(status: string): { short: string; cls: string } {
  const s = status.toLowerCase();
  if (s === "out")                  return { short: "Out", cls: "bg-red-100 text-red-700 dark:bg-red-500/20 dark:text-red-400" };
  if (s.includes("reserve"))        return { short: "IR",  cls: "bg-red-100 text-red-700 dark:bg-red-500/20 dark:text-red-400" };
  if (s.includes("unable"))         return { short: "PUP", cls: "bg-red-100 text-red-700 dark:bg-red-500/20 dark:text-red-400" };
  if (s.includes("suspension"))     return { short: "Susp", cls: "bg-gray-200 text-gray-700 dark:bg-gray-700 dark:text-gray-300" };
  if (s === "doubtful")             return { short: "Doubtful", cls: "bg-orange-100 text-orange-700 dark:bg-orange-500/20 dark:text-orange-400" };
  if (s === "questionable")         return { short: "Quest.", cls: "bg-amber-100 text-amber-700 dark:bg-amber-500/20 dark:text-amber-400" };
  return { short: status, cls: "bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400" };
}

function fmtReturn(d: string | null): string | null {
  if (!d) return null;
  const [y, m, day] = d.split("-").map(Number);
  return new Date(y, m - 1, day).toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

function InjuryList({ team, players }: { team: string; players: Injury[] }) {
  return (
    <div className="min-w-0">
      <div className="flex items-center gap-2 mb-2.5">
        <TeamLogo team={team} size="w-5 h-5" />
        <span className="text-xs font-bold text-gray-700 dark:text-gray-300">{getAbbr(team)}</span>
        <span className="text-[11px] text-gray-400">{players.length} listed</span>
      </div>
      {players.length === 0 ? (
        <p className="text-xs text-gray-400">No injuries reported.</p>
      ) : (
        <ul className="flex flex-col gap-2">
          {players.map(p => {
            const st = statusStyle(p.status);
            const ret = fmtReturn(p.return_date);
            return (
              <li key={p.name} className="flex items-start gap-2">
                <span title={p.status} className={`flex-shrink-0 mt-px text-[10px] font-bold px-1.5 py-0.5 rounded ${st.cls}`}>{st.short}</span>
                <div className="min-w-0">
                  <p className="text-xs text-gray-800 dark:text-gray-200 truncate">
                    <span className={p.position === "QB" ? "font-bold" : "font-medium"}>{p.name}</span>
                    <span className="text-gray-400"> · {p.position}</span>
                  </p>
                  {(p.injury || ret) && (
                    <p className="text-[11px] text-gray-400 truncate">
                      {p.injury}{p.injury && ret ? " · " : ""}{ret ? `est. return ${ret}` : ""}
                    </p>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

function InjuryPanel({ awayTeam, homeTeam, away, home }: {
  awayTeam: string; homeTeam: string; away: Injury[]; home: Injury[];
}) {
  return (
    <div className="bg-white dark:bg-gray-900 border border-gray-100 dark:border-transparent shadow-sm rounded-2xl p-5">
      <p className="text-[10px] font-semibold text-gray-500 uppercase tracking-widest mb-4">Injury Report</p>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-5">
        <InjuryList team={awayTeam} players={away} />
        <InjuryList team={homeTeam} players={home} />
      </div>
      <p className="mt-4 pt-3 border-t border-gray-100 dark:border-gray-800 text-[11px] text-gray-400">
        Source: ESPN. The model accounts for an injured quarterback through the projected starter; other injuries aren&apos;t in the model.
      </p>
    </div>
  );
}

function Quarterscore({
  awayTeam, homeTeam, awayQuarters, homeQuarters, awayScore, homeScore,
}: {
  awayTeam: string; homeTeam: string;
  awayQuarters: (number | null)[]; homeQuarters: (number | null)[];
  awayScore: number; homeScore: number;
}) {
  const nCols = Math.max(4, awayQuarters.length, homeQuarters.length);
  const cols  = Array.from({ length: nCols }, (_, i) => i + 1);
  const colLabel = (n: number) => (n <= 4 ? `Q${n}` : "OT");

  const awayWins = awayScore > homeScore;
  const homeWins = homeScore > awayScore;

  return (
    <div className="bg-white dark:bg-gray-900 border border-gray-100 dark:border-transparent shadow-sm rounded-2xl p-5 overflow-x-auto">
      <p className="text-[10px] font-semibold text-gray-500 uppercase tracking-widest mb-4">Score by quarter</p>
      <table className="text-xs tabular-nums min-w-full">
        <thead>
          <tr>
            <th className="text-left text-gray-400 font-semibold pb-2 pr-4 min-w-[40px]" />
            {cols.map(n => (
              <th key={n} className="text-center text-gray-400 font-semibold pb-2 w-9 min-w-[32px]">{colLabel(n)}</th>
            ))}
            <th className="text-center text-gray-400 font-semibold pb-2 pl-3 border-l border-gray-200 dark:border-gray-700 min-w-[32px]">F</th>
          </tr>
        </thead>
        <tbody>
          <tr className="border-t border-gray-100 dark:border-gray-800">
            <td className={`pr-4 py-2 font-bold ${awayWins ? "text-gray-900 dark:text-white" : "text-gray-500"}`}>{getAbbr(awayTeam)}</td>
            {cols.map(n => (
              <td key={n} className="text-center py-2 text-gray-700 dark:text-gray-300">{awayQuarters[n - 1] ?? ""}</td>
            ))}
            <td className={`text-center py-2 pl-3 font-bold border-l border-gray-200 dark:border-gray-700 ${awayWins ? "text-gray-900 dark:text-white" : "text-gray-500"}`}>
              {awayScore}
            </td>
          </tr>
          <tr className="border-t border-gray-100 dark:border-gray-800">
            <td className={`pr-4 py-2 font-bold ${homeWins ? "text-gray-900 dark:text-white" : "text-gray-500"}`}>{getAbbr(homeTeam)}</td>
            {cols.map(n => (
              <td key={n} className="text-center py-2 text-gray-600 dark:text-gray-400 italic">{homeQuarters[n - 1] ?? ""}</td>
            ))}
            <td className={`text-center py-2 pl-3 font-bold border-l border-gray-200 dark:border-gray-700 ${homeWins ? "text-gray-900 dark:text-white" : "text-gray-500"}`}>
              {homeScore}
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  );
}

// ── Page ───────────────────────────────────────────────────────────────────────

export default function NFLGamePage({
  params, searchParams,
}: {
  params: Promise<{ game_id: string }>;
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
}) {
  const { game_id } = use(params);
  const sp = use(searchParams);

  const awayParam   = (sp.away   as string) ?? "";
  const homeParam   = (sp.home   as string) ?? "";
  const statusParam = (sp.status as string) ?? "";
  const awayProbParam = sp.away_prob ? Number(sp.away_prob) : null;
  const homeProbParam = sp.home_prob ? Number(sp.home_prob) : null;
  const awayScoreParam = sp.away_score ? Number(sp.away_score) : null;
  const homeScoreParam = sp.home_score ? Number(sp.home_score) : null;

  const [gameData, setGameData] = useState<NFLGameDetail | null>(null);
  const [loading,  setLoading]  = useState(true);
  const [fetchErr, setFetchErr] = useState(false);
  const retriedRef = useRef(false);

  useEffect(() => {
    let active = true;
    retriedRef.current = false;
    let ctrl  = new AbortController();
    let timer = setTimeout(() => ctrl.abort(), 20000);

    function doFetch() {
      fetch(`${API}/api/nfl/game/${game_id}`, { signal: ctrl.signal })
        .then(r => { if (!r.ok) throw new Error(String(r.status)); return r.json(); })
        .then((d: NFLGameDetail) => { if (active) { setGameData(d); setLoading(false); } })
        .catch((err) => {
          if (!active) return;
          if ((err as Error)?.name === "AbortError" && !retriedRef.current) {
            retriedRef.current = true;
            ctrl  = new AbortController();
            timer = setTimeout(() => ctrl.abort(), 15000);
            doFetch();
            return;
          }
          setFetchErr(true);
          setLoading(false);
        });
    }
    doFetch();
    return () => { active = false; ctrl.abort(); clearTimeout(timer); };
  }, [game_id]);

  const g       = gameData;
  const away    = g?.away_team ?? awayParam;
  const home    = g?.home_team ?? homeParam;
  const status  = g?.status    ?? statusParam;
  const isFinal = status.startsWith("Final");
  const isLive  = !isFinal && status !== "Scheduled" && status !== "";
  const showScore = isLive || isFinal;
  const awayScore = g?.away_score ?? awayScoreParam;
  const homeScore = g?.home_score ?? homeScoreParam;
  const awayWins  = isFinal && awayScore !== null && homeScore !== null && awayScore > homeScore;
  const homeWins  = isFinal && awayScore !== null && homeScore !== null && homeScore > awayScore;
  const awayProb  = g?.away_win_prob ?? awayProbParam ?? 50;
  const homeProb  = g?.home_win_prob ?? homeProbParam ?? 50;

  const hasStats = g && Object.keys(g.away_stats ?? {}).length > 0;
  const hasQuarters = g && (g.away_quarters.length > 0 || g.home_quarters.length > 0);
  const hasChart = g && (g.win_prob_history?.length ?? 0) >= 1;

  return (
    <main className="px-4 lg:px-8 pt-4 lg:pt-5 pb-8 flex flex-col gap-3">

      <Link href="/nfl" className="inline-flex items-center gap-1.5 text-xs text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 transition-colors">
        <svg width="13" height="13" viewBox="0 0 13 13" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
          <path d="M8 2L3 6.5l5 4.5" />
        </svg>
        Games
      </Link>

      {/* ── Hero card ── */}
      <div className="bg-white dark:bg-gray-900 border border-gray-100 dark:border-transparent shadow-sm rounded-2xl overflow-hidden">

        <div className="px-4 pt-4 flex items-center justify-between">
          <p className="text-[11px] font-semibold text-gray-500 uppercase tracking-widest">
            {isFinal ? "Final" : isLive ? status : formatGameTime(g?.game_time_utc ?? "")}
          </p>
          {isLive && (
            <span className="flex items-center gap-1.5 text-xs font-bold text-red-400">
              <span className="w-1.5 h-1.5 rounded-full bg-red-500 animate-pulse inline-block" />
              Live
            </span>
          )}
          {g?.venue && <span className="text-[11px] text-gray-400 hidden sm:block">{g.venue}</span>}
        </div>

        {/* Mobile */}
        <div className="lg:hidden px-4 pt-3 pb-0 flex flex-col gap-2">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <TeamLogo team={away} size="w-10 h-10" />
              <div>
                <p className={`font-bold text-base leading-tight ${isFinal && !awayWins ? "text-gray-400 dark:text-gray-600" : "text-gray-900 dark:text-white"}`}>{getNick(away)}</p>
                <p className="text-xs text-gray-400 mt-0.5">{awayProb}%</p>
              </div>
            </div>
            {showScore && awayScore !== null ? (
              <p className={`text-3xl font-black ${awayWins ? "text-gray-900 dark:text-white" : "text-gray-400 dark:text-gray-600"}`}>{awayScore}</p>
            ) : (
              <p className={`text-xl font-black ${awayProb > homeProb ? "text-green-600 dark:text-green-400" : "text-gray-400"}`}>{awayProb}%</p>
            )}
          </div>
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <TeamLogo team={home} size="w-10 h-10" />
              <div>
                <p className={`font-bold text-base leading-tight ${isFinal && !homeWins ? "text-gray-400 dark:text-gray-600" : "text-gray-900 dark:text-white"}`}>{getNick(home)}</p>
                <p className="text-xs text-gray-400 mt-0.5">{homeProb}%</p>
              </div>
            </div>
            {showScore && homeScore !== null ? (
              <p className={`text-3xl font-black ${homeWins ? "text-gray-900 dark:text-white" : "text-gray-400 dark:text-gray-600"}`}>{homeScore}</p>
            ) : (
              <p className={`text-xl font-black ${homeProb > awayProb ? "text-green-600 dark:text-green-400" : "text-gray-400"}`}>{homeProb}%</p>
            )}
          </div>
        </div>

        {/* Desktop */}
        <div className="hidden lg:grid px-8 pt-4 pb-3 grid-cols-[1fr_auto_1fr] items-center gap-6">
          <div className="flex items-center gap-4">
            <TeamLogo team={away} size="w-14 h-14" />
            <div>
              <p className={`font-bold text-xl leading-tight ${isFinal && !awayWins ? "text-gray-400 dark:text-gray-600" : "text-gray-900 dark:text-white"}`}>{getNick(away)}</p>
              {showScore && awayScore !== null ? (
                <p className={`text-3xl font-black mt-1 ${awayWins ? "text-gray-900 dark:text-white" : "text-gray-400 dark:text-gray-600"}`}>{awayScore}</p>
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
              {showScore && homeScore !== null ? (
                <p className={`text-3xl font-black mt-1 ${homeWins ? "text-gray-900 dark:text-white" : "text-gray-400 dark:text-gray-600"}`}>{homeScore}</p>
              ) : (
                <p className={`text-base font-bold mt-1 ${homeProb > awayProb ? "text-green-600 dark:text-green-400" : "text-gray-500"}`}>{homeProb}%</p>
              )}
            </div>
          </div>
        </div>

        <div className="mx-4 lg:mx-8 mt-3 mb-4 h-[3px] flex rounded-full overflow-hidden">
          <div className="h-full" style={{ width: `${awayProb}%`, background: getColor(away) }} />
          <div className="h-full flex-1" style={{ background: getColor(home) }} />
        </div>
      </div>

      {loading && (
        <div className="bg-white dark:bg-gray-900 border border-gray-100 dark:border-transparent shadow-sm rounded-2xl p-6 text-center text-xs text-gray-400">
          Loading game data…
        </div>
      )}
      {!loading && fetchErr && (
        <div className="bg-white dark:bg-gray-900 border border-gray-100 dark:border-transparent shadow-sm rounded-2xl p-6 text-center text-xs text-gray-400">
          Could not load game data.
        </div>
      )}

      {!loading && !fetchErr && g && (
        <>
          {hasQuarters && (isLive || isFinal) && (
            <Quarterscore
              awayTeam={away} homeTeam={home}
              awayQuarters={g.away_quarters} homeQuarters={g.home_quarters}
              awayScore={awayScore ?? 0} homeScore={homeScore ?? 0}
            />
          )}

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
                  <p className="text-[10px] font-semibold text-gray-500 uppercase tracking-widest mb-3">Stats Comparison</p>
                  <div className="flex flex-col gap-3">
                    {STAT_ORDER.filter(k => g.away_stats[k] !== undefined || g.home_stats[k] !== undefined).map(key => {
                      const a = g.away_stats[key] ?? "—";
                      const b = g.home_stats[key] ?? "—";
                      const aNum = parseFloat(a);
                      const bNum = parseFloat(b);
                      const numeric = !isNaN(aNum) && !isNaN(bNum);
                      const lowerBetter = LOWER_IS_BETTER.has(key);
                      const aWins = numeric && (lowerBetter ? aNum < bNum : aNum > bNum);
                      const bWins = numeric && (lowerBetter ? bNum < aNum : bNum > aNum);
                      return (
                        <div key={key} className="flex items-center">
                          <span className={`w-16 text-xs font-bold ${aWins ? "text-green-600 dark:text-green-400" : "text-gray-500"}`}>{a}</span>
                          <span className="flex-1 text-center text-[10px] text-gray-500 uppercase tracking-wide">{STAT_LABELS[key] ?? key}</span>
                          <span className={`w-16 text-xs font-bold text-right ${bWins ? "text-green-600 dark:text-green-400" : "text-gray-500"}`}>{b}</span>
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}
            </div>
          )}

          {g.explanation && g.explanation.length > 0 && (
            <div className="mt-3">
              <WhyPanel factors={g.explanation} awayTeam={away} homeTeam={home} />
            </div>
          )}

          {(g.away_injuries || g.home_injuries) && (
            <div className="mt-3">
              <InjuryPanel awayTeam={away} homeTeam={home} away={g.away_injuries ?? []} home={g.home_injuries ?? []} />
            </div>
          )}
        </>
      )}

    </main>
  );
}
