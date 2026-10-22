"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { LineChart, Line, XAxis, YAxis, CartesianGrid, ResponsiveContainer, Tooltip, ReferenceLine } from "recharts";
import { CalibrationChart, ProbabilityQuality, type CalibrationBin, type Scores } from "./ModelQuality";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const MIN_CALIBRATION_GAMES = 30;

// Season record page shared by the NBA, NFL and MLB ("Record" in each sidebar)

export type Sport = "nba" | "nfl" | "mlb";
const SPORT: Record<Sport, { start: string; predictions: string; stats: string; frozenNote: string }> = {
  nba: { start: "tip-off", predictions: "/predictions", stats: "/stats",
         frozenNote: "the one written down before tip-off when we have it (injury report included)" },
  nfl: { start: "kickoff", predictions: "/nfl/predictions", stats: "/nfl/stats",
         frozenNote: "the one written down before kickoff when we have it (injury report included)" },
  mlb: { start: "first pitch", predictions: "/mlb/predictions", stats: "/mlb/stats",
         frozenNote: "the one served before first pitch when we have it" },
};

// ── Types (mirror /api/{sport}/performance) ────────────────────────────────────

interface ConfBucket { lo: number; hi: number; n: number; correct: number; accuracy: number; avg_prob: number; }
interface Day { date: string; games: number; correct: number; cum_accuracy: number; }
interface Market {
  n_games: number; model: Scores; vegas: Scores;
  value_bets: { n: number; won: number; units: number; roi: number | null };
}
interface Performance {
  sport: Sport; season: string; n_games: number; frozen: number | null; excluded: number;
  expected_accuracy: number | null; correct: number;
  accuracy: number | null; log_loss: number | null; brier: number | null;
  by_confidence: ConfBucket[]; calibration: CalibrationBin[]; by_day: Day[]; market: Market | null;
}

// ── Cards ──────────────────────────────────────────────────────────────────────

const card = "bg-white dark:bg-gray-900 border border-gray-100 dark:border-transparent shadow-sm rounded-2xl p-5";
const cardTitle = "text-[10px] font-semibold text-gray-500 uppercase tracking-widest";

function Metric({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className={`${card} text-center`}>
      <p className="text-xs text-gray-400 font-semibold uppercase tracking-widest mb-2">{label}</p>
      <p className="text-2xl font-bold text-gray-900 dark:text-white">{value}</p>
      {sub && <p className="text-xs text-gray-400 mt-1">{sub}</p>}
    </div>
  );
}

function ConfidenceCard({ buckets }: { buckets: ConfBucket[] }) {
  return (
    <div className={card}>
      <p className={`${cardTitle} mb-1`}>By confidence</p>
      <p className="text-xs text-gray-400 mb-4">How often the pick won, by how sure the model was. A well-calibrated model wins its 70% picks about 70% of the time.</p>
      <div className="flex flex-col gap-3">
        {buckets.map(b => {
          const acc = b.accuracy * 100, exp = b.avg_prob * 100;
          return (
            <div key={b.lo}>
              <div className="flex items-baseline justify-between text-xs mb-1">
                <span className="font-semibold text-gray-700 dark:text-gray-300">{b.lo}–{b.hi}% picks</span>
                <span className="tabular-nums text-gray-500">
                  <span className={`font-bold ${acc >= exp ? "text-green-600 dark:text-green-400" : "text-red-500"}`}>{acc.toFixed(0)}%</span>
                  {" "}won · {b.correct}/{b.n} · expected {exp.toFixed(0)}%
                </span>
              </div>
              <div className="relative h-2 bg-gray-100 dark:bg-gray-800 rounded-full">
                <div className="absolute inset-y-0 left-0 rounded-full bg-blue-500" style={{ width: `${acc}%` }} />
                <div className="absolute -top-0.5 -bottom-0.5 w-0.5 bg-gray-900 dark:bg-white" style={{ left: `${exp}%` }} title="Expected" />
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function TrendCard({ days, expected }: { days: Day[]; expected: number | null }) {
  const data = days.map(d => ({ ...d, pct: Math.round(d.cum_accuracy * 1000) / 10 }));
  return (
    <div className={card}>
      <div className="flex items-baseline justify-between mb-2">
        <p className={cardTitle}>Season accuracy, day by day</p>
        {expected != null && <p className="text-[11px] text-gray-400">dashed: cross-validated {expected}%</p>}
      </div>
      <ResponsiveContainer width="100%" height={180}>
        <LineChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
          <CartesianGrid strokeDasharray="2 5" stroke="var(--chart-grid)" vertical={false} />
          <XAxis dataKey="date" tickFormatter={d => d.slice(5).replace("-", "/")} tick={{ fill: "var(--chart-tick)", fontSize: 10 }} axisLine={false} tickLine={false} />
          <YAxis domain={[0, 100]} ticks={[0, 25, 50, 75, 100]} tickFormatter={v => `${v}%`} width={40}
            tick={{ fill: "var(--chart-tick)", fontSize: 10 }} axisLine={false} tickLine={false} />
          {expected != null && <ReferenceLine y={expected} stroke="var(--chart-tick)" strokeDasharray="4 4" />}
          <Tooltip
            contentStyle={{ background: "var(--tooltip-bg)", border: "1px solid var(--tooltip-border)", borderRadius: 8, fontSize: 11, color: "var(--tooltip-text)" }}
            formatter={(v: unknown, _n, item) => {
              const d = (item as { payload?: Day }).payload;
              return [`${v}% · ${d?.correct}/${d?.games} that day`, "Season"];
            }}
          />
          <Line type="linear" dataKey="pct" stroke="#3b82f6" strokeWidth={2} dot={{ r: 2 }} isAnimationActive={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

function ValueBetsCard({ m }: { m: Market }) {
  const vb = m.value_bets;
  return (
    <div className={card}>
      <p className={`${cardTitle} mb-1`}>Value bets</p>
      <p className="text-xs text-gray-400 mb-3">Games where our probability beat the bookmaker&apos;s (margin removed) by 5+ points, betting 1 unit at the pre-game odds.</p>
      {vb.n === 0 ? <p className="text-sm text-gray-400">None yet.</p> : (
        <div className="grid grid-cols-3 gap-2 text-center">
          <div><p className="text-xl font-black text-gray-900 dark:text-white">{vb.won}/{vb.n}</p><p className="text-[10px] text-gray-400 uppercase">won</p></div>
          <div><p className={`text-xl font-black ${vb.units >= 0 ? "text-green-600 dark:text-green-400" : "text-red-500"}`}>{vb.units > 0 ? "+" : ""}{vb.units}</p><p className="text-[10px] text-gray-400 uppercase">units</p></div>
          <div><p className={`text-xl font-black ${(vb.roi ?? 0) >= 0 ? "text-green-600 dark:text-green-400" : "text-red-500"}`}>{vb.roi != null ? `${(vb.roi * 100).toFixed(1)}%` : "—"}</p><p className="text-[10px] text-gray-400 uppercase">return / bet</p></div>
        </div>
      )}
    </div>
  );
}

// ── Page ───────────────────────────────────────────────────────────────────────

export default function PerformancePage({ sport }: { sport: Sport }) {
  const meta = SPORT[sport];
  const [data, setData] = useState<Performance | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    fetch(`${API}/api/${sport}/performance`)
      .then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); })
      .then(setData)
      .catch(e => setError(`Could not load the season record. (${e.message})`));
  }, [sport]);

  const expected = data?.expected_accuracy ?? null;

  return (
    <main className="px-4 md:px-6 py-6 md:py-8">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Performance {data?.season ?? ""}</h1>
        <p className="text-gray-500 text-sm mt-1">How our pre-game picks have done this season, on games that hadn&apos;t been played yet.</p>
      </div>

      {error && <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800/40 rounded-xl p-4 text-red-600 dark:text-red-400 text-sm">{error}</div>}
      {!data && !error && <div className={`${card} text-center text-sm text-gray-400`}>Loading…</div>}

      {data && data.n_games === 0 && <div className={`${card} text-center text-sm text-gray-400`}>No completed games yet this season.</div>}

      {data && data.n_games > 0 && (
        <div className="flex flex-col gap-5">
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            <Metric label="Accuracy" value={`${((data.accuracy ?? 0) * 100).toFixed(1)}%`} sub={expected != null ? `cross-validated: ${expected}%` : undefined} />
            <Metric label="Picks correct" value={`${data.correct} / ${data.n_games}`} sub="completed games this season" />
            {data.frozen != null
              ? <Metric label={`Frozen before ${meta.start}`} value={`${data.frozen} / ${data.n_games}`} sub="the rest rebuilt from pre-game data" />
              : <Metric label="Pre-game data" value={`${data.n_games}`} sub={data.excluded ? `${data.excluded} games left out (no pre-game data)` : "every game scored on its pre-game state"} />}
          </div>

          {data.n_games < 100 && expected != null && (
            <p className="text-xs text-amber-700 dark:text-amber-400 bg-amber-50 dark:bg-amber-500/10 rounded-xl px-4 py-3">
              Small sample: {data.n_games} games. Over a full season the model has been right about {expected.toFixed(0)}% of the
              time in testing — a few dozen games can easily land 10 points either side of that.
            </p>
          )}

          <div className="grid md:grid-cols-2 gap-5">
            <ConfidenceCard buckets={data.by_confidence} />
            {data.by_day.length > 1 ? <TrendCard days={data.by_day} expected={expected} /> : <div className={`${card} text-sm text-gray-400`}>The day-by-day chart appears after a second day of games.</div>}
          </div>

          <div className="grid md:grid-cols-2 gap-5">
            {data.n_games >= MIN_CALIBRATION_GAMES ? <CalibrationChart bins={data.calibration} /> : (
              <div className={`${card} text-sm text-gray-400`}>
                <p className={`${cardTitle} mb-2`}>Calibration</p>
                The calibration curve appears after {MIN_CALIBRATION_GAMES} games: with fewer, each point is one or two games and says nothing.
              </div>
            )}
            <ProbabilityQuality logLoss={data.log_loss} brier={data.brier}
              vegas={data.market ? { n_games: data.market.n_games, model: data.market.model, vegas: data.market.vegas } : null}
              market={{
                title: "Model vs the bookmakers", column: "Books",
                note: "games, pre-game lines with the bookmaker margin removed.",
                empty: "No pre-game betting lines stored yet for this season's games.",
              }} />
          </div>

          {data.market && <ValueBetsCard m={data.market} />}

          <p className="text-xs text-gray-500 dark:text-gray-400">
            Every pick is {meta.frozenNote}; otherwise the model on the pipeline&apos;s pre-game data, never on later
            information{data.excluded > 0 && <> — {data.excluded} games without pre-game data are left out</>}.{" "}
            <Link href={meta.predictions} className="underline">All predictions →</Link>
            {" · "}<Link href={meta.stats} className="underline">How the model was tested →</Link>
          </p>
        </div>
      )}
    </main>
  );
}
