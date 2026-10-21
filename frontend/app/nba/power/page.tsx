"use client";
import { useEffect, useState } from "react";
import { Glossary, PctCell, Rank, SortTable, signed, useUrlTab, type Col } from "../../components/PowerTable";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// ── Types (mirror /api/nba/projections) ────────────────────────────────────────

interface NBATeam {
  team: string; abbr: string; conference: "East" | "West";
  wins: number; losses: number;
  power: number; power_rank: number; elo: number;
  off_rtg: number; def_rtg: number; net_rtg: number; pace: number;
  off_rank: number; def_rank: number;
  sos_rank: number | null; rem_sos_rank: number | null;
  projected_wins: number; playoff_pct: number; top6_pct: number; top_seed_pct: number;
  conf_pct: number; title_pct: number;
}
interface ProjData { season: string; simulations: number; games_remaining: number; teams: NBATeam[]; }

type Tab = "power" | "projections";
type Conf = "all" | "East" | "West";

function TeamLogo({ abbr, team }: { abbr: string; team: string }) {
  // Remember which URL failed, so a new team gets a fresh attempt
  const [failedSrc, setFailedSrc] = useState<string | null>(null);
  const url = `https://a.espncdn.com/i/teamlogos/nba/500/${abbr.toLowerCase()}.png`;
  if (failedSrc === url) {
    return <span className="w-6 h-6 flex-shrink-0 flex items-center justify-center text-[9px] font-bold text-gray-500">{abbr.slice(0, 3)}</span>;
  }
  return <img src={url} alt={team} className="w-6 h-6 object-contain flex-shrink-0" onError={() => setFailedSrc(url)} />;
}

// ── Column definitions ─────────────────────────────────────────────────────────

const POWER_COLS: Col<NBATeam>[] = [
  { key: "wl", label: "W-L", title: "Record this regular season.",
    value: r => r.wins - r.losses, render: r => `${r.wins}-${r.losses}` },
  { key: "power", label: "POWER", group: "Power index", highlight: true,
    title: "Team strength in points: expected margin vs an average NBA team on a neutral floor, from the prediction model (Elo and recent point margin).",
    value: r => r.power, render: r => signed(r.power) },
  { key: "rank", label: "RK", group: "Power index", lowerIsBetter: true,
    title: "Power index rank among all 30 teams.", value: r => r.power_rank, render: r => r.power_rank },
  { key: "elo", label: "ELO", group: "Power index",
    title: "Elo rating (1505 = average). Updates after every game; carries over between seasons, pulled 1/4 toward average.",
    value: r => r.elo, render: r => r.elo },
  { key: "off_rtg", label: "OFF RTG", group: "Efficiency",
    title: "Points scored per 100 possessions (estimated from shots and free throws), weighted toward recent games.",
    value: r => r.off_rtg, render: r => <>{r.off_rtg.toFixed(1)}<Rank r={r.off_rank} /></> },
  { key: "def_rtg", label: "DEF RTG", group: "Efficiency", lowerIsBetter: true,
    title: "Points allowed per 100 possessions, weighted toward recent games. Lower = better.",
    value: r => r.def_rtg, render: r => <>{r.def_rtg.toFixed(1)}<Rank r={r.def_rank} /></> },
  { key: "net_rtg", label: "NET", group: "Efficiency",
    title: "Offensive minus defensive rating.", value: r => r.net_rtg, render: r => signed(r.net_rtg) },
  { key: "pace", label: "PACE", group: "Efficiency",
    title: "Estimated possessions per game.", value: r => r.pace, render: r => r.pace.toFixed(1) },
  { key: "sos", label: "SOS", group: "Ranks", lowerIsBetter: true,
    title: "Strength of schedule so far: rank of the average power of opponents already played (1 = toughest).",
    value: r => r.sos_rank, render: r => r.sos_rank ?? "–" },
  { key: "rem_sos", label: "REM SOS", group: "Ranks", lowerIsBetter: true,
    title: "Remaining strength of schedule: rank of the average power of opponents still to play (1 = toughest).",
    value: r => r.rem_sos_rank, render: r => r.rem_sos_rank ?? "–" },
];

const PROJ_COLS: Col<NBATeam>[] = [
  { key: "power", label: "POWER", highlight: true, title: "Power index (points vs an average team, neutral floor).",
    value: r => r.power, render: r => signed(r.power) },
  { key: "projected_wins", label: "PROJ W", title: "Average final regular-season wins (out of 82) across all simulations.",
    value: r => r.projected_wins, render: r => r.projected_wins.toFixed(1) },
  { key: "playoff_pct", label: "PLAYOFFS", group: "Chance to…", title: "Chance to make the playoffs: a top-6 seed, or through the play-in (seeds 7-10).",
    value: r => r.playoff_pct, render: r => <PctCell v={r.playoff_pct} /> },
  { key: "top6_pct", label: "TOP 6", group: "Chance to…", title: "Chance to finish in the conference's top 6 and skip the play-in.",
    value: r => r.top6_pct, render: r => <PctCell v={r.top6_pct} /> },
  { key: "top_seed_pct", label: "#1 SEED", group: "Chance to…", title: "Chance to be the conference's #1 seed.",
    value: r => r.top_seed_pct, render: r => <PctCell v={r.top_seed_pct} /> },
  { key: "conf_pct", label: "WIN CONF", group: "Chance to…", title: "Chance to win the conference and reach the NBA Finals.",
    value: r => r.conf_pct, render: r => <PctCell v={r.conf_pct} /> },
  { key: "title_pct", label: "WIN TITLE", group: "Chance to…", title: "Chance to win the NBA championship.",
    value: r => r.title_pct, render: r => <PctCell v={r.title_pct} /> },
];

// ── Page ───────────────────────────────────────────────────────────────────────

export default function NBAPowerPage() {
  const [tab, selectTab] = useUrlTab<Tab>(["power", "projections"], "power");
  const [conf, setConf] = useState<Conf>("all");
  const [data, setData] = useState<ProjData | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    fetch(`${API}/api/nba/projections`)
      .then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); })
      .then(setData)
      .catch(e => setError(`Could not load the power index. (${e.message})`));
  }, []);

  const cols = tab === "power" ? POWER_COLS : PROJ_COLS;
  const rows = data ? data.teams.filter(t => conf === "all" || t.conference === conf) : [];

  return (
    <main className="px-4 md:px-6 py-6 md:py-8">
      <div className="mb-5">
        <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Power Index {data?.season ?? ""}</h1>
        <p className="text-gray-500 text-sm mt-1">How strong every team really is, and where the season is headed.</p>
      </div>

      <div className="flex flex-wrap items-end justify-between gap-3 border-b border-gray-200 dark:border-gray-800 mb-4">
        <div className="flex flex-1 sm:flex-none">
          {([["power", "Power Index"], ["projections", "Projections"]] as [Tab, string][]).map(([id, label]) => (
            <button key={id} onClick={() => selectTab(id)}
              className={`flex-1 sm:flex-none sm:px-8 py-2.5 text-sm font-bold border-b-2 -mb-px transition-colors ${
                tab === id ? "border-red-500 text-gray-900 dark:text-white" : "border-transparent text-gray-400 hover:text-gray-600 dark:hover:text-gray-200"
              }`}>
              {label}
            </button>
          ))}
        </div>
        <div className="flex gap-1 pb-2">
          {(["all", "East", "West"] as Conf[]).map(c => (
            <button key={c} onClick={() => setConf(c)}
              className={`px-3 py-1 rounded-full text-xs font-semibold transition-colors ${
                conf === c ? "bg-gray-900 text-white dark:bg-white dark:text-gray-900" : "bg-gray-100 text-gray-500 hover:bg-gray-200 dark:bg-gray-800 dark:text-gray-400"
              }`}>
              {c === "all" ? "All" : c}
            </button>
          ))}
        </div>
      </div>

      {error && (
        <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800/40 rounded-xl p-4 text-red-600 dark:text-red-400 text-sm mb-4">{error}</div>
      )}

      <div className="bg-white dark:bg-gray-900 border border-gray-100 dark:border-transparent shadow-sm rounded-2xl overflow-hidden">
        {data ? (
          <SortTable key={tab} rows={rows} cols={cols} initial={tab === "power" ? "power" : "title_pct"}
            league="nba" logo={r => <TeamLogo abbr={r.abbr} team={r.team} />} />
        ) : !error && (
          <p className="p-8 text-center text-sm text-gray-400">Running season simulations…</p>
        )}
      </div>

      <div className="mt-5 text-xs text-gray-500 dark:text-gray-400 space-y-3">
        {tab === "power" && (
          <p>
            Power is the model&apos;s expected point margin against an average team on a neutral floor. The efficiency
            columns are recency-weighted and carry over from last season, so they mean something from opening night.
          </p>
        )}
        {tab === "projections" && data && (
          <p>
            {data.simulations.toLocaleString()} simulations of the {data.games_remaining} remaining regular-season games (model
            win probabilities, with rest and back-to-backs from the schedule), then the play-in and best-of-7 playoff series
            (power ratings, home court for the higher seed). Ties in the standings are broken at random, not by official NBA
            tiebreakers.
          </p>
        )}
        <Glossary cols={cols} />
      </div>
    </main>
  );
}
