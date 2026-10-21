// URL of a team page, e.g. teamHref("nfl", "Cleveland Browns") → "/nfl/team/cleveland-browns".
// The API resolves the slug back to the team (it also accepts abbreviations).
export function teamHref(league: "nfl" | "mlb" | "nba", teamName: string): string {
  return `/${league}/team/${teamName.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/(^-|-$)/g, "")}`;
}

// URL of a player page from an ESPN athlete id, e.g. playerHref("nfl", "3122840") → "/nfl/player/3122840"
export function playerHref(league: "nfl" | "mlb" | "nba", athleteId: string): string {
  return `/${league}/player/${athleteId}`;
}

// URL of our NBA game page, seen from one team. That page reads the matchup from the query
// string, so this builds the same parameters as the home page's game links.
export function nbaGameHref(gameId: string, g: {
  team: string; opponent: string; home: boolean; date: string;
  winProb: number | null | undefined; teamScore: number | null; oppScore: number | null;
  status: "Scheduled" | "Live" | "Final";
}): string {
  const [away, home] = g.home ? [g.opponent, g.team] : [g.team, g.opponent];
  const [awayScore, homeScore] = g.home ? [g.oppScore, g.teamScore] : [g.teamScore, g.oppScore];
  let time: string = g.status;
  if (g.status === "Scheduled") {
    try {
      time = `${new Date(g.date).toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit", timeZone: "America/New_York" })} ET`;
    } catch { /* keep the status */ }
  }
  const p = new URLSearchParams({
    away, home, time, status: g.status,
    away_score: awayScore != null ? String(awayScore) : "",
    home_score: homeScore != null ? String(homeScore) : "",
  });
  if (g.winProb != null) {
    const awayProb = g.home ? Math.round((100 - g.winProb) * 10) / 10 : g.winProb;
    const homeProb = Math.round((100 - awayProb) * 10) / 10;
    p.set("away_prob", String(awayProb));
    p.set("home_prob", String(homeProb));
    p.set("winner", awayProb >= 50 ? away : home);
  }
  return `/game/${gameId}?${p.toString()}`;
}
