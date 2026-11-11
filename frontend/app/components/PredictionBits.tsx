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
  value_underdog?: boolean | null;
}

/** "Edge" badge: our probability, blended 1 to 3 with the market's, still beats the bookmaker's
 *  price (see _value_bet in api/odds.py). Usually an underdog, so it says so. The numbers are in the tooltip. Hidden once the game has started: it is about the pre-game
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
  const team = away ? awayAbbr : homeAbbr;
  const risk = game.value_underdog ? ` Higher risk: ${team} is the underdog and should lose more often than it wins.` : "";
  return (
    <span
      title={`Our model gives ${team} ${model}%, the bookmakers ${market ?? "—"}% (their margin removed). We disagree with the bookmakers here. They are usually right: an edge only pays off over many games, never on one.${risk}`}
      className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-amber-100 dark:bg-amber-500/20 text-amber-700 dark:text-amber-400 cursor-help whitespace-nowrap">
      Edge: {team}{game.value_underdog ? " · underdog" : ""}
    </span>
  );
}
