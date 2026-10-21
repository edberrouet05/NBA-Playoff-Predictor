"use client";
import { useEffect, useState } from "react";
import { Glossary, PctCell, Rank, SortTable, signed, useUrlTab, type Col } from "../../components/PowerTable";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// ── Types (mirror /api/nfl/power and /api/nfl/projections) ─────────────────────

interface PowerTeam {
  team: string;
  wins: number; losses: number; ties: number;
  power: number; rank: number; trend: number | null;
  off: number; def: number; st: number;
  sos_rank: number | null; rem_sos_rank: number | null;
  elo: number; qb_name: string; qb_epa: number; qb_rank: number;
  off_epa: number; def_epa: number; off_pass_epa: number; def_pass_epa: number;
  off_epa_rank: number; def_epa_rank: number; off_pass_epa_rank: number; def_pass_epa_rank: number;
  st_rank: number;
}
interface PowerData { season: number; trend_since_week: number | null; teams: PowerTeam[]; }

interface ProjTeam {
  team: string; power: number; projected_wins: number;
  playoff_pct: number; division_pct: number; top_seed_pct: number; conf_pct: number; sb_win_pct: number;
}
interface ProjData { week: number; simulations: number; games_remaining: number; teams: ProjTeam[]; }

type Tab = "power" | "projections" | "efficiencies";

// ── Team metadata ──────────────────────────────────────────────────────────────

const NFL_ABBR: Record<string, string> = {
  "Arizona Cardinals": "ARI", "Atlanta Falcons": "ATL", "Baltimore Ravens": "BAL",
  "Buffalo Bills": "BUF", "Carolina Panthers": "CAR", "Chicago Bears": "CHI",
  "Cincinnati Bengals": "CIN", "Cleveland Browns": "CLE", "Dallas Cowboys": "DAL",
  "Denver Broncos": "DEN", "Detroit Lions": "DET", "Green Bay Packers": "GB",
  "Houston Texans": "HOU", "Indianapolis Colts": "IND", "Jacksonville Jaguars": "JAX",
  "Kansas City Chiefs": "KC", "Las Vegas Raiders": "LV", "Los Angeles Chargers": "LAC",
  "Los Angeles Rams": "LAR", "Miami Dolphins": "MIA", "Minnesota Vikings": "MIN",
  "New England Patriots": "NE", "New Orleans Saints": "NO", "New York Giants": "NYG",
  "New York Jets": "NYJ", "Philadelphia Eagles": "PHI", "Pittsburgh Steelers": "PIT",
  "San Francisco 49ers": "SF", "Seattle Seahawks": "SEA", "Tampa Bay Buccaneers": "TB",
  "Tennessee Titans": "TEN", "Washington Commanders": "WSH",
};

function getAbbr(t: string) { return NFL_ABBR[t] ?? t.split(" ").pop()?.slice(0, 3).toUpperCase() ?? "???"; }

function TeamLogo({ team }: { team: string }) {
  // Remember which URL failed, so a new team gets a fresh attempt
  const [failedSrc, setFailedSrc] = useState<string | null>(null);
  const abbr = getAbbr(team);
  const url = `https://a.espncdn.com/i/teamlogos/nfl/500/${abbr.toLowerCase()}.png`;
  if (failedSrc === url || abbr === "???") {
    return <span className="w-6 h-6 flex-shrink-0 flex items-center justify-center text-[9px] font-bold text-gray-500">{abbr.slice(0, 2)}</span>;
  }
  return <img src={url} alt={team} className="w-6 h-6 object-contain flex-shrink-0" onError={() => setFailedSrc(url)} />;
}

// ── Formatting ─────────────────────────────────────────────────────────────────

function Trend({ v }: { v: number | null }) {
  if (v === null || v === 0) return <span className="text-gray-400">–</span>;
  const up = v > 0;
  return (
    <span className={`font-semibold tabular-nums ${up ? "text-green-600 dark:text-green-400" : "text-red-500 dark:text-red-400"}`}
      title={`${up ? "Up" : "Down"} ${Math.abs(v)} spot${Math.abs(v) === 1 ? "" : "s"}`}>
      {up ? "↑" : "↓"}{Math.abs(v)}
    </span>
  );
}

// ── Column definitions ─────────────────────────────────────────────────────────

const POWER_COLS: Col<PowerTeam>[] = [
  { key: "wlt", label: "W-L-T", title: "Record this season.",
    value: r => r.wins + 0.5 * r.ties, render: r => `${r.wins}-${r.losses}-${r.ties}` },
  { key: "power", label: "POWER", group: "Power index", highlight: true,
    title: "Team strength in points: expected margin vs an average NFL team on a neutral field, from the prediction model (Elo, EPA efficiency, starting QB).",
    value: r => r.power, render: r => signed(r.power) },
  { key: "rank", label: "RK", group: "Power index", lowerIsBetter: true,
    title: "Power index rank among all 32 teams.", value: r => r.rank, render: r => r.rank },
  { key: "trend", label: "TREND", group: "Power index",
    title: "Change in power rank since last week's ranking.", value: r => r.trend, render: r => <Trend v={r.trend} /> },
  { key: "off", label: "OFF", group: "Power index",
    title: "Offense: expected points added per game by the offense (EPA), weighted toward recent games. 0 = average.",
    value: r => r.off, render: r => signed(r.off) },
  { key: "def", label: "DEF", group: "Power index",
    title: "Defense: expected points the defense takes away per game (EPA allowed, sign flipped so higher = better). 0 = average.",
    value: r => r.def, render: r => signed(r.def) },
  { key: "st", label: "ST", group: "Power index",
    title: "Special teams: expected points added per game on kickoffs, punts, field goals and extra points. 0 = average.",
    value: r => r.st, render: r => signed(r.st) },
  { key: "sos", label: "SOS", group: "Ranks", lowerIsBetter: true,
    title: "Strength of schedule so far: rank of the average power of opponents already played (1 = toughest).",
    value: r => r.sos_rank, render: r => r.sos_rank ?? "–" },
  { key: "rem_sos", label: "REM SOS", group: "Ranks", lowerIsBetter: true,
    title: "Remaining strength of schedule: rank of the average power of opponents still to play (1 = toughest).",
    value: r => r.rem_sos_rank, render: r => r.rem_sos_rank ?? "–" },
];

const PROJ_COLS: Col<ProjTeam>[] = [
  { key: "power", label: "POWER", highlight: true, title: "Power index (points vs an average team, neutral field).",
    value: r => r.power, render: r => signed(r.power) },
  { key: "projected_wins", label: "PROJ W", title: "Average final regular-season wins across all simulations.",
    value: r => r.projected_wins, render: r => r.projected_wins.toFixed(1) },
  { key: "playoff_pct", label: "PLAYOFFS", group: "Chance to…", title: "Chance to make the playoffs (7 teams per conference).",
    value: r => r.playoff_pct, render: r => <PctCell v={r.playoff_pct} /> },
  { key: "division_pct", label: "WIN DIV", group: "Chance to…", title: "Chance to win the division.",
    value: r => r.division_pct, render: r => <PctCell v={r.division_pct} /> },
  { key: "top_seed_pct", label: "#1 SEED", group: "Chance to…", title: "Chance to be the conference's #1 seed (first-round bye).",
    value: r => r.top_seed_pct, render: r => <PctCell v={r.top_seed_pct} /> },
  { key: "conf_pct", label: "WIN CONF", group: "Chance to…", title: "Chance to win the conference and reach the Super Bowl.",
    value: r => r.conf_pct, render: r => <PctCell v={r.conf_pct} /> },
  { key: "sb_win_pct", label: "WIN SB", group: "Chance to…", title: "Chance to win the Super Bowl.",
    value: r => r.sb_win_pct, render: r => <PctCell v={r.sb_win_pct} /> },
];

const EFF_COLS: Col<PowerTeam>[] = [
  { key: "off_epa", label: "OFF EPA", group: "Per play", highlight: true,
    title: "Offensive EPA per play (passes and runs). Higher = better. League average ≈ 0.",
    value: r => r.off_epa, render: r => <>{signed(r.off_epa, 3)}<Rank r={r.off_epa_rank} /></> },
  { key: "def_epa", label: "DEF EPA", group: "Per play", lowerIsBetter: true,
    title: "EPA per play allowed by the defense. Lower = better.",
    value: r => r.def_epa, render: r => <>{signed(r.def_epa, 3)}<Rank r={r.def_epa_rank} /></> },
  { key: "off_pass_epa", label: "PASS OFF", group: "Per play",
    title: "Offensive EPA per pass play. Higher = better.",
    value: r => r.off_pass_epa, render: r => <>{signed(r.off_pass_epa, 3)}<Rank r={r.off_pass_epa_rank} /></> },
  { key: "def_pass_epa", label: "PASS DEF", group: "Per play", lowerIsBetter: true,
    title: "EPA per pass play allowed. Lower = better.",
    value: r => r.def_pass_epa, render: r => <>{signed(r.def_pass_epa, 3)}<Rank r={r.def_pass_epa_rank} /></> },
  { key: "st", label: "ST PTS/G", group: "Per game",
    title: "Special-teams expected points added per game.",
    value: r => r.st, render: r => <>{signed(r.st)}<Rank r={r.st_rank} /></> },
  { key: "qb", label: "STARTING QB", group: "Quarterback",
    title: "Most recent starting quarterback and his EPA per dropback (weighted toward recent games).",
    value: r => r.qb_epa,
    render: r => <span className="inline-flex items-baseline gap-1.5"><span className="text-gray-500 text-xs">{r.qb_name}</span>{signed(r.qb_epa, 3)}<Rank r={r.qb_rank} /></span> },
  { key: "elo", label: "ELO", title: "Elo rating (1505 = average). Updates after every game; carries over between seasons.",
    value: r => r.elo, render: r => r.elo },
];

// ── Page ───────────────────────────────────────────────────────────────────────

export default function NFLPowerPage() {
  // ?tab=projections|efficiencies opens a tab directly (shareable links)
  const [tab, selectTab] = useUrlTab<Tab>(["power", "projections", "efficiencies"], "power");
  const [power, setPower] = useState<PowerData | null>(null);
  const [proj, setProj] = useState<ProjData | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    fetch(`${API}/api/nfl/power`)
      .then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); })
      .then(setPower)
      .catch(e => setError(`Could not load the power index. (${e.message})`));
    fetch(`${API}/api/nfl/projections`)
      .then(r => (r.ok ? r.json() : null))
      .then(setProj)
      .catch(() => setProj(null));
  }, []);

  const tabs: { id: Tab; label: string }[] = [
    { id: "power", label: "Power Index" },
    { id: "projections", label: "Projections" },
    { id: "efficiencies", label: "Efficiencies" },
  ];
  const activeCols = tab === "power" ? POWER_COLS : tab === "projections" ? PROJ_COLS : EFF_COLS;

  return (
    <main className="px-4 md:px-6 py-6 md:py-8">
      <div className="mb-5">
        <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Power Index {power?.season ?? ""}</h1>
        <p className="text-gray-500 text-sm mt-1">How strong every team really is, where each season is headed, and why.</p>
      </div>

      <div className="flex border-b border-gray-200 dark:border-gray-800 mb-4">
        {tabs.map(t => (
          <button key={t.id} onClick={() => selectTab(t.id)}
            className={`flex-1 sm:flex-none sm:px-8 py-2.5 text-sm font-bold border-b-2 -mb-px transition-colors ${
              tab === t.id ? "border-red-500 text-gray-900 dark:text-white" : "border-transparent text-gray-400 hover:text-gray-600 dark:hover:text-gray-200"
            }`}>
            {t.label}
          </button>
        ))}
      </div>

      {error && (
        <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800/40 rounded-xl p-4 text-red-600 dark:text-red-400 text-sm mb-4">{error}</div>
      )}

      <div className="bg-white dark:bg-gray-900 border border-gray-100 dark:border-transparent shadow-sm rounded-2xl overflow-hidden">
        {tab === "projections" ? (
          proj ? <SortTable rows={proj.teams} cols={PROJ_COLS} initial="sb_win_pct" league="nfl" logo={r => <TeamLogo team={r.team} />} />
               : <p className="p-8 text-center text-sm text-gray-400">Running season simulations…</p>
        ) : power ? (
          <SortTable rows={power.teams} cols={tab === "power" ? POWER_COLS : EFF_COLS} initial={tab === "power" ? "power" : "off_epa"}
            league="nfl" logo={r => <TeamLogo team={r.team} />} />
        ) : !error && (
          <p className="p-8 text-center text-sm text-gray-400">Loading…</p>
        )}
      </div>

      <div className="mt-5 text-xs text-gray-500 dark:text-gray-400 space-y-3">
        {tab === "power" && (
          <p>
            Power is the model&apos;s expected point margin against an average team on a neutral field. OFF, DEF and ST are
            separate play-by-play measures (expected points added per game) and don&apos;t add up to Power exactly, since
            Power also uses Elo and the starting QB.{power?.trend_since_week ? ` Trend compares with the ranking entering week ${power.trend_since_week}.` : ""}
          </p>
        )}
        {tab === "projections" && proj && (
          <p>
            {proj.simulations.toLocaleString()} simulations of the {proj.games_remaining} remaining regular-season games (model
            win probabilities) followed by the playoffs (power ratings, small home edge for the higher seed). Ties in the
            standings are broken at random, not by official NFL tiebreakers.
          </p>
        )}
        <Glossary cols={activeCols} />
      </div>
    </main>
  );
}
