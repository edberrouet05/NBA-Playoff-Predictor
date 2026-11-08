"use client";
import { use, useEffect, useState } from "react";
import Link from "next/link";
import { playerHref, teamHref } from "../../../components/teamLinks";
import { nhlColor, nhlLogo, nhlNick } from "../../nhlTeams";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// ── Types (mirror /api/nhl/game/{id}) ─────────────────────────────────────────

interface Side { name: string; abbr: string; score: number | null; record: string | null; logo: string | null; color: string }
interface Factor { feature: string; label: string; impact: number }
interface Goalie { id: string; name: string; side: "home" | "away"; saves: string; shots_against: string; save_pct: string; toi: string; headshot: string | null }
interface Skater { id: string; name: string; side: string; position: string; goals: number; assists: number; shots: number; plus_minus: string; toi: string; headshot: string | null }
interface Goal { period: string; clock: string; side: "home" | "away" | ""; text: string; strength: string; away_score: number; home_score: number }
interface Form { record: string; points: number; goal_diff: number; streak: number; elo: number; gf: number; ga: number; shot_share: number; sv_pct: number }
interface NHLGameDetail {
  game_id: string; start_utc: string; state: "pre" | "in" | "post"; status: string; detail: string;
  period: number; clock: string; venue: string; home: Side; away: Side;
  home_win_prob: number | null; away_win_prob: number | null; predicted_winner: string | null;
  live_home_prob: number | null; live_away_prob: number | null;
  lines: { home?: number[]; away?: number[] };
  stats: { key: string; label: string; away: string; home: string }[];
  goalies: Goalie[]; skaters: { home: Skater[]; away: Skater[] }; goals: Goal[];
  stars: { label: string; id: string; name: string; headshot: string | null }[];
  explanation: Factor[];
  form: { home: Form | null; away: Form | null };
}

const card = "bg-white dark:bg-gray-900 border border-gray-100 dark:border-transparent shadow-sm rounded-2xl";
const cardTitle = "text-[10px] font-semibold text-gray-500 uppercase tracking-widest";

function Logo({ side, size }: { side: Side; size: string }) {
  // Remember which URL failed, so another team gets a fresh attempt
  const [failedSrc, setFailedSrc] = useState<string | null>(null);
  const url = side.logo ?? nhlLogo(side.name);
  if (failedSrc === url) {
    return <div className={`${size} rounded-full flex-shrink-0`} style={{ background: nhlColor(side.name) }} />;
  }
  // eslint-disable-next-line @next/next/no-img-element
  return <img src={url} alt={side.name} className={`${size} object-contain flex-shrink-0`} onError={() => setFailedSrc(url)} />;
}

function Headshot({ src, color }: { src: string | null; color: string }) {
  const [failedSrc, setFailedSrc] = useState<string | null>(null);
  if (!src || failedSrc === src) {
    return <div className="w-9 h-9 rounded-full flex-shrink-0 bg-gray-100 dark:bg-gray-800" style={{ border: `2px solid ${color}` }} />;
  }
  // eslint-disable-next-line @next/next/no-img-element
  return <img src={src} alt="" className="w-9 h-9 rounded-full flex-shrink-0 object-cover bg-gray-100 dark:bg-gray-800"
    style={{ border: `2px solid ${color}` }} onError={() => setFailedSrc(src)} />;
}

// ── Header: teams, score, probabilities ───────────────────────────────────────

function Scoreboard({ g }: { g: NHLGameDetail }) {
  const live = g.state === "in", final = g.state === "post", showScore = live || final;
  const awayProb = live && g.live_away_prob != null ? g.live_away_prob : g.away_win_prob;
  const homeProb = live && g.live_home_prob != null ? g.live_home_prob : g.home_win_prob;
  const homeWon = final && (g.home.score ?? 0) > (g.away.score ?? 0);
  const awayWon = final && (g.away.score ?? 0) > (g.home.score ?? 0);
  const label = final ? g.detail : live ? g.detail
    : new Date(g.start_utc).toLocaleString("en-US", { weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });

  function team(s: Side, won: boolean, align: "left" | "right") {
    return (
      <Link href={teamHref("nhl", s.name)} className={`flex items-center gap-3 ${align === "right" ? "flex-row-reverse text-right" : ""}`}>
        <Logo side={s} size="w-14 h-14" />
        <div>
          <p className={`text-lg font-bold ${final && !won ? "text-gray-500" : "text-gray-900 dark:text-white"}`}>{nhlNick(s.name)}</p>
          {showScore ? (
            <p className={`text-3xl font-black tabular-nums ${final && !won ? "text-gray-400" : "text-gray-900 dark:text-white"}`}>{s.score}</p>
          ) : s.record && <p className="text-xs text-gray-400">{s.record}</p>}
        </div>
      </Link>
    );
  }

  return (
    <div className={`${card} p-5`}>
      <div className="flex items-center justify-between mb-4">
        <span className={`${cardTitle} flex items-center gap-1.5`}>
          {live && <span className="w-1.5 h-1.5 rounded-full bg-red-500 animate-pulse inline-block" />}
          {label}
        </span>
        <span className="text-xs text-gray-400">{g.venue}</span>
      </div>
      <div className="grid grid-cols-[1fr_auto_1fr] items-center gap-4">
        {team(g.away, awayWon, "left")}
        <div className="text-center">
          <p className="text-[10px] text-gray-400 uppercase tracking-widest mb-1">{live ? "Live win prob" : final ? "Pre-game" : "Win prob"}</p>
          {awayProb != null ? (
            <p className="text-xl font-black tabular-nums">
              <span style={{ color: (awayProb ?? 0) >= 50 ? "#16a34a" : undefined }} className={(awayProb ?? 0) < 50 ? "text-gray-500" : ""}>{awayProb}%</span>
              <span className="text-gray-400 mx-1.5">·</span>
              <span style={{ color: (homeProb ?? 0) > 50 ? "#16a34a" : undefined }} className={(homeProb ?? 0) <= 50 ? "text-gray-500" : ""}>{homeProb}%</span>
            </p>
          ) : <p className="text-gray-400">—</p>}
          {live && g.away_win_prob != null && (
            <p className="text-[11px] text-gray-400 mt-1">Pre-game {g.away_win_prob}% · {g.home_win_prob}%</p>
          )}
        </div>
        {team(g.home, homeWon, "right")}
      </div>
      {awayProb != null && (
        <div className="mt-4 h-1.5 flex rounded-full overflow-hidden">
          <div style={{ width: `${awayProb}%`, background: nhlColor(g.away.name) }} />
          <div className="flex-1" style={{ background: nhlColor(g.home.name) }} />
        </div>
      )}
    </div>
  );
}

function PeriodTable({ g }: { g: NHLGameDetail }) {
  const a = g.lines.away ?? [], h = g.lines.home ?? [];
  const n = Math.max(3, a.length, h.length);
  if (!a.length && !h.length) return null;
  const head = Array.from({ length: n }, (_, i) => (i < 3 ? String(i + 1) : i === 3 ? "OT" : "SO"));
  return (
    <div className={`${card} p-5 overflow-x-auto`}>
      <p className={`${cardTitle} mb-3`}>Score by period</p>
      <table className="w-full text-sm">
        <thead>
          <tr className="text-xs text-gray-400">
            <th className="text-left font-semibold pb-2" />
            {head.map(x => <th key={x} className="font-semibold pb-2 w-12 text-center">{x}</th>)}
            <th className="font-semibold pb-2 w-14 text-center">T</th>
          </tr>
        </thead>
        <tbody>
          {([["away", a], ["home", h]] as const).map(([k, row]) => (
            <tr key={k} className="border-t border-gray-100 dark:border-gray-800">
              <td className="py-2 font-bold text-gray-800 dark:text-gray-200">{g[k].abbr}</td>
              {head.map((_, i) => <td key={i} className="text-center tabular-nums text-gray-600 dark:text-gray-400">{row[i] ?? "–"}</td>)}
              <td className="text-center font-bold tabular-nums text-gray-900 dark:text-white">{g[k].score ?? "–"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function TeamStats({ g }: { g: NHLGameDetail }) {
  if (!g.stats.length) return null;
  const num = (v: string) => parseFloat(v) || 0;
  return (
    <div className={`${card} p-5`}>
      <p className={`${cardTitle} mb-3`}>Team stats</p>
      <div className="flex flex-col gap-2.5">
        {g.stats.map(s => {
          const a = num(s.away), h = num(s.home), total = a + h || 1;
          // Fewer is better for giveaways and penalty minutes
          const lowerBetter = s.key === "giveaways" || s.key === "penaltyMinutes";
          const awayBetter = lowerBetter ? a < h : a > h, homeBetter = lowerBetter ? h < a : h > a;
          return (
            <div key={s.key}>
              <div className="flex justify-between text-xs mb-1">
                <span className={`tabular-nums font-bold ${awayBetter ? "text-gray-900 dark:text-white" : "text-gray-400"}`}>{s.away}</span>
                <span className="text-gray-500">{s.label}</span>
                <span className={`tabular-nums font-bold ${homeBetter ? "text-gray-900 dark:text-white" : "text-gray-400"}`}>{s.home}</span>
              </div>
              <div className="h-1 flex rounded-full overflow-hidden bg-gray-100 dark:bg-gray-800">
                <div style={{ width: `${(a / total) * 100}%`, background: nhlColor(g.away.name) }} />
                <div className="flex-1" style={{ background: nhlColor(g.home.name) }} />
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function WhyPanel({ g }: { g: NHLGameDetail }) {
  const factors = g.explanation.filter(f => Math.abs(f.impact) >= 0.005);
  if (!factors.length) return null;
  const max = Math.max(...factors.map(f => Math.abs(f.impact)));
  return (
    <div className={`${card} p-5`}>
      <p className={`${cardTitle} mb-1`}>Why the model leans this way</p>
      <p className="text-xs text-gray-400 mb-4">Each bar is how far a factor pushes the pre-game pick toward one team.</p>
      <div className="flex justify-between text-[11px] font-semibold text-gray-500 mb-2">
        <span>← favours {g.away.abbr}</span><span>favours {g.home.abbr} →</span>
      </div>
      <div className="flex flex-col gap-3">
        {factors.map(f => {
          const w = (Math.abs(f.impact) / max) * 50;
          const toHome = f.impact > 0;
          return (
            <div key={f.feature}>
              <p className="text-[11px] text-center text-gray-600 dark:text-gray-300 font-medium mb-1">{f.label}</p>
              <div className="relative h-1.5 bg-gray-100 dark:bg-gray-800 rounded-full">
                <div className="absolute top-0 h-full rounded-full"
                  style={{ left: toHome ? "50%" : `${50 - w}%`, width: `${w}%`, background: nhlColor(toHome ? g.home.name : g.away.name) }} />
                <div className="absolute left-1/2 top-[-2px] h-[10px] w-px bg-gray-300 dark:bg-gray-600" />
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function FormCard({ g }: { g: NHLGameDetail }) {
  const a = g.form.away, h = g.form.home;
  if (!a || !h) return null;
  const rows: [string, string, string][] = [
    ["Record (W-L-OTL)", a.record, h.record],
    ["Points", String(a.points), String(h.points)],
    ["Goal differential", (a.goal_diff > 0 ? "+" : "") + a.goal_diff, (h.goal_diff > 0 ? "+" : "") + h.goal_diff],
    ["Goals for / game*", a.gf.toFixed(2), h.gf.toFixed(2)],
    ["Goals against / game*", a.ga.toFixed(2), h.ga.toFixed(2)],
    ["Shot share*", `${(a.shot_share * 100).toFixed(1)}%`, `${(h.shot_share * 100).toFixed(1)}%`],
    ["Save %*", a.sv_pct.toFixed(3).replace(/^0/, ""), h.sv_pct.toFixed(3).replace(/^0/, "")],
    ["Streak", a.streak > 0 ? `W${a.streak}` : `L${-a.streak}`, h.streak > 0 ? `W${h.streak}` : `L${-h.streak}`],
  ];
  return (
    <div className={`${card} p-5`}>
      <p className={`${cardTitle} mb-3`}>Season so far</p>
      <div className="grid grid-cols-[1fr_auto_1fr] text-xs gap-y-2">
        <span className="font-bold text-gray-800 dark:text-gray-200">{g.away.abbr}</span><span />
        <span className="font-bold text-gray-800 dark:text-gray-200 text-right">{g.home.abbr}</span>
        {rows.map(([label, av, hv]) => (
          <div key={label} className="contents">
            <span className="tabular-nums text-gray-700 dark:text-gray-300">{av}</span>
            <span className="text-gray-400 text-center px-2">{label}</span>
            <span className="tabular-nums text-gray-700 dark:text-gray-300 text-right">{hv}</span>
          </div>
        ))}
      </div>
      <p className="text-[10px] text-gray-400 mt-3">* recent games weigh more, carried over from last season</p>
    </div>
  );
}

function GoalsCard({ g }: { g: NHLGameDetail }) {
  if (!g.goals.length) return null;
  return (
    <div className={`${card} p-5`}>
      <p className={`${cardTitle} mb-3`}>Scoring summary</p>
      <div className="flex flex-col divide-y divide-gray-100 dark:divide-gray-800">
        {g.goals.map((x, i) => {
          const s = x.side === "home" ? g.home : g.away;
          return (
            <div key={i} className="flex items-center gap-3 py-2">
              <Logo side={s} size="w-6 h-6" />
              <div className="min-w-0 flex-1">
                <p className="text-xs text-gray-800 dark:text-gray-200 truncate">{x.text}</p>
                <p className="text-[10px] text-gray-400">{x.period} · {x.clock}{x.strength && x.strength !== "Even Strength" ? ` · ${x.strength}` : ""}</p>
              </div>
              <span className="text-xs font-bold tabular-nums text-gray-700 dark:text-gray-300 flex-shrink-0">{x.away_score}-{x.home_score}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function PlayersCard({ g }: { g: NHLGameDetail }) {
  const hasPlayers = g.goalies.length || g.skaters.home.length || g.skaters.away.length;
  if (!hasPlayers) return null;
  return (
    <div className={`${card} p-5`}>
      <p className={`${cardTitle} mb-3`}>Players</p>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-5">
        {(["away", "home"] as const).map(k => {
          const color = nhlColor(g[k].name);
          return (
            <div key={k}>
              <p className="text-xs font-bold text-gray-800 dark:text-gray-200 mb-2">{nhlNick(g[k].name)}</p>
              {g.goalies.filter(x => x.side === k).map(x => (
                <Link key={x.id} href={playerHref("nhl", x.id)} className="flex items-center gap-2.5 py-1.5 hover:opacity-80">
                  <Headshot src={x.headshot} color={color} />
                  <div className="min-w-0">
                    <p className="text-xs font-semibold text-gray-800 dark:text-gray-200 truncate">{x.name} <span className="text-gray-400 font-normal">· G</span></p>
                    <p className="text-[11px] text-gray-500">{x.saves}/{x.shots_against} saves · {x.save_pct} · {x.toi}</p>
                  </div>
                </Link>
              ))}
              {g.skaters[k].map(x => (
                <Link key={x.id} href={playerHref("nhl", x.id)} className="flex items-center gap-2.5 py-1.5 hover:opacity-80">
                  <Headshot src={x.headshot} color={color} />
                  <div className="min-w-0">
                    <p className="text-xs font-semibold text-gray-800 dark:text-gray-200 truncate">{x.name} <span className="text-gray-400 font-normal">· {x.position}</span></p>
                    <p className="text-[11px] text-gray-500">{x.goals} G · {x.assists} A · {x.shots} S · {x.plus_minus} · {x.toi}</p>
                  </div>
                </Link>
              ))}
            </div>
          );
        })}
      </div>
      {g.stars.length > 0 && (
        <div className="mt-4 pt-3 border-t border-gray-100 dark:border-gray-800 flex flex-wrap gap-x-5 gap-y-2">
          {g.stars.map(s => (
            <Link key={s.label} href={playerHref("nhl", s.id)} className="text-xs text-gray-600 dark:text-gray-300 hover:underline">
              <span className="text-yellow-500">★</span> {s.label.replace(" Star", "")}: <b>{s.name}</b>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Page ───────────────────────────────────────────────────────────────────────

export default function NHLGamePage({ params }: { params: Promise<{ game_id: string }> }) {
  const { game_id } = use(params);
  // Stored with the game it answers, so another game never shows a stale result
  const [result, setResult] = useState<{ id: string; data: NHLGameDetail | null; error: string } | null>(null);
  const g = result?.id === game_id ? result.data : null;
  const error = result?.id === game_id ? result.error : "";
  const live = g?.state === "in";

  useEffect(() => {
    let active = true;
    const load = () =>
      fetch(`${API}/api/nhl/game/${game_id}`)
        .then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); })
        .then(d => { if (active) setResult({ id: game_id, data: d, error: "" }); })
        .catch(e => { if (active) setResult(prev => prev?.id === game_id && prev.data ? prev : { id: game_id, data: null, error: e.message }); });
    load();
    return () => { active = false; };
  }, [game_id]);

  // Refresh every 30 s while the game is on
  useEffect(() => {
    if (!live) return;
    const id = setInterval(() => {
      fetch(`${API}/api/nhl/game/${game_id}`)
        .then(r => (r.ok ? r.json() : null))
        .then(d => { if (d) setResult({ id: game_id, data: d, error: "" }); })
        .catch(() => {});
    }, 30_000);
    return () => clearInterval(id);
  }, [live, game_id]);

  return (
    <main className="px-4 lg:px-8 pt-4 lg:pt-5 pb-8 flex flex-col gap-3">
      <Link href="/nhl" className="text-sm text-gray-500 hover:text-gray-800 dark:hover:text-gray-200 flex items-center gap-1 w-fit">
        <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M10 4l-4 4 4 4" /></svg>
        Games
      </Link>
      {!g && !error && <div className={`${card} p-8 text-center text-gray-400 text-sm`}>Loading…</div>}
      {!g && error && <div className={`${card} p-8 text-center text-gray-400 text-sm`}>Could not load this game ({error}).</div>}
      {g && (
        <>
          <Scoreboard g={g} />
          <PeriodTable g={g} />
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-3 items-start">
            <WhyPanel g={g} />
            {g.state === "pre" ? <FormCard g={g} /> : <TeamStats g={g} />}
          </div>
          {g.state !== "pre" && (
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-3 items-start">
              <div className="flex flex-col gap-3">
                <GoalsCard g={g} />
                <FormCard g={g} />
              </div>
              <PlayersCard g={g} />
            </div>
          )}
        </>
      )}
    </main>
  );
}
