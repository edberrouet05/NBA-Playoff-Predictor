"use client";
import { useEffect, useState } from "react";
import { CalibrationChart, ProbabilityQuality, type CalibrationBin, type VegasComparison } from "../../components/ModelQuality";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// ── Types ──────────────────────────────────────────────────────────────────────

interface NFLModelStats {
  accuracy:     number;
  cv_std:       number;
  cv_folds:     number[];
  n_rows:       number;
  seasons:      number[];
  features:     string[];
  coefficients: number[];
  log_loss:     number | null;
  brier:        number | null;
  calibration:  CalibrationBin[];
  vegas:        VegasComparison | null;
}

// ── Feature labels ─────────────────────────────────────────────────────────────

const FEATURE_LABELS: Record<string, { label: string; group: string; desc: string }> = {
  elo_diff: { label: "Elo Rating Gap", group: "Team strength", desc: "Gap between the two teams' Elo ratings. Elo updates after every game (bigger wins move it more) and carries over between seasons with a 1/3 pull toward average, so it's meaningful from week 1." },
  net_epa_diff: { label: "Net EPA/Play Gap", group: "Team strength", desc: "Offensive EPA per play minus defensive EPA per play allowed, compared between the two teams. EPA (expected points added) measures how much each play improves scoring chances — a steadier signal of quality than the final score. Weighted toward recent games." },
  qb_epa_diff: { label: "Starting QB Gap", group: "Quarterback", desc: "Gap in EPA per dropback between the two starting quarterbacks, based on each QB's own history (weighted toward recent games, shrunk toward backup level for QBs with little history). Uses the projected starter, so injuries and benchings are reflected." },
  qb_changed: { label: "QB Change", group: "Quarterback", desc: "Whether this team is starting a different quarterback than in its previous game — usually an injury or a benching." },
  opp_qb_changed: { label: "Opp QB Change", group: "Quarterback", desc: "Whether the opponent is starting a different quarterback than in its previous game." },
  home: { label: "Home Advantage", group: "Context", desc: "Whether the team is playing at home (neutral-site games like London count as neither). NFL home teams win roughly 55% of games." },
  rest_diff: { label: "Rest Gap", group: "Context", desc: "Difference in days of rest between the two teams, e.g. a team coming off a Thursday game vs one that played Monday." },
  off_bye: { label: "Coming Off Bye", group: "Context", desc: "Whether this team had its bye week before this game (13+ days of rest)." },
  opp_off_bye: { label: "Opp Coming Off Bye", group: "Context", desc: "Whether the opponent had its bye week before this game." },
  travel_diff_1000km: { label: "Travel Gap", group: "Context", desc: "Difference between the two teams' travel distance from their home stadium to the venue, in thousands of km." },
};

const GROUP_COLORS: Record<string, string> = {
  "Team strength": "bg-blue-500",
  Quarterback:     "bg-orange-500",
  Context:         "bg-green-500",
};

const GROUP_TEXT: Record<string, string> = {
  "Team strength": "text-blue-600 dark:text-blue-400 bg-blue-50 dark:bg-blue-500/10",
  Quarterback:     "text-orange-600 dark:text-orange-400 bg-orange-50 dark:bg-orange-500/10",
  Context:         "text-green-600 dark:text-green-400 bg-green-50 dark:bg-green-500/10",
};

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

function FoldBars({ folds, avg, seasons }: { folds: number[]; avg: number; seasons: number[] }) {
  if (!folds.length) return null;
  const max = Math.max(...folds);
  const min = Math.min(...folds);
  const range = max - min || 1;
  const height = (v: number) => 40 + ((v - min) / range) * 60;

  return (
    <div className="bg-white dark:bg-gray-900 border border-gray-100 dark:border-transparent shadow-sm rounded-2xl p-6">
      <div className="flex items-start justify-between mb-5 gap-6">
        <div>
          <h2 className="text-xs font-bold text-gray-400 uppercase tracking-widest mb-1">Accuracy by season</h2>
          <p className="text-xs text-gray-400 leading-relaxed">
            Each bar shows how accurate the model was on one season when trained only on the other seasons.
          </p>
        </div>
        <span className="text-xs text-gray-400 flex-shrink-0">avg <span className="font-bold text-gray-700 dark:text-gray-200">{avg.toFixed(2)}%</span></span>
      </div>

      <div className="flex gap-3 mb-1">
        {folds.map((acc, i) => (
          <div key={i} className="flex-1 text-center">
            <span className={`text-[11px] font-bold ${acc === max ? "text-red-500" : "text-gray-500 dark:text-gray-400"}`}>
              {acc.toFixed(1)}%
            </span>
          </div>
        ))}
      </div>

      <div className="flex items-end gap-3" style={{ height: 64 }}>
        {folds.map((acc, i) => (
          <div key={i} className="flex-1 rounded-t-md"
            style={{ height: `${height(acc)}%`, background: acc === max ? "#ef4444" : "#e5e7eb" }} />
        ))}
      </div>

      <div className="flex gap-3 mt-1.5">
        {folds.map((_, i) => (
          <div key={i} className="flex-1 text-center" title={`Held-out season ${seasons[i] ?? i + 1}`}>
            <span className="text-[10px] text-gray-400">{seasons.length === folds.length ? `'${String(seasons[i]).slice(2)}` : `Fold ${i + 1}`}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Page ───────────────────────────────────────────────────────────────────────

export default function NFLStatsPage() {
  const [data,    setData]    = useState<NFLModelStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error,   setError]   = useState("");

  useEffect(() => {
    fetch(`${API}/api/nfl/stats`)
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

      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Model Stats</h1>
        <p className="text-gray-500 text-sm mt-1">
          How well the NFL prediction model performs · trained on {data.seasons.join(", ")} seasons
        </p>
      </div>

      <div className="grid grid-cols-3 gap-4 mb-5">
        <Metric label="Prediction Accuracy" value={`${data.accuracy}%`} sub="on games it hadn't seen" />
        <Metric label="Games analyzed" value={Math.round(data.n_rows / 2).toLocaleString()} sub={`across ${data.seasons.length} seasons`} />
        <Metric label="Features tracked" value={String(data.features.length)} sub="per team per game" />
      </div>

      {data.cv_folds.length > 0 && (
        <div className="mb-5">
          <FoldBars folds={data.cv_folds} avg={data.accuracy} seasons={data.seasons} />
        </div>
      )}

      <div className="grid md:grid-cols-2 gap-5 mb-5">
        <CalibrationChart bins={data.calibration ?? []} />
        <ProbabilityQuality logLoss={data.log_loss} brier={data.brier} vegas={data.vegas} />
      </div>

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

      <div className="bg-white dark:bg-gray-900 border border-gray-100 dark:border-transparent shadow-sm rounded-2xl p-6">
        <h2 className="text-xs font-bold text-gray-400 uppercase tracking-widest mb-4">About the Model</h2>
        <ul className="text-sm text-gray-600 dark:text-gray-400 space-y-2">
          <li className="flex gap-2"><span className="text-gray-300 dark:text-gray-600">—</span> Logistic Regression with L2 regularization + StandardScaler</li>
          <li className="flex gap-2"><span className="text-gray-300 dark:text-gray-600">—</span> Trained on {data.seasons[0]}–{data.seasons[data.seasons.length - 1]} regular-season and playoff games (2 rows per game)</li>
          <li className="flex gap-2"><span className="text-gray-300 dark:text-gray-600">—</span> Leave-one-season-out cross-validation, balanced class weights</li>
          <li className="flex gap-2"><span className="text-gray-300 dark:text-gray-600">—</span> {data.features.length} features: Elo, EPA efficiency, starting QB, home field, rest / bye, travel</li>
          <li className="flex gap-2"><span className="text-gray-300 dark:text-gray-600">—</span> Play-by-play data from nflverse; projected starting QBs refreshed hourly</li>
          <li className="flex gap-2"><span className="text-gray-300 dark:text-gray-600">—</span> Probability normalized head-to-head: away prob / (away + home prob)</li>
        </ul>
      </div>

    </main>
  );
}
