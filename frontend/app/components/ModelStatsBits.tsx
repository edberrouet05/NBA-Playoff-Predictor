// Pieces shared by the four "How it's tested" pages: the headline tiles, the accuracy-by-season
// bars and the "trained on" season range.

/** Season years are the year a season ends; `split` sports span two years (2026 = 2025-26). */
export function seasonSpan(seasons: number[], split: boolean): string {
  if (!seasons.length) return "";
  const name = (s: number) => (split ? `${s - 1}-${String(s).slice(2)}` : String(s));
  const first = Math.min(...seasons), last = Math.max(...seasons);
  return first === last ? `the ${name(first)} season` : `the ${name(first)} to ${name(last)} seasons`;
}

export function Metric({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="bg-white dark:bg-gray-900 border border-gray-100 dark:border-transparent shadow-sm rounded-2xl p-3 sm:p-5 text-center min-w-0">
      <p className="text-[10px] sm:text-xs text-gray-400 font-semibold uppercase tracking-wide sm:tracking-widest mb-1.5 sm:mb-2 leading-tight">{label}</p>
      <p className="text-xl sm:text-2xl font-bold text-gray-900 dark:text-white tabular-nums">{value}</p>
      {sub && <p className="text-[11px] sm:text-xs text-gray-400 mt-1 leading-snug">{sub}</p>}
    </div>
  );
}

/** One column per held-out season (value, bar, label stacked so they always line up). */
export function FoldBars({ folds, avg, seasons, split }: {
  folds: number[]; avg: number; seasons: number[]; split: boolean;
}) {
  if (!folds.length) return null;
  const max   = Math.max(...folds);
  const min   = Math.min(...folds);
  const range = max - min || 1;
  // Shortest bar 40% of the height, tallest 100%
  const height = (v: number) => 40 + ((v - min) / range) * 60;
  const named = seasons.length === folds.length;
  // Phones show the end year ('26); wider screens the full season ('25-26) for split sports
  const short = (i: number) => (named ? `'${String(seasons[i]).slice(2)}` : `${i + 1}`);
  const long  = (i: number) => (named
    ? (split ? `'${String(seasons[i] - 1).slice(2)}-${String(seasons[i]).slice(2)}` : `'${String(seasons[i]).slice(2)}`)
    : `Fold ${i + 1}`);

  return (
    <div className="bg-white dark:bg-gray-900 border border-gray-100 dark:border-transparent shadow-sm rounded-2xl p-4 sm:p-6">
      <div className="flex items-start justify-between mb-5 gap-4">
        <div>
          <h2 className="text-xs font-bold text-gray-400 uppercase tracking-widest mb-1">Accuracy by season</h2>
          <p className="text-xs text-gray-400 leading-relaxed">
            Each bar shows how accurate the model was on one season when trained only on the other seasons.
          </p>
        </div>
        <span className="text-xs text-gray-400 flex-shrink-0">avg <span className="font-bold text-gray-700 dark:text-gray-200">{avg.toFixed(2)}%</span></span>
      </div>

      <div className="flex gap-1 sm:gap-2">
        {folds.map((acc, i) => (
          <div key={i} className="flex-1 min-w-0 flex flex-col items-center" title={`Held-out season ${long(i)}: ${acc.toFixed(1)}%`}>
            <span className={`text-[9px] sm:text-[11px] font-bold tabular-nums mb-1 ${acc === max ? "text-red-500" : "text-gray-500 dark:text-gray-400"}`}>
              {acc.toFixed(1)}<span className="hidden sm:inline">%</span>
            </span>
            <div className="w-full flex items-end" style={{ height: 64 }}>
              <div className="w-full rounded-t-md" style={{ height: `${height(acc)}%`, background: acc === max ? "#ef4444" : "#e5e7eb" }} />
            </div>
            <span className="text-[9px] sm:text-[10px] text-gray-400 mt-1.5 whitespace-nowrap">
              <span className="sm:hidden">{short(i)}</span><span className="hidden sm:inline">{long(i)}</span>
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
