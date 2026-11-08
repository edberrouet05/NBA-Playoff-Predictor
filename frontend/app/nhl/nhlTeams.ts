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
