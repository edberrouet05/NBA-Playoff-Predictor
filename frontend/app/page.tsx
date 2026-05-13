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

interface TeamStats {
  off_rtg: number; def_rtg: number; net_rtg: number; pace: number;
  ts_pct: number; tov_pct: number; oreb_pct: number; srs: number;
  point_diff: number; fg3_rate: number; ftr: number; win_streak: number;
}

interface CompareResult {
  team_a: string; team_b: string;
  team_a_stats: TeamStats; team_b_stats: TeamStats;
}

interface InjuryPlayer { name: string; status: string; pts_per_game: number | null; }
interface InjuryData   { factor: number; players: InjuryPlayer[]; }
type InjuryReport = Record<string, InjuryData>;

interface GameDetail {
  compare: CompareResult | null;
  injuries: InjuryReport | null;
}

const EXPAND_STATS = [
  { key: "net_rtg",    label: "Net Rating",      better: 1,  pct: false },
  { key: "off_rtg",    label: "Off Rating",      better: 1,  pct: false },
  { key: "def_rtg",    label: "Def Rating",      better: -1, pct: false },
  { key: "ts_pct",     label: "True Shooting %", better: 1,  pct: true  },
  { key: "tov_pct",    label: "Turnover %",      better: -1, pct: true  },
  { key: "srs",        label: "SRS",             better: 1,  pct: false },
];

const STATUS_COLOR: Record<string, string> = {
  Out:          "bg-red-100 text-red-700",
  Doubtful:     "bg-orange-100 text-orange-700",
  Questionable: "bg-yellow-100 text-yellow-700",
  "Day-To-Day": "bg-yellow-100 text-yellow-700",
};

function fmt(v: number, pct: boolean): string {
  if (pct) return (v * 100).toFixed(1) + "%";
  return v.toFixed(1);
}

export default function BracketPage() {
  const [schedule, setSchedule] = useState<{ date: string; games: TodayGame[] }[]>([]);
  const [error, setError]       = useState("");

  useEffect(() => {
    fetch(`${API}/api/schedule?days=1`)
      .then((r) => r.json())
      .then((d) => setSchedule(d.schedule ?? []))
      .catch(() => setError("Could not load schedule. Make sure the backend is running."));
  }, []);

  return (
    <main className="max-w-2xl mx-auto px-4 py-10">
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-gray-900">Tonight&apos;s Games</h1>
        <p className="text-gray-500 text-sm mt-1">
          Live win probability · injury-adjusted · tap a game for details
        </p>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 rounded-xl p-4 text-red-600 text-sm mb-6">
          {error}
        </div>
      )}

      {!error && schedule.length === 0 && (
        <div className="bg-white border border-gray-200 rounded-2xl p-8 text-center text-gray-400 text-sm shadow-sm">
          Loading tonight&apos;s games…
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

  const [expanded, setExpanded] = useState(false);
  const [detail,   setDetail]   = useState<GameDetail | null>(null);
  const [loading,  setLoading]  = useState(false);

  async function toggle() {
    setExpanded((v) => !v);
    if (detail || loading) return;
    setLoading(true);
    try {
      const [cmp, inj] = await Promise.all([
        fetch(`${API}/api/compare?team_a=${encodeURIComponent(game.away_team)}&team_b=${encodeURIComponent(game.home_team)}`).then((r) => r.json()),
        fetch(`${API}/api/injuries?team_a=${encodeURIComponent(game.away_team)}&team_b=${encodeURIComponent(game.home_team)}`).then((r) => r.json()),
      ]);
      setDetail({ compare: cmp, injuries: inj });
    } catch {
      setDetail({ compare: null, injuries: null });
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="bg-white border border-gray-200 rounded-2xl shadow-sm overflow-hidden">
      {/* Clickable header */}
      <button onClick={toggle} className="w-full text-left p-5 hover:bg-gray-50 transition-colors">
        <div className="flex items-center justify-between mb-3">
          <span className={`text-xs font-semibold px-2.5 py-0.5 rounded-full ${
            isLive  ? "bg-green-100 text-green-600" :
            isFinal ? "bg-gray-100 text-gray-500"   :
                      "bg-red-100 text-red-600"
          }`}>
            {isLive ? "● LIVE" : game.status_text}
          </span>
          <div className="flex items-center gap-3">
            <span className="text-xs text-gray-400">
              Predicted: <span className="text-red-600 font-semibold">{game.predicted_winner}</span>
            </span>
            <span className={`text-gray-300 text-xs transition-transform ${expanded ? "rotate-180" : ""}`}>▼</span>
          </div>
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
      </button>

      {/* Expanded detail */}
      {expanded && (
        <div className="border-t border-gray-100 px-5 pb-5 pt-4">
          {loading && <p className="text-xs text-gray-400 text-center py-3">Loading details…</p>}

          {detail && (
            <div className="flex flex-col gap-5">

              {/* Stats comparison */}
              {detail.compare && (
                <div>
                  <p className="text-xs font-semibold text-gray-400 uppercase tracking-widest mb-3">Stats Comparison</p>
                  <div className="grid grid-cols-[1fr_auto_1fr] gap-x-3 pb-2 mb-1 border-b border-gray-100">
                    <span className="text-center text-xs font-bold text-gray-700">{game.away_team.split(" ").slice(-1)[0]}</span>
                    <span />
                    <span className="text-center text-xs font-bold text-gray-700">{game.home_team.split(" ").slice(-1)[0]}</span>
                  </div>
                  {EXPAND_STATS.map(({ key, label, better, pct }) => {
                    const a = detail.compare!.team_a_stats[key as keyof TeamStats] ?? 0;
                    const b = detail.compare!.team_b_stats[key as keyof TeamStats] ?? 0;
                    const aWins = better !== 0 && (better === 1 ? a > b : a < b);
                    const bWins = better !== 0 && (better === 1 ? b > a : b < a);
                    return (
                      <div key={key} className="grid grid-cols-[1fr_auto_1fr] gap-x-3 items-center py-1.5 border-b border-gray-50 last:border-0">
                        <span className={`text-center text-xs font-semibold ${aWins ? "text-green-600" : "text-gray-400"}`}>{fmt(a, pct)}</span>
                        <span className="text-xs text-gray-400 text-center w-28">{label}</span>
                        <span className={`text-center text-xs font-semibold ${bWins ? "text-green-600" : "text-gray-400"}`}>{fmt(b, pct)}</span>
                      </div>
                    );
                  })}
                </div>
              )}

              {/* Injury report */}
              {detail.injuries && (
                <div>
                  <p className="text-xs font-semibold text-gray-400 uppercase tracking-widest mb-3">Injury Report</p>
                  <div className="grid grid-cols-2 gap-4">
                    <InjuryPanel team={game.away_team} data={detail.injuries[game.away_team]} />
                    <InjuryPanel team={game.home_team} data={detail.injuries[game.home_team]} />
                  </div>
                </div>
              )}

            </div>
          )}
        </div>
      )}
    </div>
  );
}

function InjuryPanel({ team, data }: { team: string; data: InjuryData | undefined }) {
  if (!data) return null;
  const lastName = team.split(" ").slice(-1)[0];
  return (
    <div>
      <p className="text-xs font-bold text-gray-700 mb-2">{lastName}</p>
      {data.players.length === 0 ? (
        <p className="text-xs text-gray-400">No injuries reported</p>
      ) : (
        <div className="flex flex-col gap-1.5">
          {data.players.map((p) => (
            <div key={p.name} className="flex flex-col gap-0.5">
              <span className="text-xs text-gray-700 font-medium leading-tight">{p.name}</span>
              <div className="flex items-center gap-1.5">
                <span className={`text-xs px-1.5 py-0.5 rounded font-semibold ${STATUS_COLOR[p.status] ?? "bg-gray-100 text-gray-600"}`}>
                  {p.status}
                </span>
                {p.pts_per_game !== null && (
                  <span className="text-xs text-gray-400">{p.pts_per_game} ppg</span>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
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
