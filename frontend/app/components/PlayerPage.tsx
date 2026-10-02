"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import {
  BarChart, Bar, Cell, LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, ReferenceLine,
} from "recharts";
import { teamHref } from "./teamLinks";
import type { League } from "./TeamPage";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// ── Types (mirror get_player_page in api/main.py) ──────────────────────────────

interface ChartPoint { date: string; opp: string; at_vs: string; value: number; result: string | null; score: string; }
interface LogGame {
  game_id: string; date: string; at_vs: string; opponent: string; opponent_abbr: string;
  opponent_logo: string | null; result: string | null; score: string; stats: string[];
}
interface PlayerData {
  league: League;
  player: {
    id: string; name: string; jersey: string | null; position: string; position_abbr: string;
    headshot: string | null; age: number | null; height: string | null; weight: string | null;
    birthplace: string | null; draft: string | null; college: string | null; experience: string | null;
    bats_throws: string | null; status: string | null;
  };
  team: { name: string; abbr: string; color: string; logo: string | null } | null;
  summary: { label: string; value: string; rank: string | null }[];
  summary_title: string;
  season_lines: { labels: string[]; rows: { label: string; stats: string[] }[] };
  form: { label: string; season: number; last5: number | null }[];
  chart: { label: string; kind: "bar" | "line"; points: ChartPoint[] };
  best_game: (ChartPoint & { label: string }) | null;
  game_log: { title: string; labels: string[]; games: LogGame[] };
  splits: { labels: string[]; tables: { title: string; rows: { label: string; stats: string[] }[] }[] };
  career: { title: string; labels: string[]; rows: { season: string; team: string; stats: string[] }[]; totals: string[] | null } | null;
  note: { headline: string; story: string | null; published: string | null } | null;
  awards: { name: string; count: string; seasons: string[] }[];
  news: { headline: string; published: string; url: string | null }[];
}

// ── Helpers ────────────────────────────────────────────────────────────────────

const card = "bg-white dark:bg-gray-900 border border-gray-100 dark:border-transparent shadow-sm rounded-2xl p-5";
const cardTitle = "text-[10px] font-semibold text-gray-500 uppercase tracking-widest";

function fmtDate(iso: string, withYear = false) {
  try {
    return new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric", ...(withYear ? { year: "numeric" } : {}) });
  } catch { return iso; }
}

function Img({ src, className, fallback }: { src: string | null; className: string; fallback: string }) {
  const [err, setErr] = useState(false);
  if (!src || err) return <div className={`${className} rounded-full`} style={{ background: fallback }} />;
  return <img src={src} alt="" className={className} onError={() => setErr(true)} />;
}

function StatTable({ labels, rows, first }: {
  labels: string[]; rows: { key: string; head: React.ReactNode; stats: string[]; bold?: boolean }[]; first: string;
}) {
  return (
    <div className="overflow-x-auto -mx-1">
      <table className="w-full text-xs tabular-nums">
        <thead>
          <tr className="text-gray-400">
            <th className="text-left font-semibold py-1.5 px-1 whitespace-nowrap">{first}</th>
            {labels.map((l, i) => <th key={i} className="text-right font-semibold py-1.5 px-1.5 whitespace-nowrap">{l}</th>)}
          </tr>
        </thead>
        <tbody>
          {rows.map(r => (
            <tr key={r.key} className={`border-t border-gray-100 dark:border-gray-800 ${r.bold ? "font-bold text-gray-900 dark:text-white" : "text-gray-700 dark:text-gray-300"}`}>
              <td className="py-1.5 px-1 whitespace-nowrap">{r.head}</td>
              {labels.map((_, i) => <td key={i} className="text-right py-1.5 px-1.5 whitespace-nowrap">{r.stats[i] ?? ""}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ── Sections ───────────────────────────────────────────────────────────────────

function Hero({ d }: { d: PlayerData }) {
  const p = d.player;
  const color = d.team?.color ?? "#555";
  const bio: [string, string | number | null][] = [
    ["Age", p.age], ["Height", p.height], ["Weight", p.weight], ["B/T", p.bats_throws],
    ["Experience", p.experience], ["Draft", p.draft], ["College", p.college], ["Born", p.birthplace],
  ];
  return (
    <div className={`${card} relative overflow-hidden`}>
      <div className="absolute inset-x-0 top-0 h-1" style={{ background: color }} />
      <div className="flex flex-col sm:flex-row sm:items-center gap-5">
        <Img src={p.headshot} className="w-28 h-28 rounded-full object-cover bg-gray-100 dark:bg-gray-800 flex-shrink-0" fallback={color} />
        <div className="flex-1 min-w-0">
          {d.team && (
            <Link href={teamHref(d.league, d.team.name)} className="inline-flex items-center gap-1.5 group">
              {d.team.logo && <img src={d.team.logo} alt="" className="w-5 h-5 object-contain" />}
              <span className="text-xs font-semibold text-gray-500 group-hover:text-gray-800 dark:group-hover:text-gray-200">{d.team.name}</span>
            </Link>
          )}
          <h1 className="text-2xl lg:text-3xl font-black text-gray-900 dark:text-white leading-tight">{p.name}</h1>
          <p className="text-sm text-gray-500">
            {p.jersey ? `${p.jersey} · ` : ""}{p.position}
            {p.status && p.status !== "Active" && <span className="ml-2 text-[11px] font-bold px-1.5 py-0.5 rounded bg-red-100 text-red-600 dark:bg-red-900/40 dark:text-red-300">{p.status}</span>}
          </p>
          <dl className="mt-3 flex flex-wrap gap-x-5 gap-y-1">
            {bio.filter(([, v]) => v).map(([k, v]) => (
              <div key={k} className="text-xs">
                <dt className="inline text-gray-400">{k} </dt>
                <dd className="inline font-semibold text-gray-700 dark:text-gray-300">{v}</dd>
              </div>
            ))}
          </dl>
        </div>
        {d.summary.length > 0 && (
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 sm:min-w-[22rem]">
            {d.summary.map(s => (
              <div key={s.label} className="rounded-lg bg-gray-50 dark:bg-gray-800/60 px-3 py-2 text-center">
                <p className="text-[10px] text-gray-400 uppercase tracking-wide truncate">{s.label}</p>
                <p className="text-xl font-black tabular-nums text-gray-900 dark:text-white">{s.value}</p>
                {s.rank && <p className="text-[10px] text-gray-400">{s.rank}</p>}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

const FORM_WINDOW = 5;

function FormCard({ d }: { d: PlayerData }) {
  if (!d.form.length) return null;
  // With 5 games or fewer, "last 5" is the whole season — show season averages only
  const compare = d.game_log.games.length > FORM_WINDOW;
  return (
    <div className={`${card} h-full flex flex-col`}>
      <div className="flex items-baseline justify-between mb-3">
        <p className={cardTitle}>{compare ? "Recent form" : "Averages"}</p>
        <p className="text-[11px] text-gray-400">
          {compare ? `Last ${FORM_WINDOW} games vs season · per game` : `Per game · form comparison after ${FORM_WINDOW} games`}
        </p>
      </div>
      <div className="flex-1 grid grid-cols-2 auto-rows-fr gap-2">
        {d.form.map(f => {
          const diff = compare && f.last5 != null ? f.last5 - f.season : 0;
          // For stats where less is better (INT, ER, BB), a drop is good
          const lowerBetter = ["INT", "ER", "BB"].includes(f.label);
          const good = lowerBetter ? diff < 0 : diff > 0;
          return (
            <div key={f.label} className="rounded-lg bg-gray-50 dark:bg-gray-800/60 px-3 py-2 flex flex-col justify-center">
              <p className="text-[10px] text-gray-400 uppercase tracking-wide">{f.label}</p>
              <div className="flex items-baseline gap-2">
                <span className="text-xl font-black tabular-nums text-gray-900 dark:text-white">
                  {compare ? (f.last5 ?? "—") : f.season}
                </span>
                {compare && f.last5 != null && Math.abs(diff) >= 0.05 && (
                  <span className={`text-[11px] font-semibold ${good ? "text-green-600 dark:text-green-400" : "text-red-500"}`}>
                    {diff > 0 ? "▲" : "▼"} {Math.abs(diff).toFixed(1)}
                  </span>
                )}
              </div>
              <p className="text-[10px] text-gray-400">
                {compare ? <>Last {FORM_WINDOW} avg · season avg {f.season}</> : "Season avg"}
              </p>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function TrendCard({ d }: { d: PlayerData }) {
  const pts = d.chart.points;
  if (pts.length < 2) return null;
  const color = d.team?.color ?? "#555";
  const data = pts.map((p, i) => ({ ...p, i: i + 1 }));
  const avg = pts.reduce((s, p) => s + p.value, 0) / pts.length;
  const tip = ({ active, payload }: { active?: boolean; payload?: readonly { payload?: unknown }[] }) => {
    const p = active && payload?.length ? (payload[0].payload as ChartPoint) : null;
    return p ? (
      <div className="rounded-lg bg-white dark:bg-gray-800 shadow px-2.5 py-1.5 text-xs text-gray-700 dark:text-gray-200">
        <p className="font-bold">{p.value} {d.chart.label}</p>
        <p className="text-gray-400">{fmtDate(p.date)} {p.at_vs} {p.opp}{p.result ? ` · ${p.result} ${p.score}` : ""}</p>
      </div>
    ) : null;
  };
  return (
    <div className={`${card} h-full`}>
      <div className="flex items-baseline justify-between mb-2">
        <p className={cardTitle}>{d.chart.label} by game</p>
        <p className="text-[11px] text-gray-400">{d.game_log.title}</p>
      </div>
      <ResponsiveContainer width="100%" height={170}>
        {d.chart.kind === "line" ? (
          <LineChart data={data} margin={{ top: 4, right: 4, bottom: 0, left: -16 }}>
            <XAxis dataKey="i" hide />
            <YAxis domain={["auto", "auto"]} tick={{ fill: "var(--chart-tick)", fontSize: 10 }} axisLine={false} tickLine={false} />
            <Tooltip content={tip} />
            <Line dataKey="value" stroke={color} strokeWidth={2} dot={false} />
          </LineChart>
        ) : (
          <BarChart data={data} margin={{ top: 4, right: 4, bottom: 0, left: -16 }}>
            <XAxis dataKey="i" hide />
            <YAxis tick={{ fill: "var(--chart-tick)", fontSize: 10 }} axisLine={false} tickLine={false} />
            <ReferenceLine y={avg} stroke="var(--chart-tick)" strokeDasharray="4 4" />
            <Tooltip cursor={{ fill: "rgba(127,127,127,0.08)" }} content={tip} />
            <Bar dataKey="value" radius={[2, 2, 0, 0]}>
              {data.map(x => <Cell key={x.i} fill={x.value >= avg ? color : `${color}66`} />)}
            </Bar>
          </BarChart>
        )}
      </ResponsiveContainer>
      {d.best_game && (
        <p className="mt-2 text-xs text-gray-500">
          Best game: <span className="font-bold text-gray-900 dark:text-white">{d.best_game.value} {d.best_game.label}</span>{" "}
          {d.best_game.at_vs} {d.best_game.opp}, {fmtDate(d.best_game.date, true)}
          {d.chart.kind === "bar" && <span className="text-gray-400"> · dashed line = season average ({avg.toFixed(1)})</span>}
        </p>
      )}
    </div>
  );
}

function SeasonLinesCard({ d }: { d: PlayerData }) {
  if (!d.season_lines.rows.length) return null;
  return (
    <div className={card}>
      <p className={`${cardTitle} mb-2`}>Season &amp; career</p>
      <StatTable first="" labels={d.season_lines.labels}
        rows={d.season_lines.rows.map(r => ({ key: r.label, head: r.label, stats: r.stats, bold: r.label === "Regular Season" }))} />
    </div>
  );
}

function SplitsCard({ d }: { d: PlayerData }) {
  if (!d.splits.tables.length) return null;
  return (
    <div className={`${card} h-full`}>
      <p className={`${cardTitle} mb-2`}>Splits</p>
      <div className="flex flex-col gap-3">
        {d.splits.tables.map(t => (
          <StatTable key={t.title} first={t.title} labels={d.splits.labels}
            rows={t.rows.map(r => ({ key: r.label, head: r.label, stats: r.stats }))} />
        ))}
      </div>
    </div>
  );
}

function NewsCard({ d }: { d: PlayerData }) {
  if (!d.note && !d.news.length && !d.awards.length) return null;
  return (
    <div className={`${card} h-full flex flex-col gap-4`}>
      {d.note && (
        <div>
          <p className={`${cardTitle} mb-1.5`}>Latest note</p>
          <p className="text-sm font-semibold text-gray-900 dark:text-white">{d.note.headline}</p>
          {d.note.story && <p className="mt-1 text-xs text-gray-500 leading-relaxed">{d.note.story}</p>}
        </div>
      )}
      {d.awards.length > 0 && (
        <div>
          <p className={`${cardTitle} mb-1.5`}>Awards</p>
          <div className="flex flex-wrap gap-1.5">
            {d.awards.map(a => (
              <span key={a.name} title={a.seasons.join(", ")} className="text-[11px] rounded-full px-2.5 py-1 bg-amber-50 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300">
                {a.count} {a.name}
              </span>
            ))}
          </div>
        </div>
      )}
      {d.news.length > 0 && (
        <div>
          <p className={`${cardTitle} mb-1.5`}>News</p>
          <ul className="flex flex-col gap-1.5">
            {d.news.map(n => (
              <li key={n.headline} className="text-xs">
                {n.url
                  ? <a href={n.url} target="_blank" rel="noopener noreferrer" className="text-gray-800 dark:text-gray-200 hover:underline">{n.headline}</a>
                  : <span className="text-gray-800 dark:text-gray-200">{n.headline}</span>}
                {n.published && <span className="text-gray-400"> · {fmtDate(n.published)}</span>}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function GameLogCard({ d }: { d: PlayerData }) {
  const [showAll, setShowAll] = useState(false);
  const games = d.game_log.games;
  if (!games.length) return null;
  const shown = showAll ? games : games.slice(0, 10);
  return (
    <div className={card}>
      <div className="flex items-baseline justify-between mb-2">
        <p className={cardTitle}>Game log · {d.game_log.title}</p>
        {games.length > 10 && (
          <button onClick={() => setShowAll(v => !v)} className="text-[11px] font-semibold text-gray-500 hover:text-gray-800 dark:hover:text-gray-200">
            {showAll ? "Show fewer" : `Show all ${games.length}`}
          </button>
        )}
      </div>
      <StatTable first="Game" labels={d.game_log.labels}
        rows={shown.map(g => {
          const head = (
            <span className="inline-flex items-center gap-1.5">
              <span className="text-gray-400 w-12">{fmtDate(g.date)}</span>
              <span className="text-gray-400">{g.at_vs}</span>
              {g.opponent_logo && <img src={g.opponent_logo} alt="" className="w-4 h-4 object-contain" />}
              <span>{g.opponent_abbr}</span>
              {g.result && (
                <span className={`ml-1 text-[10px] font-bold ${g.result === "W" ? "text-green-600 dark:text-green-400" : g.result === "L" ? "text-red-500" : "text-gray-400"}`}>
                  {g.result} {g.score}
                </span>
              )}
            </span>
          );
          const href = d.league === "nfl" ? `/nfl/game/${g.game_id}` : null;
          return { key: g.game_id, head: href ? <Link href={href} className="hover:underline">{head}</Link> : head, stats: g.stats };
        })} />
    </div>
  );
}

function CareerCard({ d }: { d: PlayerData }) {
  const c = d.career;
  if (!c || !c.rows.length) return null;
  const rows = [...c.rows].reverse().map((r, i) => ({ key: `${r.season}-${i}`, head: <span>{r.season} <span className="text-gray-400">{r.team}</span></span>, stats: r.stats }));
  if (c.totals) rows.push({ key: "totals", head: <span>Career</span>, stats: c.totals, bold: true } as typeof rows[number] & { bold: boolean });
  return (
    <div className={card}>
      <p className={`${cardTitle} mb-2`}>{c.title || "Career"} by season</p>
      <StatTable first="Season" labels={c.labels} rows={rows} />
    </div>
  );
}

// ── Page ───────────────────────────────────────────────────────────────────────

export default function PlayerPage({ league, id }: { league: League; id: string }) {
  const [data, setData] = useState<PlayerData | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    let active = true;
    setData(null); setError(false);
    fetch(`${API}/api/player/${league}/${encodeURIComponent(id)}`)
      .then(r => { if (!r.ok) throw new Error(String(r.status)); return r.json(); })
      .then((d: PlayerData) => { if (active) setData(d); })
      .catch(() => { if (active) setError(true); });
    return () => { active = false; };
  }, [league, id]);

  const back = data?.team ? teamHref(league, data.team.name) : `/${league === "nba" ? "" : league}`;

  return (
    <main className="px-4 lg:px-8 pt-4 lg:pt-5 pb-8 flex flex-col gap-3">
      <Link href={back} className="inline-flex items-center gap-1.5 text-xs text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 transition-colors">
        <svg width="13" height="13" viewBox="0 0 13 13" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
          <path d="M8 2L3 6.5l5 4.5" />
        </svg>
        {data?.team ? data.team.name : "Back"}
      </Link>

      {!data && !error && <div className={`${card} text-center text-xs text-gray-400`}>Loading player…</div>}
      {error && <div className={`${card} text-center text-xs text-gray-400`}>Could not load this player.</div>}

      {data && (
        <>
          <Hero d={data} />
          <div className="grid grid-cols-1 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)] gap-3 items-stretch">
            <TrendCard d={data} />
            <FormCard d={data} />
          </div>
          <SeasonLinesCard d={data} />
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-3 items-stretch">
            <SplitsCard d={data} />
            <NewsCard d={data} />
          </div>
          <GameLogCard d={data} />
          <CareerCard d={data} />
        </>
      )}
    </main>
  );
}
