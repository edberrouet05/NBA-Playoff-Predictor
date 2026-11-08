// Shared bits for NBA / MLB / NFL game cards.

/** "2026–27": the NBA season under way (a new one from August), as nba/pipeline.py counts it. */
export function nbaSeasonLabel(d = new Date()): string {
  const end = d.getMonth() >= 7 ? d.getFullYear() + 1 : d.getFullYear();
  return `${end - 1}–${String(end).slice(2)}`;
}

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

/** "Value pick" badge: the model's probability beats the no-vig market price by ≥ 5 points.
 *  The numbers are in the tooltip. Hidden once the game has started: it is about the pre-game
 *  price, which can no longer be bet and ignores the score. */
export function ValueBadge({ game, awayAbbr, homeAbbr, started = false }: {
  game: ValueFields & { away_win_prob: number; home_win_prob: number };
  awayAbbr: string;
  homeAbbr: string;
  started?: boolean;
}) {
  if (started || !game.value_side || game.value_edge == null) return null;
  const away = game.value_side === "away";
  const model  = away ? game.away_win_prob : game.home_win_prob;
  const market = away ? game.away_market_prob : game.home_market_prob;
  const ev = game.value_ev != null ? `${game.value_ev >= 0 ? "+" : ""}${(game.value_ev * 100).toFixed(0)}%` : "—";
  return (
    <span
      title={`Our model gives ${away ? awayAbbr : homeAbbr} ${model}%, the bookmakers ${market ?? "—"}% (their margin removed). If the model is right, a bet returns ${ev} on average.`}
      className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-amber-100 dark:bg-amber-500/20 text-amber-700 dark:text-amber-400 cursor-help">
      Value pick: {away ? awayAbbr : homeAbbr}
    </span>
  );
}
