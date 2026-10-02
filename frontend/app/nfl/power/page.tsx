"use client";
import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { teamHref } from "../../components/teamLinks";

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
  const [err, setErr] = useState(false);
  const abbr = getAbbr(team);
  if (err || abbr === "???") {
    return <span className="w-6 h-6 flex-shrink-0 flex items-center justify-center text-[9px] font-bold text-gray-500">{abbr.slice(0, 2)}</span>;
  }
  return <img src={`https://a.espncdn.com/i/teamlogos/nfl/500/${abbr.toLowerCase()}.png`} alt={team}
    className="w-6 h-6 object-contain flex-shrink-0" onError={() => setErr(true)} />;
}

// ── Formatting ─────────────────────────────────────────────────────────────────

const signed = (v: number, d = 1) => `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v).toFixed(d)}`;

function fmtPct(v: number): string {
  if (v >= 99.95) return ">99%";
  if (v > 0 && v < 0.5) return "<1%";
  return `${Math.round(v)}%`;
}

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

function PctCell({ v }: { v: number }) {
  // Magnitude as a single-hue fill behind the number; the number stays in text ink
  const alpha = 0.06 + (v / 100) * 0.34;
  return (
    <span className="inline-block min-w-[3.25rem] px-1.5 py-0.5 rounded-md text-xs font-semibold tabular-nums text-gray-800 dark:text-gray-100"
      style={{ background: `rgba(59, 130, 246, ${alpha})` }}>
      {fmtPct(v)}
    </span>
  );
}

function Rank({ r }: { r: number }) {
  return <span className="ml-1 text-[10px] text-gray-400 tabular-nums">#{r}</span>;
}

// ── Sortable table ─────────────────────────────────────────────────────────────

interface Col<T> {
  key: string;
  label: string;
  title: string;                // header tooltip / glossary text
  value: (r: T) => number | string | null;
  render: (r: T) => React.ReactNode;
  lowerIsBetter?: boolean;      // default sort direction
  group?: string;
  highlight?: boolean;
}

function SortTable<T extends { team: string }>({ rows, cols, initial }: {
  rows: T[]; cols: Col<T>[]; initial: string;
}) {
  const [sortKey, setSortKey] = useState(initial);
  const [asc, setAsc] = useState(!!cols.find(c => c.key === initial)?.lowerIsBetter);
  const col = cols.find(c => c.key === sortKey) ?? cols[0];
  const sorted = useMemo(() => [...rows].sort((a, b) => {
    const va = col.value(a), vb = col.value(b);
    if (va === null) return 1;
    if (vb === null) return -1;
    const cmp = typeof va === "string" ? va.localeCompare(String(vb)) : (va as number) - (vb as number);
    return asc ? cmp : -cmp;
  }), [rows, col, asc]);

  const groups: { name: string; span: number }[] = [];
  cols.forEach(c => {
    const g = c.group ?? "";
    if (groups.length && groups[groups.length - 1].name === g) groups[groups.length - 1].span++;
    else groups.push({ name: g, span: 1 });
  });
  const hasGroups = groups.some(g => g.name);

  const onSort = (c: Col<T>) => {
    if (c.key === sortKey) setAsc(a => !a);
    else { setSortKey(c.key); setAsc(!!c.lowerIsBetter); }
  };

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          {hasGroups && (
            <tr>
              <th className="sticky left-0 bg-white dark:bg-gray-900" />
              {groups.map((g, i) => (
                <th key={i} colSpan={g.span}
                  className={`px-2 pt-3 pb-1 text-[10px] font-bold uppercase tracking-widest text-gray-400 text-center ${g.name ? "border-b border-gray-100 dark:border-gray-800" : ""}`}>
                  {g.name}
                </th>
              ))}
            </tr>
          )}
          <tr className="border-b border-gray-100 dark:border-gray-800">
            <th className="sticky left-0 z-10 bg-white dark:bg-gray-900 px-4 py-2 text-left text-xs font-semibold text-gray-400">Team</th>
            {cols.map(c => (
              <th key={c.key} title={c.title}
                className={`px-2 py-2 text-right text-xs font-semibold whitespace-nowrap cursor-pointer select-none ${
                  c.key === sortKey ? "text-gray-900 dark:text-white" : "text-gray-400 hover:text-gray-600 dark:hover:text-gray-200"
                } ${c.highlight ? "bg-blue-50/70 dark:bg-blue-500/10" : ""}`}
                onClick={() => onSort(c)}>
                <span className="underline decoration-dotted decoration-gray-300 underline-offset-2">{c.label}</span>
                {c.key === sortKey && <span className="ml-0.5">{asc ? "▲" : "▼"}</span>}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sorted.map(r => (
            <tr key={r.team} className="border-b last:border-0 border-gray-50 dark:border-gray-800/60 hover:bg-gray-50 dark:hover:bg-gray-800/40">
              <td className="sticky left-0 z-10 bg-white dark:bg-gray-900 px-4 py-2.5">
                <div className="flex items-center gap-2.5 min-w-[11rem]">
                  <TeamLogo team={r.team} />
                  <Link href={teamHref("nfl", r.team)} className="font-medium text-gray-800 dark:text-gray-200 whitespace-nowrap hover:underline">{r.team}</Link>
                </div>
              </td>
              {cols.map(c => (
                <td key={c.key} className={`px-2 py-2.5 text-right tabular-nums text-gray-700 dark:text-gray-300 whitespace-nowrap ${c.highlight ? "bg-blue-50/70 dark:bg-blue-500/10 font-semibold text-gray-900 dark:text-white" : ""}`}>
                  {c.render(r)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
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
  const [tab, setTab] = useState<Tab>("power");
  const [power, setPower] = useState<PowerData | null>(null);
  const [proj, setProj] = useState<ProjData | null>(null);
  const [error, setError] = useState("");

  // ?tab=projections|efficiencies opens a tab directly (shareable links)
  useEffect(() => {
    const t = new URLSearchParams(window.location.search).get("tab");
    if (t === "projections" || t === "efficiencies") setTab(t);
  }, []);
  const selectTab = (t: Tab) => {
    setTab(t);
    const url = new URL(window.location.href);
    if (t === "power") url.searchParams.delete("tab"); else url.searchParams.set("tab", t);
    window.history.replaceState(null, "", url);
  };

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
          proj ? <SortTable rows={proj.teams} cols={PROJ_COLS} initial="sb_win_pct" />
               : <p className="p-8 text-center text-sm text-gray-400">Running season simulations…</p>
        ) : power ? (
          <SortTable rows={power.teams} cols={tab === "power" ? POWER_COLS : EFF_COLS} initial={tab === "power" ? "power" : "off_epa"} />
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
        <div>
          <h2 className="text-[11px] font-bold uppercase tracking-widest text-gray-700 dark:text-gray-300 mb-2">Glossary</h2>
          <dl className="grid sm:grid-cols-2 gap-x-8 gap-y-1.5">
            {activeCols.map(c => (
              <div key={c.key}><dt className="inline font-semibold text-gray-700 dark:text-gray-300">{c.label}: </dt><dd className="inline">{c.title}</dd></div>
            ))}
          </dl>
        </div>
      </div>
    </main>
  );
}
