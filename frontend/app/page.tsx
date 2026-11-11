"use client";
// Home page: every sport's games today. Your teams first, then live games, the most confident
// picks, value picks, upcoming and finished games. Each card opens the sport's game page.
import { useEffect, useState } from "react";
import Link from "next/link";
import { FavoriteStar, favoriteKey, useFavorites, type League } from "./components/favorites";
import { useWakeHint, WAKE_HINT } from "./components/useWakeHint";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface Side { name: string; abbr: string; logo: string | null; score: number | null }

interface TodayGame {
  sport: League;
  game_id: string;
  href: string;
  state: "pre" | "in" | "post";
  start_utc: string;
  status_text: string;
  away: Side;
  home: Side;
  away_prob: number | null;
  home_prob: number | null;
  live_away_prob: number | null;
  predicted_winner: string | null;
  away_odds: number | null;
  home_odds: number | null;
  value_side: "away" | "home" | null;
  value_edge: number | null;
}

const SPORT_LABEL: Record<League, string> = { nba: "NBA", nfl: "NFL", nhl: "NHL", mlb: "MLB" };
const SPORT_ORDER: League[] = ["nba", "nfl", "nhl", "mlb"];

function startTime(iso: string): string {
  try {
    return `${new Date(iso).toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit", timeZone: "America/New_York" })} ET`;
  } catch { return ""; }
}

function longDate(d: string): string {
  try {
    const [y, m, day] = d.split("-").map(Number);
    return new Date(y, m - 1, day).toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric" });
  } catch { return d; }
}

/** Our favourite's probability, and which side it is */
function pick(g: TodayGame): { side: "away" | "home"; prob: number } | null {
  if (g.away_prob == null || g.home_prob == null) return null;
  return g.away_prob >= g.home_prob ? { side: "away", prob: g.away_prob } : { side: "home", prob: g.home_prob };
}

// ── Pieces ─────────────────────────────────────────────────────────────────────

function Logo({ side, size = "w-7 h-7" }: { side: Side; size?: string }) {
  return side.logo
    // eslint-disable-next-line @next/next/no-img-element
    ? <img src={side.logo} alt="" className={`${size} object-contain flex-shrink-0`} />
    : <div className={`${size} rounded-full bg-gray-200 dark:bg-gray-700 flex-shrink-0`} />;
}

function SportTag({ sport }: { sport: League }) {
  return <span className="text-[10px] font-bold tracking-widest text-gray-400 uppercase">{SPORT_LABEL[sport]}</span>;
}

function GameCard({ g, favorites }: { g: TodayGame; favorites: string[] }) {
  const live = g.state === "in", done = g.state === "post";
  const p = pick(g);
  const awayLive = live && g.live_away_prob != null ? g.live_away_prob : null;
  const shown = (s: "away" | "home") => {
    if (awayLive != null) return s === "away" ? awayLive : Math.round((100 - awayLive) * 10) / 10;
    return s === "away" ? g.away_prob : g.home_prob;
  };
  const winner = done && g.away.score != null && g.home.score != null
    ? (g.away.score > g.home.score ? "away" : "home") : null;
  const fav = (s: Side) => favorites.includes(favoriteKey(g.sport, s.name));

  const row = (s: "away" | "home") => {
    const side = g[s];
    const prob = shown(s);
    const leads = awayLive != null ? (s === "away" ? awayLive >= 50 : awayLive < 50) : p?.side === s;
    return (
      <div className="flex items-center gap-2.5">
        <Logo side={side} />
        <span className={`text-sm font-bold ${winner && winner !== s ? "text-gray-400" : "text-gray-900 dark:text-white"}`}>{side.abbr}</span>
        <span className="text-xs text-gray-400 truncate hidden sm:inline">{side.name}</span>
        <FavoriteStar league={g.sport} team={side.name} size={13} className={fav(side) ? "" : "opacity-0 group-hover:opacity-100 focus:opacity-100"} />
        <span className="flex-1" />
        {prob != null && !done && (
          <span className={`text-xs font-bold tabular-nums ${leads ? "text-green-600 dark:text-green-400" : "text-gray-400"}`}>{prob}%</span>
        )}
        {(live || done) && side.score != null && (
          <span className={`w-8 text-right text-base font-black tabular-nums ${winner === s || live ? "text-gray-900 dark:text-white" : "text-gray-400"}`}>{side.score}</span>
        )}
      </div>
    );
  };

  const pickedRight = done && winner && p ? p.side === winner : null;
  return (
    <Link href={g.href} className="group block">
      <div className={`bg-white dark:bg-gray-900 border shadow-sm rounded-2xl px-4 py-3 h-full flex flex-col gap-2 transition-colors group-hover:bg-gray-50 dark:group-hover:bg-gray-800 ${
        fav(g.away) || fav(g.home) ? "border-yellow-400/60" : "border-gray-100 dark:border-transparent"}`}>
        <div className="flex items-center justify-between">
          <SportTag sport={g.sport} />
          {live ? (
            <span className="flex items-center gap-1.5 text-[11px] font-bold text-red-400">
              <span className="w-1.5 h-1.5 rounded-full bg-red-500 animate-pulse" />{g.status_text || "Live"}
            </span>
          ) : (
            <span className="text-[11px] text-gray-400">{done ? (g.status_text || "Final") : startTime(g.start_utc)}</span>
          )}
        </div>
        {row("away")}
        {row("home")}
        {p && g.predicted_winner && (
          <div className="mt-auto pt-1 text-[11px] flex items-center justify-between gap-2">
            {done ? (
              <span className={pickedRight ? "text-green-600 dark:text-green-400" : "text-red-500"}>
                Our pick: {g[p.side].abbr} {pickedRight ? "✓" : "✗"}
              </span>
            ) : (
              <span className="text-gray-400">Pick: <span className="text-green-600 dark:text-green-400 font-semibold">{g[p.side].abbr} {p.prob}%</span>
                {live && " pre-game"}</span>
            )}
            {!done && !live && g.value_side && (
              <span className="text-[10px] font-semibold px-1.5 py-0.5 rounded-full bg-yellow-100 dark:bg-yellow-500/15 text-yellow-700 dark:text-yellow-400">
                Value: {g[g.value_side].abbr}
              </span>
            )}
          </div>
        )}
      </div>
    </Link>
  );
}

function Section({ title, children, extra }: { title: React.ReactNode; children: React.ReactNode; extra?: React.ReactNode }) {
  return (
    <section className="mb-7">
      <div className="flex items-baseline justify-between mb-3">
        <h2 className="text-xs font-semibold text-gray-400 uppercase tracking-widest flex items-center gap-2">{title}</h2>
        {extra}
      </div>
      {children}
    </section>
  );
}

const grid = "grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3";

function PickList({ items, empty }: { items: { g: TodayGame; side: "away" | "home"; right: React.ReactNode }[]; empty: string }) {
  return (
    <div className="bg-white dark:bg-gray-900 border border-gray-100 dark:border-transparent shadow-sm rounded-2xl p-2">
      {items.length === 0 ? (
        <p className="text-xs text-gray-400 text-center py-4">{empty}</p>
      ) : items.map(({ g, side, right }) => {
        const other = side === "home" ? "away" : "home";
        return (
          <Link key={g.sport + g.game_id} href={g.href}
            className="flex items-center gap-3 px-3 py-2.5 rounded-xl hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors">
            <span className="w-9"><SportTag sport={g.sport} /></span>
            <Logo side={g[side]} size="w-6 h-6" />
            <span className="text-sm text-gray-800 dark:text-gray-200 font-medium truncate">
              {g[side].name}
              <span className="text-gray-400 font-normal"> {side === "home" ? "vs" : "@"} {g[other].abbr}</span>
            </span>
            <span className="flex-1" />
            <span className="text-[11px] text-gray-400 hidden sm:inline whitespace-nowrap">{startTime(g.start_utc)}</span>
            {right}
          </Link>
        );
      })}
    </div>
  );
}

// ── Our record (dashboard) ──────────────────────────────────────────────────────

interface Tally { correct: number; n: number }
interface DayRecord extends Tally { date: string; by_sport: Partial<Record<League, Tally>> }
interface SportRecord extends Tally {
  sport: League; accuracy: number; in_season: boolean;
  sure: Tally;   // picks at sure_pick% or more
}
interface Brief {
  sport: League; game_id: string; pick: string; prob: number; correct: boolean;
  away_team: string; home_team: string; away_score: number | null; home_score: number | null;
}
interface HomeSummary {
  today: string; days: DayRecord[]; sure_pick: number; sports: SportRecord[];
  yesterday: Tally & { date: string; by_sport: Partial<Record<League, Tally>>; best: Brief[]; misses: Brief[] };
}

function briefHref(b: Brief): string {
  const q = new URLSearchParams({ away: b.away_team, home: b.home_team, status: "Final" }).toString();
  return b.sport === "nhl" ? `/nhl/game/${b.game_id}` : b.sport === "nba" ? `/game/${b.game_id}?${q}` : `/${b.sport}/game/${b.game_id}?${q}`;
}

/** Yesterday in a few lines: the record by sport, our surest hits and our biggest misses. */
function YesterdayCard({ y, sport }: { y: HomeSummary["yesterday"]; sport: League | "all" }) {
  const keep = (b: Brief) => sport === "all" || b.sport === sport;
  const best = y.best.filter(keep).slice(0, 1), misses = y.misses.filter(keep).slice(0, 2);
  const line = (b: Brief) => {
    const pickHome = b.pick === b.home_team;
    const opp = pickHome ? b.away_team : b.home_team;
    const [ps, os] = pickHome ? [b.home_score, b.away_score] : [b.away_score, b.home_score];
    const nick = (n: string) => n.split(" ").slice(-1)[0];
    return (
      <Link key={b.sport + b.game_id} href={briefHref(b)}
        className="flex items-center gap-3 px-2 py-2 -mx-2 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors">
        <span className={`w-5 text-center font-bold ${b.correct ? "text-green-600 dark:text-green-400" : "text-gray-400"}`}>{b.correct ? "✓" : "✗"}</span>
        <span className="w-9"><SportTag sport={b.sport} /></span>
        <span className="text-sm text-gray-700 dark:text-gray-300 min-w-0 truncate">
          <b className="text-gray-900 dark:text-white">{nick(b.pick)} {b.prob}%</b>
          {" · "}{b.correct ? "beat" : "lost to"} {nick(opp)}{ps != null && os != null ? ` ${ps}-${os}` : ""}
        </span>
        <span className="flex-1" />
        <span className="text-[10px] text-gray-400 uppercase tracking-wide whitespace-nowrap hidden sm:inline">{b.correct ? "Surest hit" : "Biggest miss"}</span>
      </Link>
    );
  };
  const sports = (Object.entries(y.by_sport) as [League, Tally][]).filter(([s]) => sport === "all" || s === sport);
  return (
    <div className="bg-white dark:bg-gray-900 border border-gray-100 dark:border-transparent shadow-sm rounded-2xl p-5">
      <div className="flex flex-wrap items-baseline justify-between gap-2 mb-2">
        <h2 className="text-xs font-semibold text-gray-400 uppercase tracking-widest">Yesterday · {dayLabel(y.date, true)}</h2>
        <div className="flex gap-3 text-[11px] text-gray-500">
          {sports.map(([s, r]) => <span key={s}>{SPORT_LABEL[s]} <b className="text-gray-800 dark:text-gray-200 tabular-nums">{r.correct}/{r.n}</b></span>)}
        </div>
      </div>
      {best.length + misses.length === 0
        ? <p className="text-xs text-gray-400 py-2">No games yesterday.</p>
        : <div className="flex flex-col">{[...best, ...misses].map(line)}</div>}
    </div>
  );
}

const pct = (t: Tally) => (t.n ? `${Math.round((t.correct / t.n) * 100)}%` : "—");
const add = (a: Tally, b: Tally): Tally => ({ correct: a.correct + b.correct, n: a.n + b.n });
const NONE: Tally = { correct: 0, n: 0 };

function StatTile({ label, value, sub }: { label: string; value: React.ReactNode; sub?: React.ReactNode }) {
  return (
    <div className="bg-white dark:bg-gray-900 border border-gray-100 dark:border-transparent shadow-sm rounded-2xl px-4 py-3.5 min-w-0">
      <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-widest">{label}</p>
      <p className="text-xl sm:text-2xl font-black text-gray-900 dark:text-white tabular-nums mt-1 leading-tight">{value}</p>
      {sub && <p className="text-[11px] text-gray-400 mt-0.5 truncate">{sub}</p>}
    </div>
  );
}

function dayLabel(d: string, long = false) {
  const [y, m, day] = d.split("-").map(Number);
  return new Date(y, m - 1, day).toLocaleDateString("en-US", long ? { weekday: "short", month: "short", day: "numeric" } : { day: "numeric" });
}

/** Picks per day: right (green) under wrong (gray), one column per day; hover for the numbers. */
function RecordChart({ rows, sport, sports }: { rows: (Tally & { date: string })[]; sport: League | "all"; sports: SportRecord[] }) {
  const [hover, setHover] = useState<number | null>(null);
  const max = Math.max(1, ...rows.map(r => r.n));
  const total = rows.reduce(add, NONE);
  const h = hover != null ? rows[hover] : null;
  return (
    <div className="bg-white dark:bg-gray-900 border border-gray-100 dark:border-transparent shadow-sm rounded-2xl p-5 h-full flex flex-col">
      <div className="flex items-start justify-between gap-3 mb-4">
        <div>
          <h2 className="text-xs font-semibold text-gray-400 uppercase tracking-widest">Our picks, last {rows.length} days</h2>
          <p className="text-sm text-gray-700 dark:text-gray-300 mt-1">
            <b className="text-gray-900 dark:text-white">{total.correct}</b> of {total.n} right · <b className="text-gray-900 dark:text-white">{pct(total)}</b>
          </p>
        </div>
        <div className="flex items-center gap-3 text-[11px] text-gray-500 flex-shrink-0">
          <span className="flex items-center gap-1.5"><span className="w-2.5 h-2.5 rounded-sm bg-green-600 dark:bg-green-500" />Right</span>
          <span className="flex items-center gap-1.5"><span className="w-2.5 h-2.5 rounded-sm bg-gray-300 dark:bg-gray-600" />Wrong</span>
        </div>
      </div>
      <div className="relative flex-1 min-h-[150px] flex flex-col justify-end">
        {h && (
          <div className="absolute top-0 left-1/2 -translate-x-1/2 z-10 bg-gray-900 dark:bg-gray-800 text-white text-[11px] rounded-lg px-2.5 py-1.5 whitespace-nowrap shadow-lg pointer-events-none">
            {dayLabel(h.date, true)} · {h.n ? <><b>{h.correct}/{h.n}</b> right ({pct(h)})</> : "no games"}
          </div>
        )}
        <div className="flex items-end gap-1 sm:gap-1.5 border-b border-gray-100 dark:border-gray-800" style={{ height: 132 }}>
          {rows.map((r, i) => {
            const wrong = r.n - r.correct;
            return (
              <div key={r.date} className="flex-1 h-full flex flex-col justify-end"
                onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}
                aria-label={`${dayLabel(r.date, true)}: ${r.correct} of ${r.n} right`}>
                <div className={`flex flex-col justify-end gap-[2px] transition-opacity ${hover != null && hover !== i ? "opacity-50" : ""}`}
                  style={{ height: `${(r.n / max) * 100}%` }}>
                  {wrong > 0 && <div className="bg-gray-300 dark:bg-gray-600 rounded-t" style={{ flexGrow: wrong }} />}
                  {r.correct > 0 && <div className={`bg-green-600 dark:bg-green-500 ${wrong ? "" : "rounded-t"}`} style={{ flexGrow: r.correct }} />}
                </div>
              </div>
            );
          })}
        </div>
        <div className="flex gap-1 sm:gap-1.5 mt-1.5">
          {rows.map((r, i) => (
            <span key={r.date} className={`flex-1 text-center text-[9px] sm:text-[10px] tabular-nums ${i === rows.length - 1 ? "text-gray-700 dark:text-gray-300 font-semibold" : "text-gray-400"}`}>
              <span className={(rows.length - 1 - i) % 2 ? "hidden sm:inline" : ""}>{dayLabel(r.date)}</span>
            </span>
          ))}
        </div>
      </div>
      {sport === "all" && (
        <div className="flex flex-wrap gap-2 mt-4">
          {sports.filter(s => s.in_season).map(s => (
            <Link key={s.sport} href={`/${s.sport}/performance`}
              className="text-[11px] px-2.5 py-1 rounded-full bg-gray-50 dark:bg-gray-800 text-gray-500 hover:text-gray-800 dark:hover:text-gray-200 transition-colors">
              {SPORT_LABEL[s.sport]} this season <b className="text-gray-800 dark:text-gray-200 tabular-nums">{s.accuracy}%</b>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Page ───────────────────────────────────────────────────────────────────────

export default function TodayPage() {
  const [games, setGames] = useState<TodayGame[]>([]);
  const [date, setDate] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [sport, setSport] = useState<League | "all">("all");
  const [summary, setSummary] = useState<HomeSummary | null>(null);
  const favorites = useFavorites();
  const waking = useWakeHint(loading);
  const anyLive = games.some(g => g.state === "in");

  useEffect(() => {
    fetch(`${API}/api/today_all`)
      .then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); })
      .then(d => { setGames(d.games ?? []); setDate(d.date ?? ""); })
      .catch(e => setError(`Could not load today's games. Is the backend running? (${e.message})`))
      .finally(() => setLoading(false));
    fetch(`${API}/api/home_summary`).then(r => (r.ok ? r.json() : null)).then(d => { if (d) setSummary(d); }).catch(() => {});
  }, []);

  // Live scores and probabilities refresh every 30 s while a game is on
  useEffect(() => {
    if (!anyLive) return;
    const id = setInterval(() => {
      fetch(`${API}/api/today_all`).then(r => (r.ok ? r.json() : null)).then(d => { if (d) setGames(d.games ?? []); }).catch(() => {});
    }, 30_000);
    return () => clearInterval(id);
  }, [anyLive]);

  const sports = SPORT_ORDER.filter(s => games.some(g => g.sport === s));
  const shown = games.filter(g => sport === "all" || g.sport === sport);
  const isFav = (g: TodayGame) => favorites.includes(favoriteKey(g.sport, g.away.name)) || favorites.includes(favoriteKey(g.sport, g.home.name));
  const yours = shown.filter(isFav);
  const others = shown.filter(g => !isFav(g));
  const liveGames = others.filter(g => g.state === "in");
  const upcoming = others.filter(g => g.state === "pre");
  const finished = others.filter(g => g.state === "post");
  const best = shown.filter(g => g.state === "pre" && pick(g))
    .sort((a, b) => pick(b)!.prob - pick(a)!.prob).slice(0, 5);
  const value = shown.filter(g => g.state === "pre" && g.value_side && g.value_edge != null)
    .sort((a, b) => (b.value_edge ?? 0) - (a.value_edge ?? 0));
  const order = (g: TodayGame) => (g.state === "in" ? 0 : g.state === "pre" ? 1 : 2);
  // Our record for the selected sport (all: every sport)
  const days = (summary?.days ?? []).map(d => ({ date: d.date, ...(sport === "all" ? d : d.by_sport[sport] ?? NONE) }));
  const yday = summary ? days.find(d => d.date === summary.yesterday.date) ?? NONE : null;
  const counted = summary?.sports.filter(s => (sport === "all" ? s.in_season : s.sport === sport));
  const season = counted?.reduce(add, NONE);
  const sure = counted?.map(s => s.sure).reduce(add, NONE);

  return (
    <main className="px-4 md:px-6 py-6 md:py-8">
      <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Today</h1>
          <p className="text-gray-500 text-sm mt-1">{date ? longDate(date) : "Every sport's games"} · click a game for details · ☆ a team to pin it here</p>
        </div>
        {sports.length > 1 && (
          <div className="flex gap-1 bg-gray-100 dark:bg-gray-900 rounded-xl p-1">
            {(["all", ...sports] as const).map(s => (
              <button key={s} onClick={() => setSport(s)}
                className={`px-3 py-1 rounded-lg text-xs font-semibold transition-colors ${sport === s
                  ? "bg-white dark:bg-gray-800 text-gray-900 dark:text-white shadow-sm" : "text-gray-500 hover:text-gray-800 dark:hover:text-gray-200"}`}>
                {s === "all" ? "All" : SPORT_LABEL[s]}
              </button>
            ))}
          </div>
        )}
      </div>

      {error && <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800/40 rounded-xl p-4 text-red-600 dark:text-red-400 text-sm mb-6">{error}</div>}
      {!error && loading && (
        <div className="bg-white dark:bg-gray-900 border border-gray-100 dark:border-transparent shadow-sm rounded-2xl p-8 text-center text-gray-400 text-sm">
          Loading…{waking && <p className="mt-1 text-xs">{WAKE_HINT}</p>}
        </div>
      )}
      {!error && !loading && games.length === 0 && (
        <div className="bg-white dark:bg-gray-900 border border-gray-100 dark:border-transparent shadow-sm rounded-2xl p-8 text-center text-gray-400 text-sm">
          No games today in any sport.
        </div>
      )}

      {!error && !loading && (
        <>
          <div className="grid grid-cols-2 sm:grid-cols-3 xl:grid-cols-5 gap-3 mb-5">
            <StatTile label="Games today" value={shown.length}
              sub={`${shown.filter(g => g.state === "in").length} live · ${shown.filter(g => g.state === "pre").length} to come`} />
            <StatTile label="Yesterday" value={yday ? (yday.n ? `${yday.correct}/${yday.n}` : "—") : "…"}
              sub={yday ? (yday.n ? `${pct(yday)} of our picks right` : "no games") : ""} />
            <StatTile label={`Last ${days.length || 14} days`} value={summary ? pct(days.reduce(add, NONE)) : "…"} sub="of our picks right" />
            <StatTile label="This season" value={season ? pct(season) : "…"}
              sub={season ? `${season.correct.toLocaleString()} of ${season.n.toLocaleString()} picks` : ""} />
            <StatTile label={`Picks at ${summary?.sure_pick ?? 70}%+`} value={sure ? pct(sure) : "…"}
              sub={sure ? `${sure.correct} of ${sure.n} right this season` : ""} />
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-3 gap-5 mb-7">
            <div className="lg:col-span-2 flex flex-col gap-5">
              {summary ? <RecordChart rows={days} sport={sport} sports={summary.sports} />
                : <div className="bg-white dark:bg-gray-900 rounded-2xl p-8 text-center text-gray-400 text-sm h-full">Loading our record…</div>}
              {summary && <YesterdayCard y={summary.yesterday} sport={sport} />}
            </div>
            <div className="flex flex-col">
              <Section title="Most confident picks">
                <PickList empty="No games left to pick today."
                  items={best.map(g => ({ g, side: pick(g)!.side, right: <span className="text-sm font-bold text-green-600 dark:text-green-400 tabular-nums w-12 text-right">{pick(g)!.prob}%</span> }))} />
              </Section>
              <Section title="Value picks" extra={<span className="text-[10px] text-gray-400">our % vs the betting market</span>}>
                <PickList empty="No value picks right now."
                  items={value.map(g => ({ g, side: g.value_side!, right: (
                    <span className="text-[11px] font-semibold text-yellow-700 dark:text-yellow-400 whitespace-nowrap tabular-nums">
                      {g.value_side === "away" ? `x${g.away_odds}` : `x${g.home_odds}`} · +{g.value_edge}%
                    </span>) }))} />
              </Section>
            </div>
          </div>
        </>
      )}

      {yours.length > 0 && (
        <Section title={<><span className="text-yellow-400">★</span> Your teams</>}>
          <div className={grid}>{[...yours].sort((a, b) => order(a) - order(b)).map(g => <GameCard key={g.sport + g.game_id} g={g} favorites={favorites} />)}</div>
        </Section>
      )}

      {liveGames.length > 0 && (
        <Section title={<><span className="w-1.5 h-1.5 rounded-full bg-red-500 animate-pulse" /> Live now</>}>
          <div className={grid}>{liveGames.map(g => <GameCard key={g.sport + g.game_id} g={g} favorites={favorites} />)}</div>
        </Section>
      )}

      {upcoming.length > 0 && (
        <Section title={`Upcoming · ${upcoming.length}`}>
          <div className={grid}>{upcoming.map(g => <GameCard key={g.sport + g.game_id} g={g} favorites={favorites} />)}</div>
        </Section>
      )}

      {finished.length > 0 && (
        <Section title={`Completed · ${finished.length}`}>
          <div className={grid}>{finished.map(g => <GameCard key={g.sport + g.game_id} g={g} favorites={favorites} />)}</div>
        </Section>
      )}
    </main>
  );
}
