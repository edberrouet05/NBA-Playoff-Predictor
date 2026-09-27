"use client";
import { useState } from "react";

// ── Types (mirror _model_stats_payload in api/main.py) ─────────────────────────

export interface CalibrationBin {
  lo: number;
  hi: number;
  predicted: number;
  actual: number;
  n: number;
}

export interface Scores {
  accuracy: number;
  log_loss: number;
  brier: number;
}

export interface VegasComparison {
  n_games: number;
  model: Scores;
  vegas: Scores;
}

// ── Calibration chart ──────────────────────────────────────────────────────────

const W = 320, H = 240, PAD_L = 36, PAD_B = 28, PAD_T = 8, PAD_R = 8;
const x = (v: number) => PAD_L + v * (W - PAD_L - PAD_R);
const y = (v: number) => PAD_T + (1 - v) * (H - PAD_T - PAD_B);
const ACCENT = "#ef4444"; // site accent (red-500)

export function CalibrationChart({ bins }: { bins: CalibrationBin[] }) {
  const [hover, setHover] = useState<number | null>(null);
  const [showTable, setShowTable] = useState(false);
  if (!bins.length) return null;
  const pts = bins.map(b => [x(b.predicted), y(b.actual)] as const);
  const h = hover !== null ? bins[hover] : null;

  return (
    <div className="bg-white dark:bg-gray-900 border border-gray-100 dark:border-transparent shadow-sm rounded-2xl p-6">
      <div className="flex items-start justify-between gap-4 mb-4">
        <div>
          <h2 className="text-xs font-bold text-gray-400 uppercase tracking-widest mb-1">Calibration</h2>
          <p className="text-xs text-gray-400 leading-relaxed">
            When the model says X%, does that team actually win X% of the time? Points on the dashed line = perfectly calibrated.
          </p>
        </div>
        <button onClick={() => setShowTable(s => !s)}
          className="text-[11px] text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 underline underline-offset-2 flex-shrink-0">
          {showTable ? "Chart" : "Table"}
        </button>
      </div>

      {showTable ? (
        <table className="w-full text-xs tabular-nums">
          <thead>
            <tr className="text-gray-400 text-left">
              <th className="font-semibold pb-2">Predicted range</th>
              <th className="font-semibold pb-2 text-right">Avg predicted</th>
              <th className="font-semibold pb-2 text-right">Actual win rate</th>
              <th className="font-semibold pb-2 text-right">Team-games</th>
            </tr>
          </thead>
          <tbody className="text-gray-700 dark:text-gray-300">
            {bins.map(b => (
              <tr key={b.lo} className="border-t border-gray-100 dark:border-gray-800">
                <td className="py-1.5">{Math.round(b.lo * 100)}–{Math.round(b.hi * 100)}%</td>
                <td className="py-1.5 text-right">{(b.predicted * 100).toFixed(1)}%</td>
                <td className="py-1.5 text-right">{(b.actual * 100).toFixed(1)}%</td>
                <td className="py-1.5 text-right">{b.n.toLocaleString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <div className="relative max-w-md mx-auto">
          <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-auto" role="img"
            aria-label="Calibration curve: predicted win probability versus actual win rate">
            {[0, 0.25, 0.5, 0.75, 1].map(t => (
              <g key={t}>
                <line x1={x(0)} x2={x(1)} y1={y(t)} y2={y(t)} className="stroke-gray-100 dark:stroke-gray-800" strokeWidth={1} />
                <text x={PAD_L - 6} y={y(t) + 3} textAnchor="end" className="fill-gray-400" fontSize={9}>{t * 100}%</text>
                <text x={x(t)} y={H - PAD_B + 14} textAnchor="middle" className="fill-gray-400" fontSize={9}>{t * 100}%</text>
              </g>
            ))}
            <text x={x(0.5)} y={H - 2} textAnchor="middle" className="fill-gray-400" fontSize={9}>Predicted win probability</text>
            <line x1={x(0)} y1={y(0)} x2={x(1)} y2={y(1)} className="stroke-gray-300 dark:stroke-gray-600" strokeWidth={1.5} strokeDasharray="4 4" />
            <polyline points={pts.map(p => p.join(",")).join(" ")} fill="none" stroke={ACCENT} strokeWidth={2} strokeLinejoin="round" />
            {bins.map((b, i) => (
              <g key={b.lo} onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}>
                <circle cx={pts[i][0]} cy={pts[i][1]} r={14} fill="transparent" />
                <circle cx={pts[i][0]} cy={pts[i][1]} r={hover === i ? 5.5 : 4} fill={ACCENT}
                  className="stroke-white dark:stroke-gray-900" strokeWidth={2} />
              </g>
            ))}
          </svg>
          {h && (
            <div className="pointer-events-none absolute z-10 px-3 py-2 rounded-lg shadow-lg bg-gray-900 dark:bg-gray-800 text-white text-[11px] leading-relaxed whitespace-nowrap"
              style={{ left: `${(x(h.predicted) / W) * 100}%`, top: `${(y(h.actual) / H) * 100}%`, transform: "translate(-50%, calc(-100% - 12px))" }}>
              <div className="font-semibold">Predicted {(h.predicted * 100).toFixed(1)}%</div>
              <div>Actually won {(h.actual * 100).toFixed(1)}%</div>
              <div className="text-gray-400">{h.n.toLocaleString()} team-games</div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── Probability-quality tiles + Vegas comparison ───────────────────────────────

function Row({ label, model, vegas, fmt, lowerIsBetter }: {
  label: string; model: number; vegas: number; fmt: (v: number) => string; lowerIsBetter?: boolean;
}) {
  const modelWins = lowerIsBetter ? model < vegas : model > vegas;
  return (
    <tr className="border-t border-gray-100 dark:border-gray-800">
      <td className="py-2 text-gray-500">{label}</td>
      <td className={`py-2 text-right font-semibold ${modelWins ? "text-gray-900 dark:text-white" : "text-gray-500"}`}>{fmt(model)}{modelWins && " ✓"}</td>
      <td className={`py-2 text-right font-semibold ${!modelWins ? "text-gray-900 dark:text-white" : "text-gray-500"}`}>{fmt(vegas)}{!modelWins && " ✓"}</td>
    </tr>
  );
}

export function ProbabilityQuality({ logLoss, brier, vegas }: {
  logLoss: number | null; brier: number | null; vegas?: VegasComparison | null;
}) {
  const pct = (v: number) => `${(v * 100).toFixed(1)}%`;
  const dec = (v: number) => v.toFixed(3);
  return (
    <div className="bg-white dark:bg-gray-900 border border-gray-100 dark:border-transparent shadow-sm rounded-2xl p-6">
      <h2 className="text-xs font-bold text-gray-400 uppercase tracking-widest mb-1">Probability quality</h2>
      <p className="text-xs text-gray-400 leading-relaxed mb-4">
        Accuracy only checks who was favoured. Log loss and Brier score also punish being confidently wrong — lower is better
        (a coin flip scores 0.693 and 0.250).
      </p>
      <div className="grid grid-cols-2 gap-3 mb-5">
        <div className="rounded-xl bg-gray-50 dark:bg-gray-800/60 p-3 text-center">
          <p className="text-[10px] text-gray-400 font-semibold uppercase tracking-widest mb-1">Log loss</p>
          <p className="text-xl font-bold text-gray-900 dark:text-white tabular-nums">{logLoss !== null ? dec(logLoss) : "—"}</p>
        </div>
        <div className="rounded-xl bg-gray-50 dark:bg-gray-800/60 p-3 text-center">
          <p className="text-[10px] text-gray-400 font-semibold uppercase tracking-widest mb-1">Brier score</p>
          <p className="text-xl font-bold text-gray-900 dark:text-white tabular-nums">{brier !== null ? dec(brier) : "—"}</p>
        </div>
      </div>

      {vegas ? (
        <>
          <h3 className="text-xs font-semibold text-gray-500 dark:text-gray-400 mb-1">Model vs Vegas closing line</h3>
          <p className="text-xs text-gray-400 mb-2">Same {vegas.n_games.toLocaleString()} past games, bookmaker margin removed.</p>
          <table className="w-full text-sm tabular-nums">
            <thead>
              <tr className="text-xs text-gray-400">
                <th className="text-left font-semibold pb-1"></th>
                <th className="text-right font-semibold pb-1">Model</th>
                <th className="text-right font-semibold pb-1">Vegas</th>
              </tr>
            </thead>
            <tbody>
              <Row label="Accuracy" model={vegas.model.accuracy} vegas={vegas.vegas.accuracy} fmt={pct} />
              <Row label="Log loss" model={vegas.model.log_loss} vegas={vegas.vegas.log_loss} fmt={dec} lowerIsBetter />
              <Row label="Brier" model={vegas.model.brier} vegas={vegas.vegas.brier} fmt={dec} lowerIsBetter />
            </tbody>
          </table>
        </>
      ) : (
        <p className="text-xs text-gray-400">No historical betting lines available for a Vegas comparison.</p>
      )}
    </div>
  );
}
