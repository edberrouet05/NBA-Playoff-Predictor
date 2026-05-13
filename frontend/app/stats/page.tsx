"use client";
import { useEffect, useState } from "react";

const API = "http://localhost:8000";

interface ModelStats {
  accuracy: number;
  n_games: number;
  n_seasons: number;
  features: string[];
  coefficients: number[];
}

const LABELS: Record<string, string> = {
  off_rtg:      "Offensive Rating",
  def_rtg:      "Defensive Rating",
  net_rtg:      "Net Rating",
  pace:         "Pace",
  rest_days:    "Rest Days",
  ts_pct:       "True Shooting %",
  tov_pct:      "Turnover %",
  oreb_pct:     "Off. Rebound %",
  home:         "Home / Away",
  win_streak:   "Win Streak",
  srs:          "SRS",
  point_diff:   "Point Differential",
  fg3_rate:     "3PT Rate",
  ftr:          "Free Throw Rate",
  back_to_back:    "Back-to-Back",
  travel_km:       "Travel Distance (km)",
  prev_margin:     "Previous Game Margin",
  playoff_net_rtg: "Prev Season Playoff Net Rtg",
};

export default function StatsPage() {
  const [data,  setData]  = useState<ModelStats | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    fetch(`${API}/api/stats`)
      .then((r) => r.json())
      .then(setData)
      .catch(() => setError("Could not load model stats."));
  }, []);

  if (error) return (
    <main className="max-w-2xl mx-auto px-4 py-10">
      <p className="text-red-600 text-sm">{error}</p>
    </main>
  );
  if (!data) return (
    <main className="max-w-2xl mx-auto px-4 py-10">
      <div className="bg-white border border-gray-200 rounded-2xl p-8 text-center text-gray-400 text-sm shadow-sm">
        Loading…
      </div>
    </main>
  );

  const importance = data.features
    .map((f, i) => ({ feature: f, coef: data.coefficients[i] ?? 0 }))
    .sort((a, b) => Math.abs(b.coef) - Math.abs(a.coef));

  const maxAbs = Math.max(...importance.map((x) => Math.abs(x.coef)), 0.001);

  return (
    <main className="max-w-2xl mx-auto px-4 py-10">
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-gray-900">Model Dashboard</h1>
        <p className="text-gray-500 text-sm mt-1">
          Logistic regression · {data.n_seasons} seasons · {data.n_games.toLocaleString()} playoff games
        </p>
      </div>

      {/* Metric cards */}
      <div className="grid grid-cols-3 gap-4 mb-6">
        <Metric label="Accuracy"  value={`${data.accuracy}%`} />
        <Metric label="Games"     value={data.n_games.toLocaleString()} />
        <Metric label="Seasons"   value={String(data.n_seasons)} />
      </div>

      {/* Feature importance */}
      <div className="bg-white border border-gray-200 rounded-2xl p-6 shadow-sm mb-5">
        <h2 className="text-xs font-semibold text-gray-400 uppercase tracking-widest mb-5">
          Feature Importance
        </h2>
        <div className="flex flex-col gap-3.5">
          {importance.map(({ feature, coef }) => {
            const width   = (Math.abs(coef) / maxAbs) * 100;
            const pos     = coef >= 0;
            return (
              <div key={feature}>
                <div className="flex justify-between text-xs mb-1">
                  <span className="text-gray-600 font-medium">{LABELS[feature] ?? feature}</span>
                  <span className={`font-mono font-semibold tabular-nums ${pos ? "text-red-600" : "text-blue-500"}`}>
                    {coef > 0 ? "+" : ""}{coef.toFixed(3)}
                  </span>
                </div>
                <div className="h-2 bg-gray-100 rounded-full overflow-hidden">
                  <div
                    className={`h-full rounded-full transition-all duration-700 ${pos ? "bg-red-500" : "bg-blue-400"}`}
                    style={{ width: `${width}%` }}
                  />
                </div>
              </div>
            );
          })}
        </div>
        <p className="mt-5 text-xs text-gray-400 leading-relaxed">
          <span className="text-red-500 font-medium">Red</span> = higher value increases win probability.{" "}
          <span className="text-blue-500 font-medium">Blue</span> = higher value decreases win probability.
        </p>
      </div>

      {/* Model details */}
      <div className="bg-white border border-gray-200 rounded-2xl p-6 shadow-sm">
        <h2 className="text-xs font-semibold text-gray-400 uppercase tracking-widest mb-4">About the Model</h2>
        <ul className="text-sm text-gray-600 space-y-2">
          <li className="flex gap-2"><span className="text-gray-300">—</span> Logistic regression with L2 regularization + StandardScaler</li>
          <li className="flex gap-2"><span className="text-gray-300">—</span> Trained on individual playoff games (game-level, not series-level)</li>
          <li className="flex gap-2"><span className="text-gray-300">—</span> Stratified 5-fold cross-validation</li>
          <li className="flex gap-2"><span className="text-gray-300">—</span> Prediction: normalized head-to-head logistic scores</li>
          <li className="flex gap-2"><span className="text-gray-300">—</span> Series simulation: 10 000 Monte Carlo runs · 2-2-1-1-1 format</li>
          <li className="flex gap-2"><span className="text-gray-300">—</span> Contextual features computed live: back-to-back, travel distance</li>
        </ul>
      </div>
    </main>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="bg-white border border-gray-200 rounded-2xl p-5 shadow-sm text-center">
      <p className="text-xs text-gray-400 font-medium uppercase tracking-widest mb-2">{label}</p>
      <p className="text-2xl font-bold text-gray-900">{value}</p>
    </div>
  );
}
