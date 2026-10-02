// URL of a team page, e.g. teamHref("nfl", "Cleveland Browns") → "/nfl/team/cleveland-browns".
// The API resolves the slug back to the team (it also accepts abbreviations).
export function teamHref(league: "nfl" | "mlb" | "nba", teamName: string): string {
  return `/${league}/team/${teamName.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/(^-|-$)/g, "")}`;
}
