"use client";

import { useEffect, useState } from "react";

const API = "http://localhost:8000";

interface PredictionResult {
  team_a: string;
  team_b: string;
  team_a_win_prob: number;
  team_b_win_prob: number;
}

export default function Home() {
  const [teams, setTeams] = useState<string[]>([]);
  const [teamA, setTeamA] = useState("");
  const [teamB, setTeamB] = useState("");
  const [result, setResult] = useState<PredictionResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    fetch(`${API}/api/teams`)
      .then((r) => r.json())
      .then(setTeams)
      .catch(() => setError("Could not reach the backend. Is it running?"));
  }, []);

  async function predict() {
    if (!teamA || !teamB) return;
    if (teamA === teamB) {
      setError("Pick two different teams.");
      return;
    }
    setError("");
    setLoading(true);
    try {
      const res = await fetch(`${API}/api/predict`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ team_a: teamA, team_b: teamB }),
      });
      if (!res.ok) throw new Error();
      setResult(await res.json());
    } catch {
      setError("Prediction failed. Check the backend.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="min-h-screen bg-gray-950 text-white flex flex-col items-center px-4 py-16">
      <h1 className="text-4xl font-bold mb-2 tracking-tight">
        NBA Playoff Predictor
      </h1>
      <p className="text-gray-400 mb-12 text-sm">
        Series win probability based on 2024–25 regular season stats
      </p>

      <div className="w-full max-w-2xl bg-gray-900 rounded-2xl p-8 shadow-xl">
        <div className="flex items-center gap-4">
          <TeamSelect
            label="Team A"
            value={teamA}
            teams={teams}
            onChange={setTeamA}
          />
          <span className="text-gray-500 font-bold text-xl pt-6">vs</span>
          <TeamSelect
            label="Team B"
            value={teamB}
            teams={teams}
            onChange={setTeamB}
          />
        </div>

        {error && (
          <p className="mt-4 text-red-400 text-sm text-center">{error}</p>
        )}

        <button
          onClick={predict}
          disabled={!teamA || !teamB || loading}
          className="mt-6 w-full py-3 rounded-xl bg-blue-600 hover:bg-blue-500 disabled:bg-gray-700 disabled:text-gray-500 font-semibold transition-colors"
        >
          {loading ? "Predicting…" : "Predict Series"}
        </button>
      </div>

      {result && (
        <div className="w-full max-w-2xl mt-8 bg-gray-900 rounded-2xl p-8 shadow-xl">
          <h2 className="text-lg font-semibold text-gray-300 mb-6 text-center">
            Series Win Probability
          </h2>
          <ProbBar team={result.team_a} prob={result.team_a_win_prob} />
          <ProbBar team={result.team_b} prob={result.team_b_win_prob} />
        </div>
      )}
    </main>
  );
}

function TeamSelect({
  label,
  value,
  teams,
  onChange,
}: {
  label: string;
  value: string;
  teams: string[];
  onChange: (v: string) => void;
}) {
  return (
    <div className="flex-1 flex flex-col gap-1">
      <label className="text-xs text-gray-400 font-medium">{label}</label>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
      >
        <option value="">Select team…</option>
        {teams.map((t) => (
          <option key={t} value={t}>
            {t}
          </option>
        ))}
      </select>
    </div>
  );
}

function ProbBar({ team, prob }: { team: string; prob: number }) {
  const pct = Math.round(prob * 100);
  return (
    <div className="mb-4">
      <div className="flex justify-between text-sm mb-1">
        <span className="font-medium">{team}</span>
        <span className="text-blue-400 font-bold">{pct}%</span>
      </div>
      <div className="h-3 bg-gray-800 rounded-full overflow-hidden">
        <div
          className="h-full bg-blue-600 rounded-full transition-all duration-500"
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}
