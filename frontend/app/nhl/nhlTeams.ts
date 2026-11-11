// NHL team metadata shared by the NHL pages: ESPN abbreviations, colors and logos.

export const NHL_ABBR: Record<string, string> = {
  "Anaheim Ducks": "ANA", "Boston Bruins": "BOS", "Buffalo Sabres": "BUF", "Calgary Flames": "CGY",
  "Carolina Hurricanes": "CAR", "Chicago Blackhawks": "CHI", "Colorado Avalanche": "COL",
  "Columbus Blue Jackets": "CBJ", "Dallas Stars": "DAL", "Detroit Red Wings": "DET", "Edmonton Oilers": "EDM",
  "Florida Panthers": "FLA", "Los Angeles Kings": "LA", "Minnesota Wild": "MIN", "Montreal Canadiens": "MTL",
  "Nashville Predators": "NSH", "New Jersey Devils": "NJ", "New York Islanders": "NYI", "New York Rangers": "NYR",
  "Ottawa Senators": "OTT", "Philadelphia Flyers": "PHI", "Pittsburgh Penguins": "PIT", "San Jose Sharks": "SJ",
  "Seattle Kraken": "SEA", "St. Louis Blues": "STL", "Tampa Bay Lightning": "TB", "Toronto Maple Leafs": "TOR",
  "Utah Mammoth": "UTAH", "Vancouver Canucks": "VAN", "Vegas Golden Knights": "VGK", "Washington Capitals": "WSH",
  "Winnipeg Jets": "WPG",
};

export const NHL_COLORS: Record<string, string> = {
  ANA: "#F47A38", BOS: "#FFB81C", BUF: "#003087", CGY: "#C8102E", CAR: "#CE1126", CHI: "#CF0A2C",
  COL: "#6F263D", CBJ: "#002654", DAL: "#006847", DET: "#CE1126", EDM: "#FF4C00", FLA: "#C8102E",
  LA: "#A2AAAD", MIN: "#154734", MTL: "#AF1E2D", NSH: "#FFB81C", NJ: "#CE1126", NYI: "#00539B",
  NYR: "#0038A8", OTT: "#C52032", PHI: "#F74902", PIT: "#FCB514", SJ: "#006D75", SEA: "#99D9D9",
  STL: "#002F87", TB: "#002868", TOR: "#00205B", UTAH: "#71AFE5", VAN: "#00843D", VGK: "#B4975A",
  WSH: "#C8102E", WPG: "#041E42",
};

// Secondary colors, used when both teams' primaries look alike
export const NHL_ALT_COLORS: Record<string, string> = {
  ANA: "#B9975B", BOS: "#000000", BUF: "#FFB81C", CGY: "#F1BE48", CAR: "#000000", CHI: "#000000",
  COL: "#236192", CBJ: "#CE1126", DAL: "#8F8F8C", DET: "#000000", EDM: "#041E42", FLA: "#041E42",
  LA: "#111111", MIN: "#A6192E", MTL: "#192168", NSH: "#041E42", NJ: "#000000", NYI: "#F47D30",
  NYR: "#CE1126", OTT: "#000000", PHI: "#000000", PIT: "#000000", SJ: "#EA7200", SEA: "#001628",
  STL: "#FCB514", TB: "#FFFFFF", TOR: "#A2AAAD", UTAH: "#090909", VAN: "#00205B", VGK: "#333F42",
  WSH: "#041E42", WPG: "#AC162C",
};

export function nhlAbbr(team: string): string {
  return NHL_ABBR[team] ?? team.split(" ").pop()?.slice(0, 3).toUpperCase() ?? "???";
}

export function nhlColor(team: string): string {
  return NHL_COLORS[nhlAbbr(team)] ?? "#555";
}

export function nhlNick(team: string): string {
  // "Maple Leafs", "Red Wings", "Blue Jackets", "Golden Knights": the last word alone is odd
  const words = team.split(" ");
  const two = ["Leafs", "Wings", "Jackets", "Knights"].includes(words[words.length - 1]);
  return words.slice(two ? -2 : -1).join(" ");
}

export function nhlLogo(team: string): string {
  return `https://a.espncdn.com/i/teamlogos/nhl/500/${nhlAbbr(team).toLowerCase()}.png`;
}

/** The team's primary color, then its secondary: options for a matchup color pair. */
export function nhlColorOptions(team: string): string[] {
  const a = nhlAbbr(team);
  return [NHL_COLORS[a] ?? "#555", ...(NHL_ALT_COLORS[a] ? [NHL_ALT_COLORS[a]] : [])];
}
