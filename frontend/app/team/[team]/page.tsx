"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer } from "recharts";

const API = "http://localhost:8000";

interface TeamStats {
  off_rtg: number; def_rtg: number; net_rtg: number; pace: number;
  ts_pct: number; tov_pct: number; oreb_pct: number; srs: number;
  point_diff: number; fg3_rate: number; win_streak: number;
}
interface RecentGame {
  game_id: string; date: string; away_team: string; home_team: string;
  predicted_winner: string; actual_winner: string; correct: boolean;
  away_score: number | null; home_score: number | null; round: string;
}
interface SeriesPoint {
  game: string; team_a_prob: number; team_b_prob: number; series: string;
}

const TEAM_ABBR: Record<string, string> = {
  "Atlanta Hawks": "ATL", "Boston Celtics": "BOS", "Brooklyn Nets": "BKN",
  "Charlotte Hornets": "CHA", "Chicago Bulls": "CHI", "Cleveland Cavaliers": "CLE",
  "Dallas Mavericks": "DAL", "Denver Nuggets": "DEN", "Detroit Pistons": "DET",
  "Golden State Warriors": "GSW", "Houston Rockets": "HOU", "Indiana Pacers": "IND",
  "LA Clippers": "LAC", "Los Angeles Lakers": "LAL", "Memphis Grizzlies": "MEM",
  "Miami Heat": "MIA", "Milwaukee Bucks": "MIL", "Minnesota Timberwolves": "MIN",
  "New Orleans Pelicans": "NOP", "New York Knicks": "NYK", "Oklahoma City Thunder": "OKC",
  "Orlando Magic": "ORL", "Philadelphia 76ers": "PHI", "Phoenix Suns": "PHX",
  "Portland Trail Blazers": "POR", "Sacramento Kings": "SAC", "San Antonio Spurs": "SAS",
  "Toronto Raptors": "TOR", "Utah Jazz": "UTA", "Washington Wizards": "WAS",
};
const TEAM_COLORS: Record<string, string> = {
  ATL: "#E03A3E", BOS: "#007A33", BKN: "#9EA0A2", CHA: "#00788C", CHI: "#CE1141",
  CLE: "#860038", DAL: "#00538C", DEN: "#FEC524", DET: "#1D428A", GSW: "#FFC72C",
  HOU: "#CE1141", IND: "#FDBB30", LAC: "#C8102E", LAL: "#FDB927", MEM: "#5D76A9",
  MIA: "#F9A01B", MIL: "#00471B", MIN: "#236192", NOP: "#C8A956", NYK: "#F58426",
  OKC: "#007AC1", ORL: "#0077C0", PHI: "#006BB6", PHX: "#E56020", POR: "#E03A3E",
  SAC: "#5A2D81", SAS: "#9EA0A2", TOR: "#CE1141", UTA: "#F9A01B", WAS: "#E31837",
};
const TEAM_IDS: Record<string, number> = {
  ATL: 1610612737, BOS: 1610612738, BKN: 1610612751, CHA: 1610612766, CHI: 1610612741,
  CLE: 1610612739, DAL: 1610612742, DEN: 1610612743, DET: 1610612765, GSW: 1610612744,
  HOU: 1610612745, IND: 1610612754, LAC: 1610612746, LAL: 1610612747, MEM: 1610612763,
  MIA: 1610612748, MIL: 1610612749, MIN: 1610612750, NOP: 1610612740, NYK: 1610612752,
  OKC: 1610612760, ORL: 1610612753, PHI: 1610612755, PHX: 1610612756, POR: 1610612757,
  SAC: 1610612758, SAS: 1610612759, TOR: 1610612761, UTA: 1610612762, WAS: 1610612764,
};

function getAbbr(t: string) { return TEAM_ABBR[t] ?? t.split(" ").pop()?.substring(0, 3).toUpperCase() ?? "???"; }
function getColor(t: string) { return TEAM_COLORS[getAbbr(t)] ?? "#555"; }
function getNick(t: string) { return t.split(" ").pop() ?? t; }
function getLogoUrl(t: string) {
  const id = TEAM_IDS[getAbbr(t)];
  return id ? `https://cdn.nba.com/logos/nba/${id}/global/L/logo.svg` : "";
}

function fmtDate(d: string): string {
  const [y, mo, day] = d.split("-").map(Number);
  return new Date(y, mo - 1, day).toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

const STAT_LABELS: Record<string, string> = {
  net_rtg: "Net Rtg", off_rtg: "Off Rtg", def_rtg: "Def Rtg", pace: "Pace",
  ts_pct: "TS%", tov_pct: "TOV%", oreb_pct: "OREB%", srs: "SRS",
  point_diff: "Pt Diff", fg3_rate: "3P Rate", win_streak: "Streak",
};

export default function TeamPage() {
  const params = useParams();
  const teamName = decodeURIComponent(params.team as string);

  const [teamData, setTeamData] = useState<{ name: string; stats: TeamStats; recent_games: RecentGame[] } | null>(null);
  const [seriesHistory, setSeriesHistory] = useState<{ opponent: string; history: SeriesPoint[] } | null>(null);
  const [loading, setLoading]   = useState(true);

  useEffect(() => {
    fetch(`${API}/api/team?name=${encodeURIComponent(teamName)}`)
      .then(r => r.json())
      .then(d => setTeamData(d))
      .finally(() => setLoading(false));
  }, [teamName]);

  // Find opponent from recent games to fetch series history
  useEffect(() => {
    if (!teamData || teamData.recent_games.length === 0) return;
    const g = teamData.recent_games[0];
    const opp = g.away_team === teamName ? g.home_team : g.away_team;
    fetch(`${API}/api/series_history?team_a=${encodeURIComponent(teamName)}&team_b=${encodeURIComponent(opp)}`)
      .then(r => r.json())
      .then(d => {
        if (d.history && d.history.length > 1) setSeriesHistory({ opponent: opp, history: d.history });
      })
      .catch(() => {});
  }, [teamData, teamName]);

  if (loading) return (
    <main className="px-6 py-8 max-w-3xl mx-auto">
      <div className="text-center text-gray-400 text-sm py-16">Loading…</div>
    </main>
  );

  if (!teamData) return (
    <main className="px-6 py-8 max-w-3xl mx-auto">
      <div className="text-center text-gray-400 text-sm py-16">Team not found.</div>
    </main>
  );

  const abbr  = getAbbr(teamName);
  const color = getColor(teamName);
  const logoId = TEAM_IDS[abbr];
  const correct = teamData.recent_games.filter(g => g.correct).length;
  const acc = teamData.recent_games.length > 0 ? Math.round((correct / teamData.recent_games.length) * 100) : 0;

  return (
    <main className="px-6 py-8 max-w-3xl mx-auto">
      {/* Header */}
      <div className="mb-8 flex items-center gap-4">
        <Link href="/bracket" className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 transition-colors">
          <svg width="18" height="18" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
            <path d="M10 12L6 8l4-4" />
          </svg>
        </Link>
        {logoId && (
          <img src={`https://cdn.nba.com/logos/nba/${logoId}/global/L/logo.svg`} alt={teamName}
            className="w-14 h-14 object-contain" />
        )}
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">{teamName}</h1>
          <p className="text-sm font-semibold mt-0.5" style={{ color }}>{abbr}</p>
        </div>
      </div>

      {/* Key stats grid */}
      <div className="grid grid-cols-4 gap-3 mb-6">
        {(["net_rtg", "off_rtg", "def_rtg", "pace"] as Array<keyof TeamStats>).map(k => (
          <div key={k} className="bg-white dark:bg-gray-900 border border-gray-100 dark:border-transparent shadow-sm rounded-xl px-4 py-3">
            <p className="text-xs text-gray-400">{STAT_LABELS[k]}</p>
            <p className={`text-xl font-bold mt-0.5 ${
              k === "net_rtg" ? (teamData.stats[k] > 0 ? "text-green-600 dark:text-green-400" : "text-red-500")
                              : "text-gray-900 dark:text-white"
            }`}>
              {teamData.stats[k]?.toFixed(1)}
            </p>
          </div>
        ))}
      </div>

      {/* Secondary stats */}
      <div className="bg-white dark:bg-gray-900 border border-gray-100 dark:border-transparent shadow-sm rounded-2xl px-5 py-4 mb-6">
        <div className="grid grid-cols-4 gap-y-3 gap-x-4">
          {(["ts_pct", "tov_pct", "oreb_pct", "fg3_rate", "srs", "point_diff", "win_streak"] as const).map(k => (
            <div key={k} className="flex flex-col">
              <span className="text-[11px] text-gray-400">{STAT_LABELS[k]}</span>
              <span className="text-sm font-bold text-gray-900 dark:text-white mt-0.5">
                {k === "ts_pct" || k === "tov_pct" || k === "oreb_pct" || k === "fg3_rate"
                  ? `${(teamData.stats[k] * 100).toFixed(1)}%`
                  : teamData.stats[k]?.toFixed(1)}
              </span>
            </div>
          ))}
        </div>
      </div>

      {/* Series probability tracker */}
      {seriesHistory && (
        <div className="bg-white dark:bg-gray-900 border border-gray-100 dark:border-transparent shadow-sm rounded-2xl px-5 py-4 mb-6">
          <p className="text-sm font-bold text-gray-900 dark:text-white mb-1">
            Series vs {getNick(seriesHistory.opponent)}
          </p>
          <p className="text-xs text-gray-400 mb-4">Win probability after each game</p>
          <ResponsiveContainer width="100%" height={120}>
            <LineChart data={seriesHistory.history} margin={{ top: 4, right: 4, left: -24, bottom: 0 }}>
              <XAxis dataKey="game" tick={{ fontSize: 11, fill: "#9ca3af" }} axisLine={false} tickLine={false} />
              <YAxis domain={[0, 100]} tick={{ fontSize: 11, fill: "#9ca3af" }} axisLine={false} tickLine={false} />
              <Tooltip
                formatter={(v: unknown) => [`${v}%`, getNick(teamName)]}
                contentStyle={{ background: "#1f2937", border: "none", borderRadius: 8, fontSize: 12 }}
                labelStyle={{ color: "#9ca3af" }}
              />
              <Line type="monotone" dataKey="team_a_prob" stroke={color} strokeWidth={2.5}
                dot={{ fill: color, r: 4 }} activeDot={{ r: 5 }} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Recent games */}
      <div className="bg-white dark:bg-gray-900 border border-gray-100 dark:border-transparent shadow-sm rounded-2xl overflow-hidden">
        <div className="px-5 py-4 border-b border-gray-100 dark:border-gray-800 flex items-center justify-between">
          <p className="text-sm font-bold text-gray-900 dark:text-white">Playoff games</p>
          {teamData.recent_games.length > 0 && (
            <span className={`text-xs font-semibold px-2 py-0.5 rounded-full ${
              acc >= 60 ? "bg-green-100 dark:bg-green-500/20 text-green-700 dark:text-green-400"
                        : "bg-yellow-100 dark:bg-yellow-500/20 text-yellow-700 dark:text-yellow-400"
            }`}>
              {acc}% accuracy
            </span>
          )}
        </div>

        {teamData.recent_games.length === 0 ? (
          <div className="p-8 text-center text-gray-400 text-sm">No games yet this season.</div>
        ) : (
          <div className="divide-y divide-gray-100 dark:divide-gray-800">
            {teamData.recent_games.map((g, i) => {
              const params = new URLSearchParams({
                away: g.away_team, home: g.home_team, time: "Final", status: "Final",
                winner: g.predicted_winner,
                away_score: g.away_score !== null ? String(g.away_score) : "",
                home_score: g.home_score !== null ? String(g.home_score) : "",
              });
              return (
                <Link key={i} href={`/game/${g.game_id}?${params}`}
                  className="flex items-center gap-4 px-5 py-3 hover:bg-gray-50 dark:hover:bg-gray-800/50 transition-colors">
                  <span className="text-xs text-gray-400 w-14 flex-shrink-0">{fmtDate(g.date)}</span>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-gray-900 dark:text-white truncate">
                      {getAbbr(g.away_team)} @ {getAbbr(g.home_team)}
                    </p>
                    <p className="text-[11px] text-gray-400 mt-0.5">{g.round}</p>
                  </div>
                  {g.away_score !== null && (
                    <span className="text-xs text-gray-500 flex-shrink-0">
                      {g.away_score}–{g.home_score}
                    </span>
                  )}
                  <span className={`text-[10px] px-2 py-0.5 rounded-full font-semibold flex-shrink-0 ${
                    g.correct
                      ? "bg-green-100 dark:bg-green-500/20 text-green-700 dark:text-green-400"
                      : "bg-red-100 dark:bg-red-500/20 text-red-700 dark:text-red-400"
                  }`}>
                    {g.correct ? "✓" : "✗"}
                  </span>
                </Link>
              );
            })}
          </div>
        )}
      </div>
    </main>
  );
}
