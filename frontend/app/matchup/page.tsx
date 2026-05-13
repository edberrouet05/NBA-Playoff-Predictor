"use client";
import { useEffect, useState } from "react";

const API = "http://localhost:8000";

interface TeamStats {
  off_rtg: number; def_rtg: number; net_rtg: number; pace: number;
  ts_pct: number; tov_pct: number; oreb_pct: number; srs: number;
  point_diff: number; fg3_rate: number; ftr: number; win_streak: number;
}

interface Prediction {
  team_a: string; team_b: string;
  team_a_series_prob: number; team_b_series_prob: number;
  predicted_winner: string;
  games: { game: number; winner: string; series_score: string; clinching: boolean; team_a_prob: number; team_b_prob: number }[];
  outcomes: { result: string; team_a_pct: number; team_b_pct: number }[];
}

interface CompareResult {
  team_a: string; team_b: string;
  team_a_stats: TeamStats; team_b_stats: TeamStats;
  prediction: Prediction;
}

const STATS = [
  { key: "off_rtg",    label: "Offensive Rating",  better: 1,    pct: false },
  { key: "def_rtg",    label: "Defensive Rating",  better: -1,   pct: false },
  { key: "net_rtg",    label: "Net Rating",        better: 1,    pct: false },
  { key: "ts_pct",     label: "True Shooting %",   better: 1,    pct: true  },
  { key: "tov_pct",    label: "Turnover %",        better: -1,   pct: true  },
  { key: "oreb_pct",   label: "Off. Rebound %",    better: 1,    pct: true  },
  { key: "fg3_rate",   label: "3PT Rate",          better: 0,    pct: true  },
  { key: "ftr",        label: "Free Throw Rate",   better: 1,    pct: true  },
  { key: "srs",        label: "SRS",               better: 1,    pct: false },
  { key: "point_diff", label: "Point Differential",better: 1,    pct: false },
  { key: "pace",       label: "Pace",              better: 0,    pct: false },
  { key: "win_streak", label: "Win Streak",        better: 1,    pct: false },
];

function fmt(v: number, pct: boolean): string {
  if (pct) return (v * 100).toFixed(1) + "%";
  if (Number.isInteger(v)) return (v > 0 ? "+" : "") + v;
  return v.toFixed(1);
}

export default function MatchupPage() {
  const [teams,   setTeams]   = useState<string[]>([]);
  const [teamA,   setTeamA]   = useState("");
  const [teamB,   setTeamB]   = useState("");
  const [result,  setResult]  = useState<CompareResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error,   setError]   = useState("");

  useEffect(() => {
    fetch(`${API}/api/teams`)
      .then((r) => r.json())
      .then(setTeams)
      .catch(() => setError("Backend unreachable."));
  }, []);

  async function compare() {
    if (!teamA || !teamB) return;
    if (teamA === teamB) { setError("Pick two different teams."); return; }
    setError("");
    setLoading(true);
    try {
      const res = await fetch(
        `${API}/api/compare?team_a=${encodeURIComponent(teamA)}&team_b=${encodeURIComponent(teamB)}`
      );
      if (!res.ok) throw new Error();
      setResult(await res.json());
    } catch {
      setError("Comparison failed. Check the backend.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="max-w-2xl mx-auto px-4 py-10">
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-gray-900">Matchup Comparison</h1>
        <p className="text-gray-500 text-sm mt-1">Feature-by-feature breakdown · series simulation</p>
      </div>

      {/* Selectors */}
      <div className="bg-white border border-gray-200 rounded-2xl p-6 shadow-sm mb-6">
        <div className="flex items-end gap-4">
          <Sel label="Team A" value={teamA} teams={teams} onChange={setTeamA} />
          <span className="text-gray-300 font-bold text-xl pb-2">vs</span>
          <Sel label="Team B" value={teamB} teams={teams} onChange={setTeamB} />
        </div>
        {error && <p className="mt-3 text-red-600 text-sm">{error}</p>}
        <button
          onClick={compare}
          disabled={!teamA || !teamB || loading}
          className="mt-4 w-full py-2.5 rounded-xl bg-red-600 hover:bg-red-500 disabled:bg-gray-200 disabled:text-gray-400 text-white font-semibold transition-colors"
        >
          {loading ? "Comparing…" : "Compare"}
        </button>
      </div>

      {result && (
        <div className="flex flex-col gap-5">

          {/* Win probability */}
          <Card title="Series Win Probability">
            <ProbBar team={result.team_a} pct={result.prediction.team_a_series_prob} />
            <ProbBar team={result.team_b} pct={result.prediction.team_b_series_prob} />
            <div className="mt-4 pt-4 border-t border-gray-100 text-center">
              <p className="text-xs text-gray-400 uppercase tracking-widest">Predicted winner</p>
              <p className="text-xl font-bold text-red-600 mt-1">{result.prediction.predicted_winner}</p>
            </div>
          </Card>

          {/* Stats comparison */}
          <Card title="Stats Comparison">
            {/* Header row */}
            <div className="grid grid-cols-[1fr_auto_1fr] gap-x-4 pb-3 mb-1 border-b border-gray-100">
              <span className="text-center text-sm font-bold text-gray-900">{result.team_a}</span>
              <span />
              <span className="text-center text-sm font-bold text-gray-900">{result.team_b}</span>
            </div>
            {STATS.map(({ key, label, better, pct }) => {
              const a = result.team_a_stats[key as keyof TeamStats] ?? 0;
              const b = result.team_b_stats[key as keyof TeamStats] ?? 0;
              const aWins = better !== 0 && (better === 1 ? a > b : a < b);
              const bWins = better !== 0 && (better === 1 ? b > a : b < a);
              return (
                <div key={key} className="grid grid-cols-[1fr_auto_1fr] gap-x-4 items-center py-2 border-b border-gray-50 last:border-0">
                  <span className={`text-center text-sm font-semibold ${aWins ? "text-red-600" : "text-gray-400"}`}>
                    {fmt(a, pct)}
                  </span>
                  <span className="text-xs text-gray-400 text-center whitespace-nowrap w-32">{label}</span>
                  <span className={`text-center text-sm font-semibold ${bWins ? "text-red-600" : "text-gray-400"}`}>
                    {fmt(b, pct)}
                  </span>
                </div>
              );
            })}
          </Card>

          {/* Game-by-game */}
          <Card title="Game-by-Game Simulation">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-gray-400 text-xs uppercase border-b border-gray-200">
                  <th className="text-left pb-2">Game</th>
                  <th className="text-left pb-2">Winner</th>
                  <th className="text-right pb-2">Prob</th>
                  <th className="text-right pb-2">Series</th>
                </tr>
              </thead>
              <tbody>
                {result.prediction.games.map((g) => (
                  <tr key={g.game} className={`border-b border-gray-100 ${g.clinching ? "font-semibold" : ""}`}>
                    <td className="py-2 text-gray-400">Game {g.game}</td>
                    <td className={`py-2 ${g.clinching ? "text-red-600" : ""}`}>
                      {g.winner}
                      {g.clinching && (
                        <span className="ml-2 text-xs bg-red-100 text-red-600 px-2 py-0.5 rounded-full">
                          Clinches
                        </span>
                      )}
                    </td>
                    <td className="py-2 text-right text-gray-400">
                      {g.winner === result.team_a ? g.team_a_prob : g.team_b_prob}%
                    </td>
                    <td className="py-2 text-right text-gray-400">{g.series_score}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>

          {/* Outcome distribution */}
          <Card title="Series Outcome Distribution (10 000 simulations)">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-gray-400 text-xs uppercase border-b border-gray-200">
                  <th className="text-left pb-2">Result</th>
                  <th className="text-right pb-2">{result.team_a}</th>
                  <th className="text-right pb-2">{result.team_b}</th>
                </tr>
              </thead>
              <tbody>
                {result.prediction.outcomes.map((o) => (
                  <tr key={o.result} className="border-b border-gray-100">
                    <td className="py-2 text-gray-500">{o.result}</td>
                    <td className="py-2 text-right text-red-600 font-medium">{o.team_a_pct}%</td>
                    <td className="py-2 text-right text-gray-400">{o.team_b_pct}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>

        </div>
      )}
    </main>
  );
}

function Sel({ label, value, teams, onChange }: {
  label: string; value: string; teams: string[]; onChange: (v: string) => void;
}) {
  return (
    <div className="flex-1">
      <label className="text-xs text-gray-500 font-medium block mb-1">{label}</label>
      <select
        value={value} onChange={(e) => onChange(e.target.value)}
        className="w-full bg-white border border-gray-300 rounded-lg px-3 py-2 text-sm text-gray-900 focus:outline-none focus:ring-2 focus:ring-red-500"
      >
        <option value="">Select team…</option>
        {teams.map((t) => <option key={t} value={t}>{t}</option>)}
      </select>
    </div>
  );
}

function ProbBar({ team, pct }: { team: string; pct: number }) {
  return (
    <div className="mb-3">
      <div className="flex justify-between text-sm mb-1">
        <span className="font-medium text-gray-800">{team}</span>
        <span className="text-red-600 font-bold">{pct}%</span>
      </div>
      <div className="h-2.5 bg-gray-100 rounded-full overflow-hidden">
        <div className="h-full bg-red-600 rounded-full transition-all duration-500" style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="bg-white border border-gray-200 rounded-2xl p-6 shadow-sm">
      <h2 className="text-xs font-semibold text-gray-400 uppercase tracking-widest mb-4">{title}</h2>
      {children}
    </div>
  );
}
