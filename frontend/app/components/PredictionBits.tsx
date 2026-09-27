// Shared bits for NBA / MLB / NFL game cards.

/** Color for a team's win-probability label: green for the model's pick,
 *  red once the game is final and that pick lost, gray for the other side. */
export function probClass(isPredicted: boolean, pickLost: boolean): string {
  if (!isPredicted) return "text-gray-500";
  return pickLost ? "text-red-600 dark:text-red-400" : "text-green-600 dark:text-green-400";
}

/** Value-bet fields added by the API (_value_bet in api/main.py). */
export interface ValueFields {
  away_market_prob?: number | null;
  home_market_prob?: number | null;
  value_side?: "away" | "home" | null;
  value_edge?: number | null;
  value_ev?: number | null;
}

/** Badge shown when the model's probability beats the no-vig market price by ≥ 5 points. */
export function ValueBadge({ game, awayAbbr, homeAbbr }: {
  game: ValueFields & { away_win_prob: number; home_win_prob: number };
  awayAbbr: string;
  homeAbbr: string;
}) {
  if (!game.value_side || game.value_edge == null) return null;
  const away = game.value_side === "away";
  const model  = away ? game.away_win_prob : game.home_win_prob;
  const market = away ? game.away_market_prob : game.home_market_prob;
  const ev = game.value_ev != null ? `${game.value_ev >= 0 ? "+" : ""}${(game.value_ev * 100).toFixed(0)}%` : "—";
  return (
    <span
      title={`Model ${model}% vs market ${market ?? "—"}% (bookmaker margin removed). Expected return per bet: ${ev}.`}
      className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-amber-100 dark:bg-amber-500/20 text-amber-700 dark:text-amber-400 cursor-help">
      Value: {away ? awayAbbr : homeAbbr} +{game.value_edge.toFixed(0)} pts
    </span>
  );
}
