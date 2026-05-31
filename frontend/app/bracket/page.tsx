"use client";
import { useEffect, useState } from "react";
import Link from "next/link";

const API = "http://localhost:8000";

interface SeriesEntry {
  team_a: string;
  team_b: string;
  team_a_wins: number;
  team_b_wins: number;
  team_a_series_prob: number;
  team_b_series_prob: number;
  status: "active" | "complete";
  winner: string | null;
}

interface Round {
  round: number;
  name: string;
  series: SeriesEntry[];
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
function getLogoUrl(t: string) {
  const id = TEAM_IDS[getAbbr(t)];
  return id ? `https://cdn.nba.com/logos/nba/${id}/global/L/logo.svg` : "";
}

function TeamLogo({ team, size }: { team: string; size: string }) {
  const [err, setErr] = useState(false);
  const url = getLogoUrl(team);
  if (!url || err) return <div className={`${size} rounded-full flex-shrink-0`} style={{ background: getColor(team) }} />;
  return <img src={url} alt={team} className={`${size} object-contain flex-shrink-0`} onError={() => setErr(true)} />;
}

function SeriesCard({ s }: { s: SeriesEntry }) {
  const aLeads  = s.team_a_wins > s.team_b_wins;
  const bLeads  = s.team_b_wins > s.team_a_wins;
  const done    = s.status === "complete";
  const matchupUrl = `/predictions?team_a=${encodeURIComponent(s.team_a)}&team_b=${encodeURIComponent(s.team_b)}`;

  return (
    <Link href={matchupUrl} className="block group">
      <div className={`bg-white dark:bg-gray-900 border rounded-2xl p-4 shadow-sm transition-colors group-hover:bg-gray-50 dark:group-hover:bg-gray-800 ${
        done ? "border-gray-200 dark:border-gray-700 opacity-75" : "border-gray-100 dark:border-transparent"
      }`}>
        {done && s.winner && (
          <div className="text-[10px] font-bold uppercase tracking-widest text-green-600 dark:text-green-400 mb-2">
            {getAbbr(s.winner)} wins series
          </div>
        )}

        {/* Team A */}
        <div className={`flex items-center justify-between mb-2 ${done && s.winner !== s.team_a ? "opacity-40" : ""}`}>
          <div className="flex items-center gap-2">
            <TeamLogo team={s.team_a} size="w-7 h-7" />
            <span className="text-sm font-bold text-gray-900 dark:text-white">{getAbbr(s.team_a)}</span>
          </div>
          <div className="flex items-center gap-3">
            <span className={`text-xs font-medium ${aLeads ? "text-gray-900 dark:text-white" : "text-gray-400"}`}>
              {s.team_a_series_prob}%
            </span>
            <span className={`text-lg font-bold w-5 text-center ${aLeads ? "text-gray-900 dark:text-white" : "text-gray-400"}`}>
              {s.team_a_wins}
            </span>
          </div>
        </div>

        {/* Team B */}
        <div className={`flex items-center justify-between ${done && s.winner !== s.team_b ? "opacity-40" : ""}`}>
          <div className="flex items-center gap-2">
            <TeamLogo team={s.team_b} size="w-7 h-7" />
            <span className="text-sm font-bold text-gray-900 dark:text-white">{getAbbr(s.team_b)}</span>
          </div>
          <div className="flex items-center gap-3">
            <span className={`text-xs font-medium ${bLeads ? "text-gray-900 dark:text-white" : "text-gray-400"}`}>
              {s.team_b_series_prob}%
            </span>
            <span className={`text-lg font-bold w-5 text-center ${bLeads ? "text-gray-900 dark:text-white" : "text-gray-400"}`}>
              {s.team_b_wins}
            </span>
          </div>
        </div>

        {/* Probability bar */}
        {!done && (
          <div className="mt-3 h-[3px] flex rounded-full overflow-hidden">
            <div style={{ width: `${s.team_a_series_prob}%`, background: getColor(s.team_a) }} className="h-full" />
            <div style={{ flex: 1, background: getColor(s.team_b) }} className="h-full" />
          </div>
        )}
      </div>
    </Link>
  );
}

export default function BracketPage() {
  const [rounds, setRounds]   = useState<Round[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const load = () =>
      fetch(`${API}/api/bracket`)
        .then(r => r.json())
        .then(d => setRounds(d.rounds ?? []))
        .finally(() => setLoading(false));

    load();
    const id = setInterval(load, 60_000);
    return () => clearInterval(id);
  }, []);

  const totalSeries  = rounds.flatMap(r => r.series).length;
  const doneSeries   = rounds.flatMap(r => r.series).filter(s => s.status === "complete").length;

  return (
    <main className="px-6 py-8">
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Playoff Bracket</h1>
        <p className="text-sm text-gray-500 mt-1">
          Live series scores · model win probability · click a series for full prediction
        </p>
      </div>

      {loading && (
        <div className="bg-white dark:bg-gray-900 rounded-2xl p-10 text-center text-gray-400 text-sm shadow-sm">
          Loading bracket…
        </div>
      )}

      {!loading && rounds.length === 0 && (
        <div className="bg-white dark:bg-gray-900 rounded-2xl p-10 text-center text-gray-400 text-sm shadow-sm">
          No playoff games found yet this season.
        </div>
      )}

      {!loading && rounds.length > 0 && (
        <>
          {/* Progress bar */}
          <div className="bg-white dark:bg-gray-900 border border-gray-100 dark:border-transparent shadow-sm rounded-2xl px-5 py-4 mb-6 flex items-center justify-between">
            <div>
              <p className="text-sm font-bold text-gray-900 dark:text-white">
                {rounds[rounds.length - 1].name}
              </p>
              <p className="text-xs text-gray-500 mt-0.5">{doneSeries} of {totalSeries} series completed</p>
            </div>
            <div className="w-32 h-2 bg-gray-100 dark:bg-gray-800 rounded-full overflow-hidden">
              <div
                className="h-full bg-green-500 rounded-full transition-all"
                style={{ width: `${totalSeries > 0 ? (doneSeries / totalSeries) * 100 : 0}%` }}
              />
            </div>
          </div>

          {/* Rounds */}
          <div className="flex flex-col gap-8">
            {rounds.map(round => (
              <div key={round.round}>
                <div className="flex items-center gap-3 mb-4">
                  <span className="text-xs font-bold uppercase tracking-widest text-gray-400">
                    Round {round.round}
                  </span>
                  <span className="text-sm font-bold text-gray-900 dark:text-white">{round.name}</span>
                  <span className="ml-auto text-xs text-gray-400">
                    {round.series.filter(s => s.status === "complete").length}/{round.series.length} done
                  </span>
                </div>
                <div className={`grid gap-4 ${
                  round.series.length >= 4 ? "grid-cols-2 lg:grid-cols-4" :
                  round.series.length === 2 ? "grid-cols-1 sm:grid-cols-2 max-w-lg" :
                  "grid-cols-1 max-w-xs"
                }`}>
                  {round.series.map((s, i) => <SeriesCard key={i} s={s} />)}
                </div>
              </div>
            ))}
          </div>
        </>
      )}
    </main>
  );
}
