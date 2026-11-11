// "Projected score" card for the NFL game page (the NBA page has its own, with pace), and the
// projected-total line on the NBA and NFL game cards. Only shown where a backtest beat the league average.

export interface Projection {
  away: number;
  home: number;
  total: number;
}

/** Goals and runs keep one decimal (3.0, not 3); points are whole numbers. */
function fmt(n: number, decimals: number) { return n.toFixed(decimals); }

export function ProjectedScoreCard({ projection: pr, awayAbbr, homeAbbr, actual, note, decimals = 0 }: {
  projection: Projection; awayAbbr: string; homeAbbr: string; decimals?: number;
  /** The final total once the game is over */
  actual?: number | null;
  note: string;
}) {
  return (
    <div className="bg-white dark:bg-gray-900 border border-gray-100 dark:border-transparent shadow-sm rounded-2xl p-5">
      <p className="text-[10px] font-semibold text-gray-500 uppercase tracking-widest mb-3">Projected score</p>
      <div className="flex items-center justify-center gap-4 tabular-nums">
        <span className="text-xs font-bold text-gray-500">{awayAbbr}</span>
        <span className="text-2xl font-black text-gray-900 dark:text-white">{fmt(pr.away, decimals)}</span>
        <span className="text-gray-300 dark:text-gray-700">–</span>
        <span className="text-2xl font-black text-gray-900 dark:text-white">{fmt(pr.home, decimals)}</span>
        <span className="text-xs font-bold text-gray-500">{homeAbbr}</span>
      </div>
      <p className="mt-2 text-center text-[11px] text-gray-400">
        Total {fmt(pr.total, decimals)}
        {actual != null && <> · <span className="font-semibold text-gray-600 dark:text-gray-300">actual {actual}</span></>}
      </p>
      <p className="mt-1 text-center text-[10px] text-gray-400">{note}</p>
    </div>
  );
}

/** Small line for the game cards: projected total, and the real one once the game is over. */
export function TotalLine({ projected, actual, decimals = 0 }: {
  projected?: number | null; actual?: number | null; decimals?: number;
}) {
  if (projected == null) return null;
  return (
    <span className="text-[11px] text-gray-400 whitespace-nowrap tabular-nums">
      Proj. total {fmt(projected, decimals)}
      {actual != null && <> · actual <span className="font-semibold text-gray-600 dark:text-gray-300">{actual}</span></>}
    </span>
  );
}
