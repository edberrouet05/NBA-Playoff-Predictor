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

export default function BracketPage() {
  const [schedule, setSchedule] = useState<{ date: string; games: TodayGame[] }[]>([]);
  const [error, setError]       = useState("");

  useEffect(() => {
    fetch(`${API}/api/schedule?days=7`)
      .then((r) => r.json())
      .then((d) => setSchedule(d.schedule ?? []))
      .catch(() => setError("Could not load schedule. Make sure the backend is running."));
  }, []);

  return (
    <main className="max-w-2xl mx-auto px-4 py-10">
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-gray-900">Upcoming Games</h1>
        <p className="text-gray-500 text-sm mt-1">
          Next 7 days · win probability per game
        </p>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 rounded-xl p-4 text-red-600 text-sm mb-6">
          {error}
        </div>
      )}

      {!error && schedule.length === 0 && (
        <div className="bg-white border border-gray-200 rounded-2xl p-8 text-center text-gray-400 text-sm shadow-sm">
          Loading schedule…
        </div>
      )}

      {schedule.map((day) => (
        <div key={day.date} className="mb-6">
          <p className="text-xs text-gray-400 font-semibold mb-2 uppercase tracking-widest">
            {(() => {
              const [y, m, d] = day.date.split("T")[0].split("-").map(Number);
              return new Date(y, m - 1, d).toLocaleDateString("en-US", {
                weekday: "long", month: "long", day: "numeric",
              });
            })()}
          </p>
          <div className="flex flex-col gap-3">
            {day.games.map((g) => <GameCard key={g.game_id} game={g} />)}
          </div>
        </div>
      ))}
    </main>
  );
}

function GameCard({ game }: { game: TodayGame }) {
  const isLive  = game.status === "Live";
  const isFinal = game.status === "Final";

  return (
    <div className="bg-white border border-gray-200 rounded-2xl p-5 shadow-sm">
      <div className="flex items-center justify-between mb-3">
        <span className={`text-xs font-semibold px-2.5 py-0.5 rounded-full ${
          isLive  ? "bg-green-100 text-green-600" :
          isFinal ? "bg-gray-100 text-gray-500"   :
                    "bg-red-100 text-red-600"
        }`}>
          {isLive ? "● LIVE" : game.status_text}
        </span>
        <span className="text-xs text-gray-400">
          Predicted: <span className="text-red-600 font-semibold">{game.predicted_winner}</span>
        </span>
      </div>

      <div className="flex flex-col gap-2">
        <TeamRow
          team={game.away_team} prob={game.away_win_prob} score={game.away_score}
          isWinner={isFinal && game.away_score !== null && game.home_score !== null && game.away_score > game.home_score}
          showScore={isLive || isFinal}
        />
        <TeamRow
          team={game.home_team} prob={game.home_win_prob} score={game.home_score}
          isWinner={isFinal && game.away_score !== null && game.home_score !== null && game.home_score > game.away_score}
          showScore={isLive || isFinal}
        />
      </div>
    </div>
  );
}

function TeamRow({ team, prob, score, isWinner, showScore }: {
  team: string; prob: number; score: number | null; isWinner: boolean; showScore: boolean;
}) {
  return (
    <div className="flex items-center gap-3">
      <span className={`w-44 text-sm font-medium truncate ${isWinner ? "text-red-600 font-semibold" : "text-gray-800"}`}>
        {team}
      </span>
      <div className="flex-1 h-2 bg-gray-100 rounded-full overflow-hidden">
        <div className="h-full bg-red-500 rounded-full" style={{ width: `${prob}%` }} />
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
