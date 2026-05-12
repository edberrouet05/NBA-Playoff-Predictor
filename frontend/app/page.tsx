"use client";

import { useEffect, useState } from "react";

const API = "http://localhost:8000";

interface TodayGame {
  game_id: string;
  status: string;
  status_text: string;
  away_team: string;
  home_team: string;
  away_score: number | null;
  home_score: number | null;
  away_win_prob: number;
  home_win_prob: number;
  predicted_winner: string;
}

interface Game {
  game: number;
  winner: string;
  team_a_prob: number;
  team_b_prob: number;
  series_score: string;
  clinching: boolean;
}

interface Outcome {
  result: string;
  team_a_pct: number;
  team_b_pct: number;
}

interface Prediction {
  team_a: string;
  team_b: string;
  team_a_series_prob: number;
  team_b_series_prob: number;
  team_a_game_prob: number;
  team_b_game_prob: number;
  predicted_winner: string;
  games: Game[];
  outcomes: Outcome[];
}

export default function Home() {
  const [teams, setTeams] = useState<string[]>([]);
  const [schedule, setSchedule] = useState<{ date: string; games: TodayGame[] }[]>([]);
  const [scheduleError, setScheduleError] = useState("");
  const [teamA, setTeamA] = useState("");
  const [teamB, setTeamB] = useState("");
  const [result, setResult] = useState<Prediction | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    fetch(`${API}/api/teams`)
      .then((r) => r.json())
      .then(setTeams)
      .catch(() => setError("Backend unreachable. Run: uvicorn api.main:app"));

    fetch(`${API}/api/schedule?days=7`)
      .then((r) => r.json())
      .then((d) => setSchedule(d.schedule ?? []))
      .catch(() => setScheduleError("Could not load schedule."));
  }, []);

  async function predict() {
    if (!teamA || !teamB) return;
    if (teamA === teamB) { setError("Pick two different teams."); return; }
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
    <main className="min-h-screen bg-gray-50 text-gray-900 flex flex-col items-center px-4 py-12">
      <div className="mb-10 text-center">
        <h1 className="text-4xl font-bold mb-1 tracking-tight text-gray-900">
          NBA Playoff Predictor
        </h1>
        <p className="text-gray-500 text-sm">
          Live schedule · Game-by-game simulation · 2025–26 stats
        </p>
      </div>

      {/* ── Schedule ──────────────────────────────────────────────── */}
      <div className="w-full max-w-2xl mb-8">
        <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-widest mb-3">
          Upcoming Games
        </h2>

        {scheduleError && <p className="text-red-600 text-sm">{scheduleError}</p>}

        {!scheduleError && schedule.length === 0 && (
          <div className="bg-white border border-gray-200 rounded-2xl p-6 text-center text-gray-400 text-sm shadow-sm">
            Loading schedule…
          </div>
        )}

        {schedule.map((day) => (
          <div key={day.date} className="mb-6">
            <p className="text-xs text-gray-400 font-medium mb-2 uppercase tracking-widest">
              {(() => { const [y, m, d] = day.date.split("T")[0].split("-").map(Number); return new Date(y, m - 1, d).toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric" }); })()}
            </p>
            <div className="flex flex-col gap-3">
              {day.games.map((g) => (
                <TodayCard key={g.game_id} game={g} />
              ))}
            </div>
          </div>
        ))}
      </div>

      {/* ── Manual matchup ────────────────────────────────────────── */}
      <div className="w-full max-w-2xl bg-white border border-gray-200 rounded-2xl p-8 shadow-sm">
        <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-widest mb-4">
          Custom Matchup
        </h2>
        <div className="flex items-center gap-4">
          <TeamSelect label="Team A" value={teamA} teams={teams} onChange={setTeamA} />
          <span className="text-gray-400 font-bold text-xl pt-6">vs</span>
          <TeamSelect label="Team B" value={teamB} teams={teams} onChange={setTeamB} />
        </div>
        {error && <p className="mt-4 text-red-600 text-sm text-center">{error}</p>}
        <button
          onClick={predict}
          disabled={!teamA || !teamB || loading}
          className="mt-6 w-full py-3 rounded-xl bg-red-600 hover:bg-red-500 disabled:bg-gray-200 disabled:text-gray-400 text-white font-semibold transition-colors"
        >
          {loading ? "Simulating…" : "Predict Series"}
        </button>
      </div>

      {/* ── Prediction results ────────────────────────────────────── */}
      {result && (
        <div className="w-full max-w-2xl mt-6 flex flex-col gap-6">
          <Section title="Series Win Probability">
            <ProbBar team={result.team_a} pct={result.team_a_series_prob} />
            <ProbBar team={result.team_b} pct={result.team_b_series_prob} />
            <div className="mt-4 text-center">
              <span className="text-xs text-gray-400 uppercase tracking-widest">Predicted winner</span>
              <p className="text-xl font-bold text-red-600 mt-1">{result.predicted_winner}</p>
            </div>
          </Section>

          <Section title="Game-by-Game Simulation">
            <p className="text-xs text-gray-400 mb-3">
              Per-game win probability — {result.team_a}: {result.team_a_game_prob}% &nbsp;|&nbsp;
              {result.team_b}: {result.team_b_game_prob}%
            </p>
            <table className="w-full text-sm">
              <thead>
                <tr className="text-gray-400 text-xs uppercase border-b border-gray-200">
                  <th className="text-left pb-2">Game</th>
                  <th className="text-left pb-2">Winner</th>
                  <th className="text-right pb-2">Series</th>
                </tr>
              </thead>
              <tbody>
                {result.games.map((g) => (
                  <tr key={g.game} className={`border-b border-gray-100 ${g.clinching ? "text-red-600 font-semibold" : ""}`}>
                    <td className="py-2 text-gray-400">Game {g.game}</td>
                    <td className="py-2">
                      {g.winner}
                      {g.clinching && <span className="ml-2 text-xs bg-red-100 text-red-600 px-2 py-0.5 rounded-full">Clinches</span>}
                    </td>
                    <td className="py-2 text-right text-gray-400">{g.series_score}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Section>

          <Section title="Series Outcome Distribution (10 000 simulations)">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-gray-400 text-xs uppercase border-b border-gray-200">
                  <th className="text-left pb-2">Result</th>
                  <th className="text-right pb-2">{result.team_a}</th>
                  <th className="text-right pb-2">{result.team_b}</th>
                </tr>
              </thead>
              <tbody>
                {result.outcomes.map((o) => (
                  <tr key={o.result} className="border-b border-gray-100">
                    <td className="py-2 text-gray-500">{o.result}</td>
                    <td className="py-2 text-right text-red-600 font-medium">{o.team_a_pct}%</td>
                    <td className="py-2 text-right text-red-400">{o.team_b_pct}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Section>
        </div>
      )}
    </main>
  );
}

function TodayCard({ game }: { game: TodayGame }) {
  const isLive  = game.status === "Live";
  const isFinal = game.status === "Final";

  return (
    <div className="bg-white border border-gray-200 rounded-2xl p-5 shadow-sm">
      <div className="flex items-center justify-between mb-3">
        <span className={`text-xs font-semibold px-2 py-0.5 rounded-full ${
          isLive  ? "bg-green-100 text-green-600" :
          isFinal ? "bg-gray-100 text-gray-500" :
                    "bg-red-100 text-red-600"
        }`}>
          {isLive ? "● LIVE" : game.status_text}
        </span>
        <span className="text-xs text-gray-400">
          Predicted: <span className="text-red-600 font-medium">{game.predicted_winner}</span>
        </span>
      </div>

      <div className="flex flex-col gap-2">
        <GameTeamRow
          team={game.away_team}
          prob={game.away_win_prob}
          score={game.away_score}
          isWinner={isFinal && game.away_score !== null && game.home_score !== null && game.away_score > game.home_score}
          showScore={isLive || isFinal}
        />
        <GameTeamRow
          team={game.home_team}
          prob={game.home_win_prob}
          score={game.home_score}
          isWinner={isFinal && game.away_score !== null && game.home_score !== null && game.home_score > game.away_score}
          showScore={isLive || isFinal}
        />
      </div>
    </div>
  );
}

function GameTeamRow({ team, prob, score, isWinner, showScore }: {
  team: string; prob: number; score: number | null; isWinner: boolean; showScore: boolean;
}) {
  return (
    <div className="flex items-center gap-3">
      <span className={`w-44 text-sm font-medium truncate ${isWinner ? "text-red-600" : "text-gray-800"}`}>{team}</span>
      <div className="flex-1 h-2 bg-gray-200 rounded-full overflow-hidden">
        <div className="h-full bg-red-600 rounded-full" style={{ width: `${prob}%` }} />
      </div>
      <span className="text-red-600 text-xs font-bold w-10 text-right">{prob}%</span>
      {showScore && score !== null && (
        <span className={`text-sm font-bold w-8 text-right ${isWinner ? "text-red-600" : "text-gray-400"}`}>
          {score}
        </span>
      )}
    </div>
  );
}

function TeamSelect({ label, value, teams, onChange }: {
  label: string; value: string; teams: string[]; onChange: (v: string) => void;
}) {
  return (
    <div className="flex-1 flex flex-col gap-1">
      <label className="text-xs text-gray-500 font-medium">{label}</label>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="bg-white border border-gray-300 rounded-lg px-3 py-2 text-sm text-gray-900 focus:outline-none focus:ring-2 focus:ring-red-500"
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
      <div className="h-3 bg-gray-200 rounded-full overflow-hidden">
        <div className="h-full bg-red-600 rounded-full transition-all duration-500" style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="bg-white border border-gray-200 rounded-2xl p-6 shadow-sm">
      <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-widest mb-4">{title}</h2>
      {children}
    </div>
  );
}
