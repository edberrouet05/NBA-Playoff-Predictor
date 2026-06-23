"use client";
import { useEffect, useState } from "react";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// ── Types ──────────────────────────────────────────────────────────────────────

interface MLBModelStats {
  accuracy:     number;
  cv_std:       number;
  cv_folds:     number[];
  n_rows:       number;
  seasons:      number[];
  features:     string[];
  coefficients: number[];
}

// ── Feature labels ─────────────────────────────────────────────────────────────

const FEATURE_LABELS: Record<string, { label: string; group: string; desc: string }> = {
  era:           { label: "ERA (team)",            group: "Pitching",      desc: "How many runs the pitchers give up per game on average. Lower = better pitching staff." },
  whip:          { label: "WHIP (team)",           group: "Pitching",      desc: "How many batters reach base per inning (hits + walks). Lower means pitchers are more dominant." },
  k_per9:        { label: "K/9",                   group: "Pitching",      desc: "Strikeouts per 9 innings. More strikeouts = pitchers who overpower hitters." },
  bb_per9:       { label: "BB/9",                  group: "Pitching",      desc: "Free walks given up per 9 innings. High number = pitchers losing control of the strike zone." },
  sp_era:        { label: "Starter ERA",           group: "Pitching",      desc: "Run average for starting pitchers only. Starters set the tone for the first 5–6 innings." },
  bullpen_era:   { label: "Bullpen ERA",           group: "Pitching",      desc: "Run average for relief pitchers. A bad bullpen can blow leads in the final innings." },
  batting_avg:   { label: "Batting Average",       group: "Hitting",       desc: "How often batters get a hit. .250 is league average; higher means a more consistent offense." },
  ops:           { label: "OPS",                   group: "Hitting",       desc: "Overall offensive strength — combines how often players get on base with how hard they hit. Higher is better." },
  obp:           { label: "On-Base %",             group: "Hitting",       desc: "How often batters reach base (hits, walks, etc.). More baserunners = more scoring opportunities." },
  slg:           { label: "Slugging %",            group: "Hitting",       desc: "Measures hitting power — extra-base hits count more. A team that hits home runs will have a high slugging %." },
  run_diff:      { label: "Run Differential",      group: "Hitting",       desc: "Runs scored minus runs allowed over the full season. The best overall measure of how good a team really is." },
  opp_era:       { label: "Opp ERA",               group: "Opponent",      desc: "How good the opposing team's pitchers are. Lower ERA = harder to score against them." },
  opp_whip:      { label: "Opp WHIP",              group: "Opponent",      desc: "How dominant the opponent's pitchers are at keeping runners off base." },
  opp_ops:       { label: "Opp OPS",               group: "Opponent",      desc: "How strong the opposing team's offense is overall. High OPS = dangerous lineup." },
  opp_run_diff:  { label: "Opp Run Diff",          group: "Opponent",      desc: "The opponent's runs scored vs. runs allowed balance. A high positive value = a well-rounded, dominant team." },
  opp_sp_era:    { label: "Opp Starter ERA",       group: "Opponent",      desc: "Quality of the opponent's starting pitcher. Used when we know who's starting that game." },
  era_diff:      { label: "ERA Differential",      group: "Differentials", desc: "This team's pitching ERA vs. the opponent's. Negative = this team has the pitching edge." },
  whip_diff:     { label: "WHIP Differential",     group: "Differentials", desc: "Gap in pitcher dominance between the two teams." },
  ops_diff:      { label: "OPS Differential",      group: "Differentials", desc: "Gap in offensive strength. Positive = this team hits better than the opponent." },
  run_diff_diff: { label: "Run Diff Differential", group: "Differentials", desc: "The model's top signal. Compares both teams' run differentials — the bigger the gap, the more one team has outplayed the other all season." },
  home:          { label: "Home Advantage",        group: "Context",       desc: "Whether the team is playing at home. Home teams win ~54% of MLB games due to crowd, familiarity, and no travel." },
  rest_days:     { label: "Rest Days",             group: "Context",       desc: "Days off since the last game. More rest helps pitchers recover, especially the bullpen." },
  win_pct_last10:{ label: "Win % Last 10",         group: "Context",       desc: "Win rate over the last 10 games. Captures whether a team is on a hot streak or struggling lately." },
  park_factor:   { label: "Park Factor",           group: "Context",       desc: "How much a stadium favors hitters or pitchers. Coors Field (Colorado) = 1.15 (easy to score), Petco Park (San Diego) = 0.93 (hard to score)." },
};

const GROUP_COLORS: Record<string, string> = {
  Pitching:     "bg-blue-500",
  Hitting:      "bg-orange-500",
  Opponent:     "bg-purple-500",
  Differentials:"bg-red-500",
  Context:      "bg-green-500",
};

const GROUP_TEXT: Record<string, string> = {
  Pitching:     "text-blue-600 dark:text-blue-400 bg-blue-50 dark:bg-blue-500/10",
  Hitting:      "text-orange-600 dark:text-orange-400 bg-orange-50 dark:bg-orange-500/10",
  Opponent:     "text-purple-600 dark:text-purple-400 bg-purple-50 dark:bg-purple-500/10",
  Differentials:"text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-500/10",
  Context:      "text-green-600 dark:text-green-400 bg-green-50 dark:bg-green-500/10",
};

// ── Metric card ────────────────────────────────────────────────────────────────

// ── Tooltip ────────────────────────────────────────────────────────────────────

function Tooltip({ text, children }: { text: string; children: React.ReactNode }) {
  return (
    <div className="relative group/tip inline-flex items-center">
      {children}
      <div className="
        pointer-events-none absolute bottom-full left-0 mb-2 z-50
        w-72 px-3 py-2.5 rounded-xl shadow-lg
        bg-gray-900 dark:bg-gray-800 text-white text-xs leading-relaxed
        opacity-0 group-hover/tip:opacity-100
        translate-y-1 group-hover/tip:translate-y-0
        transition-all duration-150
      ">
        {text}
        {/* Arrow */}
        <div className="absolute top-full left-4 -mt-px border-4 border-transparent border-t-gray-900 dark:border-t-gray-800" />
      </div>
    </div>
  );
}

// ── Metric card ────────────────────────────────────────────────────────────────

function Metric({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="bg-white dark:bg-gray-900 border border-gray-100 dark:border-transparent shadow-sm rounded-2xl p-5 text-center">
      <p className="text-xs text-gray-400 font-semibold uppercase tracking-widest mb-2">{label}</p>
      <p className="text-2xl font-bold text-gray-900 dark:text-white">{value}</p>
      {sub && <p className="text-xs text-gray-400 mt-1">{sub}</p>}
    </div>
  );
}

// ── CV fold bars ───────────────────────────────────────────────────────────────

function FoldBars({ folds, avg }: { folds: number[]; avg: number }) {
  if (!folds.length) return null;
  const max    = Math.max(...folds);
  const min    = Math.min(...folds);
  const range  = max - min || 1;
  // Scale so shortest bar = 40% height, tallest = 100%
  const height = (v: number) => 40 + ((v - min) / range) * 60;

  return (
    <div className="bg-white dark:bg-gray-900 border border-gray-100 dark:border-transparent shadow-sm rounded-2xl p-6">
      <div className="flex items-start justify-between mb-5 gap-6">
        <div>
          <h2 className="text-xs font-bold text-gray-400 uppercase tracking-widest mb-1">Accuracy by test group</h2>
          <p className="text-xs text-gray-400 leading-relaxed">
            The dataset was split into 5 groups. Each bar shows how accurate the model was when tested on games it had never seen from that group.
          </p>
        </div>
        <span className="text-xs text-gray-400 flex-shrink-0">avg <span className="font-bold text-gray-700 dark:text-gray-200">{avg.toFixed(2)}%</span></span>
      </div>

      {/* Values row */}
      <div className="flex gap-3 mb-1">
        {folds.map((acc, i) => (
          <div key={i} className="flex-1 text-center">
            <span className={`text-[11px] font-bold ${acc === max ? "text-red-500" : "text-gray-500 dark:text-gray-400"}`}>
              {acc.toFixed(1)}%
            </span>
          </div>
        ))}
      </div>

      {/* Bars */}
      <div className="flex items-end gap-3" style={{ height: 64 }}>
        {folds.map((acc, i) => (
          <div
            key={i}
            className="flex-1 rounded-t-md"
            style={{
              height: `${height(acc)}%`,
              background: acc === max ? "#ef4444" : "#e5e7eb",
            }}
          />
        ))}
      </div>

      {/* Labels row */}
      <div className="flex gap-3 mt-1.5">
        {folds.map((_, i) => (
          <div key={i} className="flex-1 text-center" title={`Test group ${i + 1}`}>
            <span className="text-[10px] text-gray-400">Fold {i + 1}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Page ───────────────────────────────────────────────────────────────────────

export default function MLBStatsPage() {
  const [data,    setData]    = useState<MLBModelStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error,   setError]   = useState("");

  useEffect(() => {
    fetch(`${API}/api/mlb/stats`)
      .then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); })
      .then(d => setData(d))
      .catch(e => setError(`Could not load model stats. (${e.message})`))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return (
    <main className="px-4 md:px-6 py-6 md:py-8">
      <div className="bg-white dark:bg-gray-900 border border-gray-100 dark:border-transparent shadow-sm rounded-2xl p-8 text-center text-gray-400 text-sm">
        Loading…
      </div>
    </main>
  );

  if (error || !data) return (
    <main className="px-4 md:px-6 py-6 md:py-8">
      <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800/40 rounded-xl p-4 text-red-600 dark:text-red-400 text-sm">
        {error || "No data."}
      </div>
    </main>
  );

  const ranked = data.features
    .map((f, i) => ({ feature: f, coef: data.coefficients[i] ?? 0 }))
    .sort((a, b) => Math.abs(b.coef) - Math.abs(a.coef));

  const maxAbs = Math.max(...ranked.map(x => Math.abs(x.coef)), 0.001);

  return (
    <main className="px-4 md:px-6 py-6 md:py-8">

      {/* Header */}
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Model Stats</h1>
        <p className="text-gray-500 text-sm mt-1">
          How well the MLB prediction model performs · trained on {data.seasons.join(", ")} seasons
        </p>
      </div>

      {/* Key metrics */}
      <div className="grid grid-cols-3 gap-4 mb-5">
        <Metric label="Prediction Accuracy" value={`${data.accuracy}%`}  sub="on games it hadn't seen" />
        <Metric label="Games analyzed"      value={data.n_rows.toLocaleString()} sub={`across ${data.seasons.length} seasons`} />
        <Metric label="Stats tracked"       value={String(data.features.length)} sub="per team per game" />
      </div>

      {/* Feature importance */}
      <div className="bg-white dark:bg-gray-900 border border-gray-100 dark:border-transparent shadow-sm rounded-2xl p-6 mb-5">
        <h2 className="text-xs font-bold text-gray-400 uppercase tracking-widest mb-5">
          Feature Importance — coefficient magnitude
        </h2>
        <div className="flex flex-col gap-3.5">
          {ranked.map(({ feature, coef }) => {
            const meta  = FEATURE_LABELS[feature];
            const label = meta?.label ?? feature;
            const group = meta?.group ?? "Other";
            const desc  = meta?.desc  ?? "";
            const bar   = GROUP_COLORS[group] ?? "bg-gray-400";
            const badge = GROUP_TEXT[group]   ?? "text-gray-500 bg-gray-100";
            const width = (Math.abs(coef) / maxAbs) * 100;
            const pos   = coef >= 0;
            return (
              <div key={feature}>
                <div className="flex items-center justify-between text-xs mb-1.5 gap-2">
                  <div className="flex items-center gap-2 min-w-0">
                    <Tooltip text={desc}>
                      <span className="text-gray-700 dark:text-gray-300 font-medium cursor-help underline decoration-dotted decoration-gray-400 underline-offset-2">
                        {label}
                      </span>
                    </Tooltip>
                    <span className={`text-[10px] px-1.5 py-0.5 rounded-md font-semibold flex-shrink-0 ${badge}`}>
                      {group}
                    </span>
                  </div>
                  <span className={`font-mono font-bold tabular-nums flex-shrink-0 ${
                    pos ? "text-red-600 dark:text-red-400" : "text-blue-500 dark:text-blue-400"
                  }`}>
                    {coef > 0 ? "+" : ""}{coef.toFixed(4)}
                  </span>
                </div>
                <div className="h-1.5 bg-gray-100 dark:bg-gray-800 rounded-full overflow-hidden">
                  <div className={`h-full rounded-full ${bar}`} style={{ width: `${width}%` }} />
                </div>
              </div>
            );
          })}
        </div>

        {/* Legend */}
        <div className="mt-5 pt-4 border-t border-gray-100 dark:border-gray-800 flex flex-wrap gap-3">
          {Object.entries(GROUP_TEXT).map(([group, cls]) => (
            <span key={group} className={`text-[10px] px-2 py-0.5 rounded-md font-semibold ${cls}`}>{group}</span>
          ))}
        </div>
        <p className="mt-3 text-xs text-gray-400">
          <span className="text-red-500 font-medium">+</span> increases win probability ·{" "}
          <span className="text-blue-500 font-medium">−</span> decreases win probability
        </p>
      </div>

      {/* About the model */}
      <div className="bg-white dark:bg-gray-900 border border-gray-100 dark:border-transparent shadow-sm rounded-2xl p-6">
        <h2 className="text-xs font-bold text-gray-400 uppercase tracking-widest mb-4">About the Model</h2>
        <ul className="text-sm text-gray-600 dark:text-gray-400 space-y-2">
          <li className="flex gap-2"><span className="text-gray-300 dark:text-gray-600">—</span> Logistic Regression with L2 regularization + StandardScaler</li>
          <li className="flex gap-2"><span className="text-gray-300 dark:text-gray-600">—</span> Trained on 2023–2025 regular-season games (2 rows per game)</li>
          <li className="flex gap-2"><span className="text-gray-300 dark:text-gray-600">—</span> Stratified 5-fold cross-validation, balanced class weights</li>
          <li className="flex gap-2"><span className="text-gray-300 dark:text-gray-600">—</span> {data.features.length} features: pitching splits, hitting, opponent stats, differentials, context</li>
          <li className="flex gap-2"><span className="text-gray-300 dark:text-gray-600">—</span> Game-day prediction: pitcher ERA overrides applied when starters are known</li>
          <li className="flex gap-2"><span className="text-gray-300 dark:text-gray-600">—</span> Probability normalized head-to-head: away prob / (away + home prob)</li>
        </ul>
      </div>

    </main>
  );
}
