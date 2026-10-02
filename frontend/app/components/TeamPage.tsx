"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { playerHref, teamHref } from "./teamLinks";
import { BarChart, Bar, Cell, XAxis, YAxis, Tooltip, ResponsiveContainer, ReferenceLine } from "recharts";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// ── Types (mirror get_team_page in api/main.py) ────────────────────────────────

export type League = "nfl" | "mlb" | "nba";

interface TeamGame {
  game_id: string; date: string; season_type: "reg" | "post"; label: string;
  home: boolean; neutral: boolean; opponent: string; opponent_abbr: string;
  team_score: number | null; opp_score: number | null; result: "W" | "L" | "T" | null;
  completed: boolean; status: string; win_prob?: number | null;
}
interface GameRef {
  game_id: string; date: string; opponent: string; home: boolean;
  team_score: number; opp_score: number; margin: number;
}
interface Facts {
  games: number; record: string; home: string; road: string; last10: string; streak: string;
  longest_win_streak: number; longest_loss_streak: number;
  points_for: number; points_against: number; differential: number;
  close: { record: string; threshold: number }; blowouts: { record: string; threshold: number };
  after_loss: string; best_win: GameRef | null; worst_loss: GameRef | null; unit: string;
  by_month?: { month: string; record: string; differential: number }[];
}
interface StatRow { label: string; value: string; rank: number | null; rank_display: string | null; }
interface LeaderRow { label: string; id: string | null; name: string; position: string; value: string; headshot: string | null; }
interface ModelBlock {
  power?: number; power_rank?: number; trend?: number; off_rank?: number; def_rank?: number;
  qb_name?: string; qb_rank?: number; sos_rank?: number; rem_sos_rank?: number;
  projected_wins?: number; playoff_pct?: number; division_pct?: number;
  top_seed_pct?: number; conf_pct?: number; sb_win_pct?: number;
}
interface TeamPageData {
  league: League;
  team: { id: string; abbr: string; name: string; nickname: string; location: string;
          color: string; alt_color: string; logo: string | null; standing: string; };
  season: { year: number; is_current: boolean; label: string };
  record: Record<string, string>;
  next_game: TeamGame | null;
  facts: Facts | Record<string, never>;
  stats: StatRow[];
  stats_rank_scope: "league" | "division";
  leaders: LeaderRow[];
  model: ModelBlock | null;
  games: TeamGame[];
  postseason: TeamGame[];
}

// ── Helpers ────────────────────────────────────────────────────────────────────

const LEAGUE_TEAMS: Record<League, number> = { nfl: 32, mlb: 30, nba: 30 };
const SCORE_WORD: Record<League, string> = { nfl: "Points", mlb: "Runs", nba: "Points" };

function logoUrl(league: League, espnAbbr: string) {
  return `https://a.espncdn.com/i/teamlogos/${league}/500/${espnAbbr.toLowerCase()}.png`;
}

function fmtDate(iso: string, withYear = false) {
  try {
    return new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric", ...(withYear ? { year: "numeric" } : {}) });
  } catch { return iso; }
}

function fmtDateTime(iso: string) {
  try {
    return new Date(iso).toLocaleString("en-US", { weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
  } catch { return iso; }
}

function fmtMonth(ym: string) {
  const [y, m] = ym.split("-").map(Number);
  return new Date(y, m - 1, 1).toLocaleDateString("en-US", { month: "short" });
}

/** Link to our game page — only NFL game pages use ESPN ids. */
function gameHref(league: League, gameId: string): string | null {
  return league === "nfl" ? `/nfl/game/${gameId}` : null;
}

function rankClass(rank: number | null, of: number) {
  if (!rank) return "text-gray-400";
  if (rank <= Math.round(of / 3)) return "text-green-600 dark:text-green-400";
  if (rank > of - Math.round(of / 3)) return "text-red-500 dark:text-red-400";
  return "text-gray-500";
}

function ordinal(n: number) {
  const s = ["th", "st", "nd", "rd"], v = n % 100;
  return n + (s[(v - 20) % 10] || s[v] || s[0]);
}

const card = "bg-white dark:bg-gray-900 border border-gray-100 dark:border-transparent shadow-sm rounded-2xl p-5";
const cardTitle = "text-[10px] font-semibold text-gray-500 uppercase tracking-widest";

function Img({ src, alt, className, fallback }: { src: string | null; alt: string; className: string; fallback: string }) {
  // Remember which URL failed, so a new team/player gets a fresh attempt
  const [failedSrc, setFailedSrc] = useState<string | null>(null);
  if (!src || (failedSrc !== null && failedSrc === src)) return <div className={`${className} rounded-full`} style={{ background: fallback }} />;
  return <img src={src} alt={alt} className={className} onError={() => setFailedSrc(src)} />;
}

// ── Sections ───────────────────────────────────────────────────────────────────

function Hero({ d }: { d: TeamPageData }) {
  const f = d.facts as Facts;
  const chips: [string, string | undefined][] = [
    ["Home", d.record.home ?? f.home], ["Road", d.record.road ?? f.road],
    ["Last 10", f.last10], ["Streak", f.streak],
  ];
  return (
    <div className={`${card} relative overflow-hidden`}>
      <div className="absolute inset-x-0 top-0 h-1" style={{ background: `linear-gradient(90deg, ${d.team.color}, ${d.team.alt_color})` }} />
      <div className="flex flex-col sm:flex-row sm:items-center gap-5">
        <Img src={d.team.logo} alt={d.team.name} className="w-20 h-20 object-contain flex-shrink-0" fallback={d.team.color} />
        <div className="flex-1 min-w-0">
          <p className="text-[11px] font-semibold text-gray-400 uppercase tracking-widest">
            {d.league.toUpperCase()} · {d.season.label}{d.season.is_current ? "" : " season"}
          </p>
          <h1 className="text-2xl lg:text-3xl font-black text-gray-900 dark:text-white leading-tight">{d.team.name}</h1>
          {d.team.standing && <p className="text-sm text-gray-500 mt-0.5">{d.team.standing}</p>}
        </div>
        <div className="flex items-end gap-6">
          <div>
            <p className={cardTitle}>Record</p>
            <p className="text-3xl font-black tabular-nums text-gray-900 dark:text-white">{d.record.total ?? f.record ?? "—"}</p>
          </div>
          {f.differential !== undefined && (
            <div>
              <p className={cardTitle}>Diff / game</p>
              <p className={`text-3xl font-black tabular-nums ${f.differential >= 0 ? "text-green-600 dark:text-green-400" : "text-red-500"}`}>
                {f.differential > 0 ? "+" : ""}{f.differential}
              </p>
            </div>
          )}
        </div>
      </div>
      <div className="mt-4 flex flex-wrap gap-2">
        {chips.filter(([, v]) => v).map(([k, v]) => (
          <span key={k} className="text-xs rounded-full bg-gray-50 dark:bg-gray-800 px-3 py-1 text-gray-600 dark:text-gray-300">
            <span className="text-gray-400">{k}</span> <span className="font-bold tabular-nums">{v}</span>
          </span>
        ))}
      </div>
    </div>
  );
}

function NextGame({ d }: { d: TeamPageData }) {
  const g = d.next_game;
  if (!g) return null;
  const href = gameHref(d.league, g.game_id);
  const body = (
    <div className={`${card} h-full flex flex-col ${href ? "hover:ring-1 hover:ring-gray-200 dark:hover:ring-gray-700 transition" : ""}`}>
      <p className={cardTitle}>Next game{g.season_type === "post" ? " · Playoffs" : ""}</p>
      <div className="flex-1 flex items-center gap-4 py-3">
        <img src={logoUrl(d.league, g.opponent_abbr)} alt="" className="w-16 h-16 object-contain" />
        <div className="min-w-0">
          <p className="text-lg font-bold text-gray-900 dark:text-white truncate">{g.home ? "vs" : "@"} {g.opponent}</p>
          <p className="text-xs text-gray-400">{fmtDateTime(g.date)}{g.label ? ` · ${g.label}` : ""}</p>
          <p className="text-xs text-gray-400">{g.neutral ? "Neutral site" : g.home ? "Home" : "Away"}</p>
        </div>
      </div>
      {g.win_prob != null && (
        <div>
          <div className="flex justify-between text-xs mb-1">
            <span className="text-gray-500">Our model</span>
            <span className="font-bold text-gray-900 dark:text-white tabular-nums">{g.win_prob}% to win</span>
          </div>
          <div className="h-1.5 rounded-full bg-gray-100 dark:bg-gray-800 overflow-hidden">
            <div className="h-full rounded-full" style={{ width: `${g.win_prob}%`, background: d.team.color }} />
          </div>
        </div>
      )}
    </div>
  );
  return href ? <Link href={href} className="block h-full">{body}</Link> : body;
}

function ModelCard({ d }: { d: TeamPageData }) {
  const m = d.model;
  if (!m) return null;
  const tiles: [string, string, string?][] = [];
  if (m.power_rank != null) tiles.push(["Power rank", `#${m.power_rank}`, `${m.power! > 0 ? "+" : ""}${m.power} pts vs avg`]);
  if (m.projected_wins != null) tiles.push(["Projected wins", `${m.projected_wins}`]);
  if (m.playoff_pct != null) tiles.push(["Make playoffs", `${m.playoff_pct}%`]);
  if (m.division_pct != null) tiles.push(["Win division", `${m.division_pct}%`]);
  if (m.conf_pct != null) tiles.push(["Win conference", `${m.conf_pct}%`]);
  if (m.sb_win_pct != null) tiles.push(["Win Super Bowl", `${m.sb_win_pct}%`]);
  const ranks: [string, number | undefined][] = [
    ["Offense (EPA)", m.off_rank], ["Defense (EPA)", m.def_rank],
    [`QB${m.qb_name ? ` · ${m.qb_name}` : ""}`, m.qb_rank], ["Schedule left (1st = hardest)", m.rem_sos_rank],
  ];
  return (
    <div className={`${card} h-full`}>
      <div className="flex items-baseline justify-between">
        <p className={cardTitle}>Our model</p>
        {m.trend ? (
          <span className={`text-[11px] font-semibold ${m.trend > 0 ? "text-green-600 dark:text-green-400" : "text-red-500"}`}>
            {m.trend > 0 ? "▲" : "▼"} {Math.abs(m.trend)} this week
          </span>
        ) : null}
      </div>
      <div className="mt-3 grid grid-cols-3 gap-2">
        {tiles.map(([k, v, sub]) => (
          <div key={k} className="rounded-lg bg-gray-50 dark:bg-gray-800/60 px-3 py-2">
            <p className="text-[10px] text-gray-400 uppercase tracking-wide">{k}</p>
            <p className="text-lg font-black text-gray-900 dark:text-white tabular-nums">{v}</p>
            {sub && <p className="text-[10px] text-gray-400">{sub}</p>}
          </div>
        ))}
      </div>
      <div className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1.5">
        {ranks.filter(([, r]) => r != null).map(([k, r]) => (
          <div key={k} className="flex justify-between text-xs">
            <span className="text-gray-500 truncate">{k}</span>
            <span className={`font-bold tabular-nums ${rankClass(k.startsWith("Schedule") ? 33 - r! : r!, 32)}`}>{ordinal(r!)}</span>
          </div>
        ))}
      </div>
      {m.rem_sos_rank != null && (
        <p className="mt-2 text-[10px] text-gray-400">Green = good for the team (an easy schedule left is good).</p>
      )}
    </div>
  );
}

function StatsCard({ d }: { d: TeamPageData }) {
  if (!d.stats.length) return null;
  const of = d.stats_rank_scope === "division" ? 5 : LEAGUE_TEAMS[d.league];
  return (
    <div className={`${card} h-full flex flex-col`}>
      <div className="flex items-baseline justify-between mb-3">
        <p className={cardTitle}>Team stats</p>
        <p className="text-[11px] text-gray-400">Rank {d.stats_rank_scope === "division" ? "in division" : "in league"}</p>
      </div>
      <div className="flex-1 grid grid-cols-2 sm:grid-cols-3 auto-rows-fr gap-2">
        {d.stats.map(s => (
          <div key={s.label} className="rounded-lg bg-gray-50 dark:bg-gray-800/60 px-3 py-2 flex flex-col justify-center">
            <p className="text-[10px] text-gray-400 uppercase tracking-wide truncate">{s.label}</p>
            <div className="flex items-baseline justify-between gap-2">
              <span className="text-base font-black text-gray-900 dark:text-white tabular-nums">{s.value}</span>
              {s.rank_display && <span className={`text-[11px] font-semibold ${rankClass(s.rank, of)}`}>{s.rank_display}</span>}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function LeadersCard({ d }: { d: TeamPageData }) {
  if (!d.leaders.length) return null;
  return (
    <div className={`${card} h-full flex flex-col`}>
      <div className="flex items-center justify-between mb-3">
        <p className={cardTitle}>Team leaders</p>
        <Link href={`${teamHref(d.league, d.team.name)}/roster`}
          className="inline-flex items-center gap-1 rounded-full bg-gray-50 dark:bg-gray-800 px-3 py-1 text-[11px] font-semibold text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors">
          View roster
          <svg width="10" height="10" viewBox="0 0 10 10" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"><path d="M3.5 1.5L7 5l-3.5 3.5" /></svg>
        </Link>
      </div>
      <ul className="flex-1 grid grid-cols-1 sm:grid-cols-2 auto-rows-fr gap-x-6 gap-y-3">
        {d.leaders.map(l => (
          <li key={l.label} className="flex items-center gap-3 min-w-0">
            <Img src={l.headshot} alt="" className="w-11 h-11 rounded-full object-cover bg-gray-100 dark:bg-gray-800 flex-shrink-0" fallback={d.team.color} />
            <div className="min-w-0 flex-1">
              <p className="text-[10px] text-gray-400 uppercase tracking-wide">{l.label}</p>
              <p className="text-sm font-bold text-gray-900 dark:text-white truncate">
                {l.id ? <Link href={playerHref(d.league, l.id)} className="inline-block transition-transform hover:scale-105 origin-left">{l.name}</Link> : l.name}{l.position && <span className="font-normal text-gray-400"> · {l.position}</span>}
              </p>
            </div>
            <span className="text-lg font-black tabular-nums" style={{ color: d.team.color }}>{l.value}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function GameLine({ league, g, label }: { league: League; g: GameRef; label: string }) {
  const href = gameHref(league, g.game_id);
  const inner = (
    <>
      <span className="text-gray-500">{label}</span>
      <span className="font-semibold text-gray-800 dark:text-gray-200 text-right">
        {g.team_score}–{g.opp_score} {g.home ? "vs" : "@"} {g.opponent.split(" ").pop()}
        <span className="text-gray-400 font-normal"> · {fmtDate(g.date)}</span>
      </span>
    </>
  );
  return href
    ? <Link href={href} className="flex justify-between gap-3 text-xs hover:underline">{inner}</Link>
    : <div className="flex justify-between gap-3 text-xs">{inner}</div>;
}

function FactsCard({ d }: { d: TeamPageData }) {
  const f = d.facts as Facts;
  if (!f.games) return null;
  const word = SCORE_WORD[d.league];
  const closeLabel = d.league === "mlb" ? "One-run games" : `Games decided by ≤ ${f.close.threshold}`;
  const rows: [string, string][] = [
    [`${word} scored / game`, `${f.points_for}`],
    [`${word} allowed / game`, `${f.points_against}`],
    [closeLabel, f.close.record],
    [`Wins/losses by ${f.blowouts.threshold}+`, f.blowouts.record],
    ["After a loss", f.after_loss],
    ["Longest win streak", `${f.longest_win_streak}`],
    ["Longest losing streak", `${f.longest_loss_streak}`],
  ];
  return (
    <div className={card}>
      <p className={`${cardTitle} mb-3`}>Splits &amp; facts</p>
      <dl className="flex flex-col gap-1.5">
        {rows.map(([k, v]) => (
          <div key={k} className="flex justify-between text-xs">
            <dt className="text-gray-500">{k}</dt>
            <dd className="font-bold text-gray-900 dark:text-white tabular-nums">{v}</dd>
          </div>
        ))}
      </dl>
      {(f.best_win || f.worst_loss) && (
        <div className="mt-3 pt-3 border-t border-gray-100 dark:border-gray-800 flex flex-col gap-1.5">
          {f.best_win && <GameLine league={d.league} g={f.best_win} label="Biggest win" />}
          {f.worst_loss && <GameLine league={d.league} g={f.worst_loss} label="Worst loss" />}
        </div>
      )}
      {f.by_month && f.by_month.length > 1 && (
        <div className="mt-3 pt-3 border-t border-gray-100 dark:border-gray-800">
          <p className="text-[10px] text-gray-400 uppercase tracking-wide mb-2">By month</p>
          <div className="grid gap-1.5" style={{ gridTemplateColumns: `repeat(${f.by_month.length}, minmax(0, 1fr))` }}>
            {f.by_month.map(m => (
              <div key={m.month} className="text-center">
                <p className="text-[10px] text-gray-400">{fmtMonth(m.month)}</p>
                <p className="text-xs font-bold tabular-nums text-gray-900 dark:text-white">{m.record}</p>
                <p className={`text-[10px] tabular-nums ${m.differential >= 0 ? "text-green-600 dark:text-green-400" : "text-red-500"}`}>
                  {m.differential > 0 ? "+" : ""}{m.differential}
                </p>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function MarginChart({ d }: { d: TeamPageData }) {
  const done = d.games.filter(g => g.completed);
  if (done.length < 2) return null;
  const data = done.map((g, i) => ({
    i: i + 1, margin: (g.team_score ?? 0) - (g.opp_score ?? 0),
    label: `${fmtDate(g.date)} ${g.home ? "vs" : "@"} ${g.opponent_abbr}: ${g.team_score}–${g.opp_score}`,
  }));
  return (
    <div className={card}>
      <div className="flex items-baseline justify-between mb-2">
        <p className={cardTitle}>Game-by-game margin</p>
        <p className="text-[11px] text-gray-400">{d.season.label} regular season · {done.length} games</p>
      </div>
      <ResponsiveContainer width="100%" height={140}>
        <BarChart data={data} margin={{ top: 4, right: 4, bottom: 0, left: -20 }}>
          <XAxis dataKey="i" hide />
          <YAxis tick={{ fill: "var(--chart-tick)", fontSize: 10 }} axisLine={false} tickLine={false} />
          <ReferenceLine y={0} stroke="var(--chart-grid)" />
          <Tooltip
            cursor={{ fill: "rgba(127,127,127,0.08)" }}
            content={({ active, payload }) => active && payload?.length ? (
              <div className="rounded-lg bg-white dark:bg-gray-800 shadow px-2.5 py-1.5 text-xs text-gray-700 dark:text-gray-200">
                {(payload[0].payload as { label: string }).label}
              </div>
            ) : null}
          />
          <Bar dataKey="margin" radius={[2, 2, 0, 0]}>
            {data.map(x => <Cell key={x.i} fill={x.margin >= 0 ? "#16a34a" : "#ef4444"} />)}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

function GameRow({ league, g }: { league: League; g: TeamGame }) {
  const href = g.completed ? gameHref(league, g.game_id) : null;
  const badge = g.result === "W" ? "bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300"
    : g.result === "L" ? "bg-red-100 text-red-600 dark:bg-red-900/40 dark:text-red-300"
    : "bg-gray-100 text-gray-500 dark:bg-gray-800 dark:text-gray-400";
  const content = (
    <>
      <span className="w-14 flex-shrink-0 text-gray-400 tabular-nums">{fmtDate(g.date)}</span>
      {g.label && league === "nfl" && <span className="hidden sm:block w-16 flex-shrink-0 text-gray-400">{g.label}</span>}
      <span className="w-5 text-gray-400">{g.neutral ? "vs" : g.home ? "vs" : "@"}</span>
      <img src={logoUrl(league, g.opponent_abbr)} alt="" className="w-5 h-5 object-contain" />
      <span className="flex-1 min-w-0 truncate text-gray-700 dark:text-gray-300">{g.opponent}</span>
      {g.completed ? (
        <>
          <span className={`w-6 text-center text-[10px] font-bold rounded ${badge}`}>{g.result}</span>
          <span className="w-14 text-right font-semibold tabular-nums text-gray-800 dark:text-gray-200">{g.team_score}–{g.opp_score}</span>
        </>
      ) : (
        <span className="text-gray-400 text-right">{g.status || fmtDateTime(g.date)}</span>
      )}
    </>
  );
  return (
    <li>
      {href
        ? <Link href={href} className="flex items-center gap-2 py-1.5 text-xs hover:bg-gray-50 dark:hover:bg-gray-800/50 rounded px-1 -mx-1">{content}</Link>
        : <div className="flex items-center gap-2 py-1.5 text-xs">{content}</div>}
    </li>
  );
}

function ScheduleCard({ d }: { d: TeamPageData }) {
  const [showAll, setShowAll] = useState(false);
  const games = d.games;
  const long = games.length > 20;
  // Long seasons: latest games first, collapsed to the last 15
  const ordered = long ? [...games].filter(g => g.completed).reverse() : games;
  const shown = long && !showAll ? ordered.slice(0, 15) : ordered;
  return (
    <div className={card}>
      <div className="flex items-baseline justify-between mb-2">
        <p className={cardTitle}>{long ? "Results" : "Schedule"} · {d.season.label}</p>
        {long && (
          <button onClick={() => setShowAll(v => !v)} className="text-[11px] font-semibold text-gray-500 hover:text-gray-800 dark:hover:text-gray-200">
            {showAll ? "Show fewer" : `Show all ${ordered.length}`}
          </button>
        )}
      </div>
      <ul className="divide-y divide-gray-100 dark:divide-gray-800">
        {shown.map(g => <GameRow key={g.game_id} league={d.league} g={g} />)}
      </ul>
    </div>
  );
}

function PostseasonCard({ d }: { d: TeamPageData }) {
  if (!d.postseason.length) return null;
  return (
    <div className={card}>
      <p className={`${cardTitle} mb-2`}>Playoffs · {d.season.label}</p>
      <ul className="divide-y divide-gray-100 dark:divide-gray-800">
        {d.postseason.map(g => <GameRow key={g.game_id} league={d.league} g={g} />)}
      </ul>
    </div>
  );
}

// ── Page ───────────────────────────────────────────────────────────────────────

export default function TeamPage({ league, team, backHref, backLabel }: {
  league: League; team: string; backHref: string; backLabel: string;
}) {
  const [data, setData] = useState<TeamPageData | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    let active = true;
    setData(null); setError(false);
    fetch(`${API}/api/team/${league}/${encodeURIComponent(team)}`)
      .then(r => { if (!r.ok) throw new Error(String(r.status)); return r.json(); })
      .then((d: TeamPageData) => { if (active) setData(d); })
      .catch(() => { if (active) setError(true); });
    return () => { active = false; };
  }, [league, team]);

  return (
    <main className="px-4 lg:px-8 pt-4 lg:pt-5 pb-8 flex flex-col gap-3">
      <Link href={backHref} className="inline-flex items-center gap-1.5 text-xs text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 transition-colors">
        <svg width="13" height="13" viewBox="0 0 13 13" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
          <path d="M8 2L3 6.5l5 4.5" />
        </svg>
        {backLabel}
      </Link>

      {!data && !error && <div className={`${card} text-center text-xs text-gray-400`}>Loading team…</div>}
      {error && <div className={`${card} text-center text-xs text-gray-400`}>Could not load this team.</div>}

      {data && (
        <>
          <Hero d={data} />

          {(data.next_game || data.model) && (
            <div className={`grid grid-cols-1 gap-3 items-stretch ${data.model ? "lg:grid-cols-[minmax(0,1fr)_minmax(0,2fr)]" : ""}`}>
              <NextGame d={data} />
              <ModelCard d={data} />
            </div>
          )}

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-3 items-stretch">
            <StatsCard d={data} />
            <LeadersCard d={data} />
          </div>

          <MarginChart d={data} />

          <div className="grid grid-cols-1 lg:grid-cols-[minmax(0,1fr)_minmax(0,2fr)] gap-3 items-start">
            <div className="flex flex-col gap-3">
              <FactsCard d={data} />
              <PostseasonCard d={data} />
            </div>
            <ScheduleCard d={data} />
          </div>
        </>
      )}
    </main>
  );
}
