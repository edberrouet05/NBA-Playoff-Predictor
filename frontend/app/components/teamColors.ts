// Pick a visually distinct color pair for two teams in a matchup.
// Each team offers its primary color first, then alternates; we keep the primaries
// when they're far enough apart, otherwise swap in the alternate that contrasts best.

const MIN_DISTANCE = 40; // CIE76 ΔE — below this two colors read as "the same" in a chart

function hexToLab(hex: string): [number, number, number] {
  const n = parseInt(hex.replace("#", ""), 16);
  const lin = (c: number) => {
    const v = c / 255;
    return v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
  };
  const r = lin((n >> 16) & 255), g = lin((n >> 8) & 255), b = lin(n & 255);
  const x = (r * 0.4124 + g * 0.3576 + b * 0.1805) / 0.95047;
  const y = r * 0.2126 + g * 0.7152 + b * 0.0722;
  const z = (r * 0.0193 + g * 0.1192 + b * 0.9505) / 1.08883;
  const f = (t: number) => (t > 0.008856 ? Math.cbrt(t) : 7.787 * t + 16 / 116);
  const fx = f(x), fy = f(y), fz = f(z);
  return [116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)];
}

export function colorDistance(a: string, b: string): number {
  const [l1, a1, b1] = hexToLab(a);
  const [l2, a2, b2] = hexToLab(b);
  return Math.hypot(l1 - l2, a1 - a2, b1 - b2);
}

/** Returns [awayColor, homeColor]. Candidate lists are ordered by preference (primary first). */
export function pickMatchupColors(away: string[], home: string[]): [string, string] {
  // Preference order: both primaries, then change the home team, then the away team, then both
  const combos: [number, number][] = [];
  for (let hi = 0; hi < home.length; hi++) combos.push([0, hi]);
  for (let ai = 1; ai < away.length; ai++) for (let hi = 0; hi < home.length; hi++) combos.push([ai, hi]);

  let best: [string, string] = [away[0], home[0]];
  let bestD = -1;
  for (const [ai, hi] of combos) {
    const d = colorDistance(away[ai], home[hi]);
    if (d >= MIN_DISTANCE) return [away[ai], home[hi]];
    if (d > bestD) { bestD = d; best = [away[ai], home[hi]]; }
  }
  return best;
}
