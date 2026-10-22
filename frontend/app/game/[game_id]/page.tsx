"use client";
import { use, useEffect, useRef, useState } from "react";
import { pickMatchupColors } from "../../components/teamColors";
import Link from "next/link";
import { playerHref, teamHref } from "../../components/teamLinks";
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid,
  ResponsiveContainer, Tooltip, LabelList, ReferenceLine,
} from "recharts";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface TeamStats {
  off_rtg: number; def_rtg: number; net_rtg: number; pace: number;
  ts_pct: number; tov_pct: number; oreb_pct: number; srs: number;
  point_diff: number; fg3_rate: number; ftr: number; win_streak: number;
}
interface CompareResult {
  team_a: string; team_b: string;
  team_a_stats: TeamStats; team_b_stats: TeamStats;
}
interface HistoryPoint  { game: string; team_a_prob: number; team_b_prob: number; series: string; }
// /api/nba/game/{id}/live: our win probability through the game, after each basket
interface LivePoint { minute: number; label: string; away_score: number; home_score: number; away_prob: number; home_prob: number; }
interface BoxPlayer {
  id: string; name: string; position: string; headshot: string | null; starter: boolean; dnp: boolean;
  min: string; pts: string; reb: string; ast: string; fg: string; fg3: string; stl: string; blk: string; tov: string; pm: string;
}
interface Factor { feature: string; away_value: number; home_value: number; impact: number; }  // impact > 0 favours away
interface LiveGame {
  season_type: number; state: "pre" | "in" | "post"; status: string;
  away_team: string; home_team: string; away_score: number; home_score: number;
  pregame_away_prob: number; pregame_home_prob: number; away_prob: number; home_prob: number;
  timeline: LivePoint[];
  away_quarters: (number | null)[]; home_quarters: (number | null)[];
  away_stats: Record<string, string>; home_stats: Record<string, string>;
  away_players: BoxPlayer[]; home_players: BoxPlayer[];
  explanation: Factor[];
}
interface InjuryPlayer { id?: string | null; name: string; status: string; pts_per_game: number | null; }
interface InjuryData   { factor: number; players: InjuryPlayer[]; }
type InjuryReport = Record<string, InjuryData>;

const STATS = [
  { key: "net_rtg",  label: "Net Rating",     better:  1, pct: false },
  { key: "off_rtg",  label: "Off Rating",      better:  1, pct: false },
  { key: "def_rtg",  label: "Def Rating",      better: -1, pct: false },
  { key: "ts_pct",   label: "True Shoot %",    better:  1, pct: true  },
  { key: "tov_pct",  label: "Turnover %",      better: -1, pct: true  },
  { key: "srs",      label: "SRS",             better:  1, pct: false },
];

const STATUS_COLOR: Record<string, string> = {
  Out:          "bg-red-100 dark:bg-red-500/25 text-red-600 dark:text-red-400",
  Doubtful:     "bg-orange-100 dark:bg-orange-500/25 text-orange-600 dark:text-orange-400",
  Questionable: "bg-yellow-100 dark:bg-yellow-500/25 text-yellow-600 dark:text-yellow-400",
  "Day-To-Day": "bg-yellow-100 dark:bg-yellow-500/25 text-yellow-600 dark:text-yellow-400",
};

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
  ATL: "#E03A3E", BOS: "#007A33", BKN: "#9EA0A2",
  CHA: "#00788C", CHI: "#CE1141", CLE: "#860038",
  DAL: "#00538C", DEN: "#FEC524", DET: "#1D428A",
  GSW: "#FFC72C", HOU: "#CE1141", IND: "#FDBB30",
  LAC: "#C8102E", LAL: "#FDB927", MEM: "#5D76A9",
  MIA: "#F9A01B", MIL: "#00471B", MIN: "#236192",
  NOP: "#C8A956", NYK: "#F58426", OKC: "#007AC1",
  ORL: "#0077C0", PHI: "#006BB6", PHX: "#E56020",
  POR: "#E03A3E", SAC: "#5A2D81", SAS: "#9EA0A2",
  TOR: "#CE1141", UTA: "#F9A01B", WAS: "#E31837",
};

// Secondary team colors, used when both primaries look alike
const TEAM_ALT_COLORS: Record<string, string> = {
  ATL: "#C1D32F", BOS: "#BA9653", BKN: "#000000",
  CHA: "#1D1160", CHI: "#000000", CLE: "#FDBB30",
  DAL: "#002B5E", DEN: "#0E2240", DET: "#C8102E",
  GSW: "#1D428A", HOU: "#000000", IND: "#002D62",
  LAC: "#1D428A", LAL: "#552583", MEM: "#12173F",
  MIA: "#98002E", MIL: "#0077C0", MIN: "#78BE20",
  NOP: "#0C2340", NYK: "#006BB6", OKC: "#EF3B24",
  ORL: "#000000", PHI: "#ED174C", PHX: "#1D1160",
  POR: "#000000", SAC: "#63727A", SAS: "#000000",
  TOR: "#000000", UTA: "#002B5C", WAS: "#002B5C",
};

function getAbbr(t: string) { return TEAM_ABBR[t] ?? t.split(" ").pop()?.substring(0, 3).toUpperCase() ?? "???"; }
function teamColorCandidates(t: string): string[] {
  const a = getAbbr(t);
  return [TEAM_COLORS[a] ?? "#555", ...(TEAM_ALT_COLORS[a] ? [TEAM_ALT_COLORS[a]] : [])];
}
// Colors for the matchup on screen, set by the page so both teams are clearly distinct
/** The team's color in this matchup (picked so the two sides contrast), else its usual one. */
type Colors = Record<string, string>;
function getColor(t: string, colors: Colors) { return colors[t] ?? TEAM_COLORS[getAbbr(t)] ?? "#555"; }

const TEAM_IDS: Record<string, number> = {
  ATL: 1610612737, BOS: 1610612738, BKN: 1610612751,
  CHA: 1610612766, CHI: 1610612741, CLE: 1610612739,
  DAL: 1610612742, DEN: 1610612743, DET: 1610612765,
  GSW: 1610612744, HOU: 1610612745, IND: 1610612754,
  LAC: 1610612746, LAL: 1610612747, MEM: 1610612763,
  MIA: 1610612748, MIL: 1610612749, MIN: 1610612750,
  NOP: 1610612740, NYK: 1610612752, OKC: 1610612760,
  ORL: 1610612753, PHI: 1610612755, PHX: 1610612756,
  POR: 1610612757, SAC: 1610612758, SAS: 1610612759,
  TOR: 1610612761, UTA: 1610612762, WAS: 1610612764,
};
function getLogoUrl(t: string) {
  const id = TEAM_IDS[getAbbr(t)];
  return id ? `https://cdn.nba.com/logos/nba/${id}/global/L/logo.svg` : "";
}

function TeamLogo({ team, size, colors }: { team: string; size: string; colors: Colors }) {
  // Remember which URL failed, so a new team/player gets a fresh attempt
  const [failedSrc, setFailedSrc] = useState<string | null>(null);
  const url = getLogoUrl(team);
  if (!url || (failedSrc !== null && failedSrc === url)) {
    return <div className={`${size} rounded-full flex-shrink-0`} style={{ background: getColor(team, colors) }} />;
  }
  return (
    <img src={url} alt={team} className={`${size} object-contain flex-shrink-0`} onError={() => setFailedSrc(url)} />
  );
}
function lastName(t: string) { return t.split(" ").pop() ?? t; }
function fmt(v: number, pct: boolean) { return pct ? (v * 100).toFixed(1) + "%" : v.toFixed(1); }

function barPcts(a: number, b: number, better: number) {
  if (better === 0) return { aPct: 50, bPct: 50 };
  const lo = Math.min(a, b), hi = Math.max(a, b);
  if (hi === lo) return { aPct: 50, bPct: 50 };
  const s = better === 1 ? (a - lo) / (hi - lo) : (hi - a) / (hi - lo);
  return { aPct: 20 + s * 60, bPct: 20 + (1 - s) * 60 };
}

export default function GamePage({
  params,
  searchParams,
}: {
  params: Promise<{ game_id: string }>;
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
}) {
  const { game_id } = use(params);
  const sp       = use(searchParams);
  const away     = (sp.away     as string) ?? "";
  const home     = (sp.home     as string) ?? "";
  const [awayColor, homeColor] = pickMatchupColors(teamColorCandidates(away), teamColorCandidates(home));
  const colors: Colors = { [away]: awayColor, [home]: homeColor };
  // Score, clock and live probability from the API once it answers; the link's values until then
  const [live, setLive] = useState<LiveGame | null>(null);
  const started  = !!live && live.state !== "pre";
  const inPlay   = live?.state === "in";
  const time     = started ? live.status : (sp.time as string) ?? "";
  const status   = live ? (live.state === "in" ? "Live" : live.state === "post" ? "Final" : "Scheduled") : (sp.status as string) ?? "";
  const awayProb = inPlay ? live.away_prob : live ? live.pregame_away_prob : parseFloat((sp.away_prob as string) ?? "50");
  const homeProb = inPlay ? live.home_prob : live ? live.pregame_home_prob : parseFloat((sp.home_prob as string) ?? "50");
  const winner   = live ? (awayProb >= homeProb ? away : home) : (sp.winner as string) ?? "";
  const awayScore = started ? live.away_score : sp.away_score ? parseInt(sp.away_score as string) : null;
  const homeScore = started ? live.home_score : sp.home_score ? parseInt(sp.home_score as string) : null;

  const isLive    = status === "Live";
  const isFinal   = status === "Final";
  const showScore = isLive || isFinal;
  const awayWins  = isFinal && awayScore !== null && homeScore !== null && awayScore > homeScore;
  const homeWins  = isFinal && awayScore !== null && homeScore !== null && homeScore > awayScore;

  const [compare,  setCompare]  = useState<CompareResult | null>(null);
  const [injuries, setInjuries] = useState<InjuryReport | null>(null);
  const [history,  setHistory]  = useState<HistoryPoint[]>([]);
  const [loading,  setLoading]  = useState(() => !!away && !!home);
  const [fetchErr, setFetchErr] = useState(false);
  const retriedRef = useRef(false);

  // Live win probability: refreshed every 30 s while the game is on
  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const load = () => {
      fetch(`${API}/api/nba/game/${game_id}`)
        .then(r => { if (!r.ok) throw new Error(String(r.status)); return r.json(); })
        .then((d: LiveGame) => {
          if (!active) return;
          setLive(d);
          if (d.state !== "post") timer = setTimeout(load, d.state === "in" ? 30_000 : 120_000);
        })
        .catch(() => { if (active) timer = setTimeout(load, 60_000); });
    };
    load();
    return () => { active = false; clearTimeout(timer); };
  }, [game_id]);

  useEffect(() => {
    if (!away || !home) return;

    const qa = `team_a=${encodeURIComponent(away)}&team_b=${encodeURIComponent(home)}`;
    retriedRef.current = false;

    // ── Series history — slow (Monte Carlo + nba_api), fetched independently ──
    const histCtrl  = new AbortController();
    const histTimer = setTimeout(() => histCtrl.abort(), 60000);
    fetch(`${API}/api/series_history?${qa}`, { signal: histCtrl.signal })
      .then(r => { if (!r.ok) throw new Error(String(r.status)); return r.json(); })
      .then(hist => setHistory((hist as { history: HistoryPoint[] }).history ?? []))
      .catch(() => {})
      .finally(() => clearTimeout(histTimer));

    // ── Injuries — fetched independently so ESPN latency doesn't block stats ──
    const injCtrl  = new AbortController();
    const injTimer = setTimeout(() => injCtrl.abort(), 30000);
    fetch(`${API}/api/injuries?${qa}`, { signal: injCtrl.signal })
      .then(r => { if (!r.ok) throw new Error(String(r.status)); return r.json(); })
      .then(inj => setInjuries(inj as InjuryReport))
      .catch(() => {})
      .finally(() => clearTimeout(injTimer));

    // ── Primary fetch: compare — auto-retries once on timeout (Render cold start) ──
    let ctrl  = new AbortController();
    let timer = setTimeout(() => ctrl.abort(), 55000);

    function doCompare() {
      fetch(`${API}/api/compare?${qa}`, { signal: ctrl.signal })
        .then(r => { if (!r.ok) throw new Error(String(r.status)); return r.json(); })
        .then(cmp => { clearTimeout(timer); setCompare(cmp as CompareResult); setLoading(false); })
        .catch((err) => {
          clearTimeout(timer);
          if ((err as Error)?.name === "AbortError" && !retriedRef.current) {
            // Backend was waking up — retry once now that it's likely ready
            retriedRef.current = true;
            ctrl  = new AbortController();
            timer = setTimeout(() => ctrl.abort(), 30000);
            doCompare();
            return;
          }
          if ((err as Error)?.name !== "AbortError") {
            console.error("[GamePage] compare fetch error:", err);
          }
          setFetchErr(true);
          setLoading(false);
        });
    }
    doCompare();

    return () => {
      ctrl.abort();     clearTimeout(timer);
      histCtrl.abort(); clearTimeout(histTimer);
      injCtrl.abort();  clearTimeout(injTimer);
    };
  }, [away, home]);

  const showChart = (started && !!live && live.season_type !== 3 && live.timeline.length > 1)
    || (live?.season_type === 3 && history.length > 0);
  const hasGameStats = started && !!live && Object.keys(live.away_stats).length > 0;
  const hasPlayers = started && !!live && (live.away_players.length > 0 || live.home_players.length > 0);

  return (
    <main className="px-4 md:px-8 pt-4 md:pt-5 pb-4 flex flex-col gap-3">

      {/* Back */}
      <Link href="/" className="inline-flex items-center gap-1.5 text-xs text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 transition-colors">
        <svg width="13" height="13" viewBox="0 0 13 13" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
          <path d="M8 2L3 6.5l5 4.5" />
        </svg>
        Games
      </Link>

      {/* ── Hero card ── */}
      <div className="bg-white dark:bg-gray-900 border border-gray-100 dark:border-transparent shadow-sm rounded-2xl overflow-hidden">
        <div className="px-4 md:px-8 pt-4 flex items-center justify-between">
          <p className="text-[11px] font-semibold text-gray-500 uppercase tracking-widest">{time}</p>
          {isLive && (
            <span className="flex items-center gap-1.5 text-xs font-bold text-red-400">
              <span className="w-1.5 h-1.5 rounded-full bg-red-500 animate-pulse inline-block" />
              Live
            </span>
          )}
        </div>

        <div className="px-4 md:px-8 pt-4 pb-3 grid grid-cols-[1fr_auto_1fr] items-center gap-2 md:gap-6">

          {/* Away */}
          <div className="group flex items-center">
            <Link href={teamHref("nba", away)} title={`${away} team page`} className="flex-shrink-0 pr-2 md:pr-4 origin-left transition-transform group-hover:scale-110"><TeamLogo team={away} size="w-10 h-10 md:w-14 md:h-14" colors={colors} /></Link>
            <div>
              <p className="text-gray-900 dark:text-white font-bold text-base md:text-xl leading-tight"><Link href={teamHref("nba", away)} className="inline-block transition-transform group-hover:scale-110">{lastName(away)}</Link></p>
              {showScore && awayScore !== null ? (
                <p className={`text-xl md:text-2xl font-black mt-1 ${awayWins ? "text-gray-900 dark:text-white" : "text-gray-500"}`}>{awayScore}</p>
              ) : (
                <p className={`text-sm md:text-base font-bold mt-1 ${winner === away ? "text-green-600 dark:text-green-400" : "text-gray-500"}`}>{awayProb}%</p>
              )}
            </div>
          </div>

          {/* Center */}
          <div className="flex flex-col items-center gap-1 px-2 md:px-8">
            <p className="text-[9px] md:text-[10px] font-semibold text-gray-500 uppercase tracking-widest">{inPlay ? "Live win prob" : started ? "Pre-game win prob" : "Win Prob"}</p>
            <p className="text-lg md:text-2xl font-black tracking-tight whitespace-nowrap">
              <span style={{ color: winner === away ? "#16a34a" : "#6b7280" }}>{awayProb}%</span>
              <span className="text-gray-300 dark:text-gray-700 mx-1 md:mx-2">·</span>
              <span style={{ color: winner === home ? "#16a34a" : "#6b7280" }}>{homeProb}%</span>
            </p>
            {inPlay && live && (
              <p className="text-[10px] text-gray-400 whitespace-nowrap">
                Pre-game {live.pregame_away_prob}% · {live.pregame_home_prob}%
              </p>
            )}
          </div>

          {/* Home */}
          <div className="group flex items-center flex-row-reverse">
            <Link href={teamHref("nba", home)} title={`${home} team page`} className="flex-shrink-0 pl-2 md:pl-4 origin-right transition-transform group-hover:scale-110"><TeamLogo team={home} size="w-10 h-10 md:w-14 md:h-14" colors={colors} /></Link>
            <div className="text-right">
              <p className="text-gray-900 dark:text-white font-bold text-base md:text-xl leading-tight"><Link href={teamHref("nba", home)} className="inline-block transition-transform group-hover:scale-110">{lastName(home)}</Link></p>
              {showScore && homeScore !== null ? (
                <p className={`text-xl md:text-2xl font-black mt-1 ${homeWins ? "text-gray-900 dark:text-white" : "text-gray-500"}`}>{homeScore}</p>
              ) : (
                <p className={`text-sm md:text-base font-bold mt-1 ${winner === home ? "text-green-600 dark:text-green-400" : "text-gray-500"}`}>{homeProb}%</p>
              )}
            </div>
          </div>
        </div>

        {/* Probability bar */}
        <div className="mx-4 md:mx-8 mb-5 h-[3px] flex rounded-full overflow-hidden">
          <div className="h-full" style={{ width: `${awayProb}%`, background: getColor(away, colors) }} />
          <div className="h-full flex-1" style={{ background: getColor(home, colors) }} />
        </div>
      </div>

      {!live && loading && (
        <div className="bg-white dark:bg-gray-900 border border-gray-100 dark:border-transparent shadow-sm rounded-2xl p-5 text-center text-xs text-gray-400 dark:text-gray-600">
          Loading game…
        </div>
      )}

      {!live && !loading && fetchErr && (
        <div className="bg-white dark:bg-gray-900 border border-gray-100 dark:border-transparent shadow-sm rounded-2xl p-5 text-center text-xs text-gray-400 dark:text-gray-600">
          Stats unavailable — backend timed out.{" "}
          <button onClick={() => window.location.reload()} className="underline hover:text-gray-600 dark:hover:text-gray-400">Retry</button>
        </div>
      )}

      {/* ── Score by quarter ── */}
      {started && live && (live.away_quarters.length > 0 || live.home_quarters.length > 0) && (
        <Quarterscore live={live} awayTeam={away} homeTeam={home} />
      )}

      {/* ── Win probability (this game, or the series in the playoffs) + team stats ── */}
      {(showChart || hasGameStats || compare) && (
        <div className={`grid gap-3 items-start ${showChart ? "grid-cols-1 lg:grid-cols-[5fr_2fr]" : "grid-cols-1"}`}>
          {started && live && live.season_type !== 3 && live.timeline.length > 1 && (
            <GameProbChart live={live} awayTeam={away} homeTeam={home} colors={colors} />
          )}
          {live?.season_type === 3 && history.length > 0 && (
            <ProbChart data={history} awayTeam={away} homeTeam={home} colors={colors} />
          )}
          {hasGameStats && live
            ? <GameStatsCard live={live} />
            : compare && <SeasonStatsCard compare={compare} />}
        </div>
      )}

      {/* ── Why the model leans + the players in this game (injuries before tip-off) ── */}
      {live && (live.explanation.length > 0 || hasPlayers || injuries) && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-3 items-stretch">
          {live.explanation.length > 0 && (
            <WhyPanel factors={live.explanation} awayTeam={away} homeTeam={home} colors={colors} />
          )}
          {hasPlayers ? (
            <BoxScore live={live} awayTeam={away} homeTeam={home} colors={colors} />
          ) : injuries && (
            <div className="bg-white dark:bg-gray-900 border border-gray-100 dark:border-transparent shadow-sm rounded-2xl p-5">
              <p className="text-[10px] font-semibold text-gray-500 uppercase tracking-widest mb-3">Injury Report</p>
              <div className="flex flex-col gap-4">
                <InjuryColumn team={away} data={injuries[away]} />
                <InjuryColumn team={home} data={injuries[home]} />
              </div>
            </div>
          )}
        </div>
      )}
    </main>
  );
}

// ── Score by quarter ───────────────────────────────────────────────────────────

function Quarterscore({ live, awayTeam, homeTeam }: { live: LiveGame; awayTeam: string; homeTeam: string }) {
  const n = Math.max(4, live.away_quarters.length, live.home_quarters.length);
  const cols = Array.from({ length: n }, (_, i) => i + 1);
  const label = (q: number) => (q <= 4 ? `Q${q}` : q === 5 ? "OT" : `OT${q - 4}`);
  const final = live.state === "post";
  const rows: [string, (number | null)[], number, boolean][] = [
    [awayTeam, live.away_quarters, live.away_score, final && live.away_score > live.home_score],
    [homeTeam, live.home_quarters, live.home_score, final && live.home_score > live.away_score],
  ];
  return (
    <div className="bg-white dark:bg-gray-900 border border-gray-100 dark:border-transparent shadow-sm rounded-2xl p-5 overflow-x-auto">
      <p className="text-[10px] font-semibold text-gray-500 uppercase tracking-widest mb-4">Score by quarter</p>
      <table className="text-xs tabular-nums min-w-full">
        <thead>
          <tr>
            <th className="text-left text-gray-400 font-semibold pb-2 pr-4 min-w-[40px]" />
            {cols.map(q => <th key={q} className="text-center text-gray-400 font-semibold pb-2 w-9 min-w-[32px]">{label(q)}</th>)}
            <th className="text-center text-gray-400 font-semibold pb-2 pl-3 border-l border-gray-200 dark:border-gray-700 min-w-[32px]">{final ? "Final" : "Total"}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(([team, qs, total, won]) => (
            <tr key={team} className="border-t border-gray-100 dark:border-gray-800">
              <td className={`pr-4 py-2 font-bold ${won || !final ? "text-gray-900 dark:text-white" : "text-gray-500"}`}>{getAbbr(team)}</td>
              {cols.map(q => <td key={q} className="text-center py-2 text-gray-700 dark:text-gray-300">{qs[q - 1] ?? ""}</td>)}
              <td className={`text-center py-2 pl-3 font-bold border-l border-gray-200 dark:border-gray-700 ${won || !final ? "text-gray-900 dark:text-white" : "text-gray-500"}`}>{total}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ── Team stats: this game, or the season before tip-off ────────────────────────

const GAME_STATS: { key: string; label: string; lowerBetter?: boolean }[] = [
  { key: "fg", label: "Field goals" }, { key: "fg_pct", label: "FG %" },
  { key: "fg3", label: "3-pointers" }, { key: "fg3_pct", label: "3PT %" },
  { key: "ft", label: "Free throws" }, { key: "reb", label: "Rebounds" },
  { key: "ast", label: "Assists" }, { key: "tov", label: "Turnovers", lowerBetter: true },
  { key: "stl", label: "Steals" }, { key: "blk", label: "Blocks" },
  { key: "paint", label: "Points in paint" }, { key: "fast_break", label: "Fast-break points" },
];

function GameStatsCard({ live }: { live: LiveGame }) {
  return (
    <div className="bg-white dark:bg-gray-900 border border-gray-100 dark:border-transparent shadow-sm rounded-2xl p-5">
      <p className="text-[10px] font-semibold text-gray-500 uppercase tracking-widest mb-3">Stats comparison · this game</p>
      <div className="flex flex-col gap-2.5">
        {GAME_STATS.filter(s => live.away_stats[s.key] !== undefined || live.home_stats[s.key] !== undefined).map(({ key, label, lowerBetter }) => {
          const a = live.away_stats[key] ?? "—", b = live.home_stats[key] ?? "—";
          const an = parseFloat(a), bn = parseFloat(b);   // "43-95" → 43 made
          const ok = !isNaN(an) && !isNaN(bn);
          const aWins = ok && (lowerBetter ? an < bn : an > bn);
          const bWins = ok && (lowerBetter ? bn < an : bn > an);
          const pct = key.endsWith("_pct");
          return (
            <div key={key} className="flex items-center">
              <span className={`w-16 text-xs font-bold tabular-nums ${aWins ? "text-green-600 dark:text-green-400" : "text-gray-500"}`}>{a}{pct && a !== "—" ? "%" : ""}</span>
              <span className="flex-1 text-center text-[10px] text-gray-500 uppercase tracking-wide">{label}</span>
              <span className={`w-16 text-xs font-bold tabular-nums text-right ${bWins ? "text-green-600 dark:text-green-400" : "text-gray-500"}`}>{b}{pct && b !== "—" ? "%" : ""}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function SeasonStatsCard({ compare }: { compare: CompareResult }) {
  return (
    <div className="bg-white dark:bg-gray-900 border border-gray-100 dark:border-transparent shadow-sm rounded-2xl p-5">
      <p className="text-[10px] font-semibold text-gray-500 uppercase tracking-widest mb-3">Stats comparison · season</p>
      <div className="flex flex-col gap-3">
        {STATS.map(({ key, label, better, pct }) => {
          const a = compare.team_a_stats[key as keyof TeamStats] ?? 0;
          const b = compare.team_b_stats[key as keyof TeamStats] ?? 0;
          const aWins = better !== 0 && (better === 1 ? a > b : a < b);
          const bWins = better !== 0 && (better === 1 ? b > a : b < a);
          const { aPct, bPct } = barPcts(a, b, better);
          return (
            <div key={key}>
              <div className="flex items-center mb-1">
                <span className={`w-12 text-xs font-bold ${aWins ? "text-green-600 dark:text-green-400" : "text-gray-500"}`}>{fmt(a, pct)}</span>
                <span className="flex-1 text-center text-[10px] text-gray-500 uppercase tracking-wide">{label}</span>
                <span className={`w-12 text-xs font-bold text-right ${bWins ? "text-green-600 dark:text-green-400" : "text-gray-500"}`}>{fmt(b, pct)}</span>
              </div>
              <div className="flex h-[3px] gap-[2px]">
                <div className="flex-1 bg-gray-100 dark:bg-gray-800 rounded-l-full overflow-hidden flex justify-end">
                  <div className={`h-full rounded-l-full ${aWins ? "bg-green-500" : "bg-gray-300 dark:bg-gray-600"}`} style={{ width: `${aPct}%` }} />
                </div>
                <div className="flex-1 bg-gray-100 dark:bg-gray-800 rounded-r-full overflow-hidden">
                  <div className={`h-full rounded-r-full ${bWins ? "bg-green-500" : "bg-gray-300 dark:bg-gray-600"}`} style={{ width: `${bPct}%` }} />
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── Why the model leans ────────────────────────────────────────────────────────

const FACTOR_LABELS: Record<string, { label: string; desc: string; fmt: (v: number) => string }> = {
  elo_diff: {
    label: "Elo rating",
    desc: "Overall team strength. Goes up after wins (more for big wins), down after losses, and carries over between seasons. Shown as the gap vs the opponent.",
    fmt: v => (v > 0 ? "+" : "") + v.toFixed(0),
  },
  margin_ewm_diff: {
    label: "Recent point margin",
    desc: "Points scored minus points allowed per game, weighted toward recent games. Shown as the gap vs the opponent.",
    fmt: v => (v > 0 ? "+" : "") + v.toFixed(1) + " pts",
  },
  roster_diff: {
    label: "Roster strength",
    desc: "Last season's production (Game Score per minute) of the players on today's roster, weighted by their expected minutes — how the model sees trades and signings. Shown per 100 minutes, as the gap vs the opponent.",
    fmt: v => (v > 0 ? "+" : "") + (v * 100).toFixed(1),
  },
  home: {
    label: "Home court",
    desc: "Home teams win about 56% of NBA games. Neutral sites give no home edge.",
    fmt: v => (v ? "Home" : "Away"),
  },
  rest_diff: {
    label: "Extra rest",
    desc: "Days of rest compared with the opponent (capped at 4).",
    fmt: v => (v > 0 ? "+" : "") + v.toFixed(0) + "d",
  },
  b2b: {
    label: "Back-to-back",
    desc: "Whether the team played the day before. Tired legs lower its chances.",
    fmt: v => (v ? "Yes" : "No"),
  },
};

function WhyPanel({ factors, awayTeam, homeTeam, colors }: { factors: Factor[]; awayTeam: string; homeTeam: string; colors: Colors }) {
  const shown = factors.filter(f => Math.abs(f.impact) >= 0.01).slice(0, 6);
  if (!shown.length) return null;
  const maxAbs = Math.max(...shown.map(f => Math.abs(f.impact)));
  return (
    <div className="h-full bg-white dark:bg-gray-900 border border-gray-100 dark:border-transparent shadow-sm rounded-2xl p-5">
      <p className="text-[10px] font-semibold text-gray-500 uppercase tracking-widest mb-1">Why the model leans this way</p>
      <p className="text-xs text-gray-400 mb-4">Each bar is that factor&apos;s share of the pre-game edge. Values are from each team&apos;s side.</p>
      <div className="flex justify-between text-[11px] font-bold text-gray-700 dark:text-gray-300 mb-2">
        <span>← favours {getAbbr(awayTeam)}</span><span>favours {getAbbr(homeTeam)} →</span>
      </div>
      <div className="flex flex-col gap-2.5">
        {shown.map(f => {
          const meta = FACTOR_LABELS[f.feature] ?? { label: f.feature, desc: "", fmt: (v: number) => v.toFixed(2) };
          const w = (Math.abs(f.impact) / maxAbs) * 50;
          const favAway = f.impact > 0;
          return (
            <div key={f.feature}>
              <div className="flex items-center justify-between text-[11px] text-gray-500 mb-1 tabular-nums">
                <span className="w-20">{meta.fmt(f.away_value)}</span>
                <span className="relative group/def">
                  <span tabIndex={0} className="font-medium text-gray-700 dark:text-gray-300 cursor-help underline decoration-dotted decoration-gray-400 underline-offset-2">{meta.label}</span>
                  {meta.desc && (
                    <span role="tooltip" className="pointer-events-none absolute bottom-full left-1/2 -translate-x-1/2 mb-2 z-20 w-60 px-3 py-2 rounded-lg shadow-lg bg-gray-900 dark:bg-gray-800 text-white text-[11px] leading-relaxed font-normal text-left opacity-0 group-hover/def:opacity-100 group-focus-within/def:opacity-100 transition-opacity duration-150">
                      {meta.desc}
                    </span>
                  )}
                </span>
                <span className="w-20 text-right">{meta.fmt(f.home_value)}</span>
              </div>
              <div className="relative h-2 bg-gray-100 dark:bg-gray-800 rounded-full">
                <div className="absolute top-0 bottom-0 w-px bg-gray-300 dark:bg-gray-600" style={{ left: "50%" }} />
                <div className="absolute top-0 bottom-0 rounded-full"
                  style={{ width: `${w}%`, left: favAway ? `${50 - w}%` : "50%", background: getColor(favAway ? awayTeam : homeTeam, colors) }} />
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── Players in this game ───────────────────────────────────────────────────────

const BOX_COLS: { key: keyof BoxPlayer; label: string }[] = [
  { key: "min", label: "MIN" }, { key: "pts", label: "PTS" }, { key: "reb", label: "REB" },
  { key: "ast", label: "AST" }, { key: "fg", label: "FG" }, { key: "fg3", label: "3PT" }, { key: "pm", label: "+/-" },
];

function BoxScore({ live, awayTeam, homeTeam, colors }: { live: LiveGame; awayTeam: string; homeTeam: string; colors: Colors }) {
  const [side, setSide] = useState<"away" | "home">("away");
  const team = side === "away" ? awayTeam : homeTeam;
  const players = side === "away" ? live.away_players : live.home_players;
  const firstBench = players.findIndex(p => !p.starter);
  return (
    <div className="h-full bg-white dark:bg-gray-900 border border-gray-100 dark:border-transparent shadow-sm rounded-2xl p-5">
      <div className="flex items-center justify-between mb-3 gap-3">
        <p className="text-[10px] font-semibold text-gray-500 uppercase tracking-widest">Players · this game</p>
        <div className="flex gap-1 bg-gray-100 dark:bg-gray-800 rounded-lg p-0.5">
          {(["away", "home"] as const).map(s => {
            const t = s === "away" ? awayTeam : homeTeam;
            return (
              <button key={s} onClick={() => setSide(s)}
                className={`px-3 py-1 rounded-md text-xs font-bold transition-colors ${side === s ? "bg-white dark:bg-gray-900 shadow-sm" : "text-gray-500"}`}
                style={side === s ? { color: getColor(t, colors) } : undefined}>
                {getAbbr(t)}
              </button>
            );
          })}
        </div>
      </div>
      <div className="overflow-x-auto -mx-1">
        <table className="w-full text-xs tabular-nums">
          <thead>
            <tr className="text-gray-400">
              <th className="text-left font-semibold py-1.5 px-1">{lastName(team)}</th>
              {BOX_COLS.map(c => <th key={c.key} className="text-right font-semibold py-1.5 px-1.5">{c.label}</th>)}
            </tr>
          </thead>
          <tbody>
            {players.map((pl, i) => (
              <tr key={pl.id || pl.name}
                className={`border-t ${i === firstBench && i > 0 ? "border-gray-300 dark:border-gray-600" : "border-gray-100 dark:border-gray-800"} ${pl.dnp ? "text-gray-400" : "text-gray-700 dark:text-gray-300"}`}>
                <td className="py-1.5 px-1 whitespace-nowrap">
                  {pl.id
                    ? <Link href={playerHref("nba", pl.id)} className="font-semibold text-gray-900 dark:text-white hover:underline">{pl.name}</Link>
                    : <span className="font-semibold">{pl.name}</span>}
                  <span className="text-gray-400"> {pl.position}</span>
                </td>
                {pl.dnp
                  ? <td colSpan={BOX_COLS.length} className="text-right py-1.5 px-1.5 text-[10px] uppercase">Did not play</td>
                  : BOX_COLS.map(c => (
                      <td key={c.key} className={`text-right py-1.5 px-1.5 whitespace-nowrap ${c.key === "pts" ? "font-bold text-gray-900 dark:text-white" : ""}`}>{String(pl[c.key] ?? "")}</td>
                    ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-2 text-[10px] text-gray-400">Starters first · {live.state === "in" ? "updates every 30 s" : "final box score"}</p>
    </div>
  );
}

function GameProbChart({ live, awayTeam, homeTeam, colors }: { live: LiveGame; awayTeam: string; homeTeam: string; colors: Colors }) {
  const ac = getColor(awayTeam, colors);
  const hc = getColor(homeTeam, colors);
  const end = Math.max(48, live.timeline[live.timeline.length - 1].minute);
  const ticks = [0, 12, 24, 36, 48].concat(end > 48 ? [end] : []);
  const tickLabel = (m: number) => (m === 0 ? "Q1" : m < 48 ? `Q${m / 12 + 1}` : m === 48 ? (end > 48 ? "OT" : "End") : "");
  return (
    <div className="bg-white dark:bg-gray-900 border border-gray-100 dark:border-transparent shadow-sm rounded-2xl px-6 pt-5 pb-4">
      <div className="flex items-start justify-between mb-3">
        <div>
          <p className="text-[10px] font-semibold text-gray-500 uppercase tracking-widest">Win probability · this game</p>
          <p className="text-[10px] text-gray-400 mt-0.5">From our pre-game prediction, updated after every basket</p>
        </div>
        <div className="flex gap-5">
          <div className="text-right">
            <p className="text-[10px] font-bold" style={{ color: ac }}>{getAbbr(awayTeam)}</p>
            <p className="text-lg font-black leading-none" style={{ color: ac }}>{live.away_prob}%</p>
          </div>
          <div className="text-right">
            <p className="text-[10px] font-bold" style={{ color: hc }}>{getAbbr(homeTeam)}</p>
            <p className="text-lg font-black leading-none" style={{ color: hc }}>{live.home_prob}%</p>
          </div>
        </div>
      </div>
      <ResponsiveContainer width="100%" height={170}>
        <LineChart data={live.timeline} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
          <CartesianGrid strokeDasharray="2 5" stroke="var(--chart-grid)" vertical={false} />
          <XAxis dataKey="minute" type="number" domain={[0, end]} ticks={ticks} tickFormatter={tickLabel}
            tick={{ fill: "var(--chart-tick)", fontSize: 10 }} axisLine={false} tickLine={false} />
          <YAxis domain={[0, 100]} ticks={[0, 25, 50, 75, 100]} tick={{ fill: "var(--chart-tick)", fontSize: 10 }}
            axisLine={false} tickLine={false} tickFormatter={v => `${v}%`} width={40} />
          <ReferenceLine y={50} stroke="var(--chart-grid)" />
          <Tooltip
            contentStyle={{ background: "var(--tooltip-bg)", border: "1px solid var(--tooltip-border)", borderRadius: 8, fontSize: 11, color: "var(--tooltip-text)" }}
            labelStyle={{ color: "#6b7280", marginBottom: 4 }}
            labelFormatter={(_, payload) => {
              const p = payload?.[0]?.payload as LivePoint | undefined;
              return p ? `${p.label} · ${getAbbr(awayTeam)} ${p.away_score}–${p.home_score} ${getAbbr(homeTeam)}` : "";
            }}
            formatter={(v: unknown, name: string | number | undefined) => [
              `${v}%`, name?.toString() === "away_prob" ? getAbbr(awayTeam) : getAbbr(homeTeam),
            ]}
          />
          <Line type="stepAfter" dataKey="away_prob" stroke={ac} strokeWidth={2} dot={false} isAnimationActive={false} />
          <Line type="stepAfter" dataKey="home_prob" stroke={hc} strokeWidth={2} dot={false} isAnimationActive={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

function ProbChart({ data, awayTeam, homeTeam, colors }: {
  data: HistoryPoint[]; awayTeam: string; homeTeam: string; colors: Colors;
}) {
  const ac   = getColor(awayTeam, colors);
  const hc   = getColor(homeTeam, colors);
  const last = data[data.length - 1];

  // Approximate pixel y for each endpoint (chart height=150, topMargin=8, domain [0,100])
  const PLOT_H = 142;
  const aY = 8 + (1 - (last?.team_a_prob ?? 50) / 100) * PLOT_H;
  const bY = 8 + (1 - (last?.team_b_prob ?? 50) / 100) * PLOT_H;
  const diff = bY - aY;
  const MIN_GAP = 42;
  let aOff = 0, bOff = 0;
  if (Math.abs(diff) < MIN_GAP) {
    const push = (MIN_GAP - Math.abs(diff)) / 2;
    if (diff >= 0) { aOff = -push; bOff = push; }
    else           { aOff =  push; bOff = -push; }
  }

  const EndDot = (color: string) => function EndDot(props: { cx?: number; cy?: number; index?: number }) {
    const { cx = 0, cy = 0, index = 0 } = props;
    if (index !== data.length - 1) return <g />;
    return <circle cx={cx} cy={cy} r={5} fill={color} />;
  };

  const EndLabel = (team: string, color: string, yOff: number) =>
    function EndLabel(props: { x?: number; y?: number; index?: number; value?: number }) {
      const { x = 0, y = 0, index = 0, value = 0 } = props;
      if (index !== data.length - 1) return null;
      const adjY = Math.max(16, Number(y) + yOff);  // keep the label inside the chart near 100 %
      return (
        <g>
          <text x={Number(x) + 10} y={adjY - 5} fill={color} fontSize={9} fontWeight="700" fontFamily="inherit">{getAbbr(team)}</text>
          <text x={Number(x) + 10} y={adjY + 9} fill={color} fontSize={14} fontWeight="900" fontFamily="inherit">{value}%</text>
        </g>
      );
    };

  return (
    <div className="bg-white dark:bg-gray-900 border border-gray-100 dark:border-transparent shadow-sm rounded-2xl px-6 pt-5 pb-4">
      <div className="flex items-start justify-between mb-3">
        <p className="text-[10px] font-semibold text-gray-500 uppercase tracking-widest">
          Series Win Probability
        </p>
        <div className="flex gap-5">
          <div className="text-right">
            <p className="text-[10px] font-bold" style={{ color: ac }}>{getAbbr(awayTeam)}</p>
            <p className="text-lg font-black leading-none" style={{ color: ac }}>{last?.team_a_prob}%</p>
          </div>
          <div className="text-right">
            <p className="text-[10px] font-bold" style={{ color: hc }}>{getAbbr(homeTeam)}</p>
            <p className="text-lg font-black leading-none" style={{ color: hc }}>{last?.team_b_prob}%</p>
          </div>
        </div>
      </div>

      <ResponsiveContainer width="100%" height={150}>
        <LineChart data={data} margin={{ top: 8, right: 70, bottom: 0, left: -8 }}>
          <CartesianGrid strokeDasharray="2 5" stroke="var(--chart-grid)" vertical={false} />
          <XAxis
            dataKey="game"
            tick={{ fill: "var(--chart-tick)", fontSize: 10 }}
            axisLine={false}
            tickLine={false}
            interval={0}
          />
          <YAxis
            domain={[0, 100]}
            ticks={[0, 25, 50, 75, 100]}
            tick={{ fill: "var(--chart-tick)", fontSize: 10 }}
            axisLine={false}
            tickLine={false}
            tickFormatter={v => `${v}%`}
            width={30}
          />
          <Tooltip
            contentStyle={{ background: "var(--tooltip-bg)", border: "1px solid var(--tooltip-border)", borderRadius: 8, fontSize: 11, color: "var(--tooltip-text)" }}
            labelStyle={{ color: "#6b7280", marginBottom: 4 }}
            labelFormatter={(label, payload) => {
              const s = (payload?.[0]?.payload as HistoryPoint | undefined)?.series;
              return s ? `${label} — ${s}` : label;
            }}
            formatter={(v: unknown, name: string | number | undefined) => [
              `${v}%`,
              name?.toString() === "team_a_prob" ? getAbbr(awayTeam) : getAbbr(homeTeam),
            ]}
          />
          <Line type="monotone" dataKey="team_a_prob" stroke={ac} strokeWidth={2} dot={EndDot(ac)} activeDot={{ r: 4 }}>
            <LabelList dataKey="team_a_prob" content={EndLabel(awayTeam, ac, aOff) as never} />
          </Line>
          <Line type="monotone" dataKey="team_b_prob" stroke={hc} strokeWidth={2} dot={EndDot(hc)} activeDot={{ r: 4 }}>
            <LabelList dataKey="team_b_prob" content={EndLabel(homeTeam, hc, bOff) as never} />
          </Line>
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

function InjuryColumn({ team, data }: { team: string; data: InjuryData | undefined }) {
  return (
    <div>
      <p className="text-gray-900 dark:text-white font-bold text-xs mb-2">{lastName(team)}</p>
      {!data || data.players.length === 0 ? (
        <p className="text-[11px] text-gray-400 dark:text-gray-600">No injuries reported</p>
      ) : (
        <div className="flex flex-col gap-1.5">
          {data.players.map(p => (
            <div key={p.name} className="flex items-center gap-1.5">
              <span className={`text-[10px] px-1 py-0.5 rounded font-bold flex-shrink-0 ${STATUS_COLOR[p.status] ?? "bg-white/10 text-gray-400"}`}>
                {p.status === "Day-To-Day" ? "D2D" : p.status}
              </span>
              {p.id
                ? <Link href={playerHref("nba", p.id)} title={p.name} className="text-[11px] text-gray-600 dark:text-gray-300 truncate inline-block transition-transform hover:scale-105 origin-left">{p.name.split(" ").pop()}</Link>
                : <span className="text-[11px] text-gray-600 dark:text-gray-300 truncate">{p.name.split(" ").pop()}</span>}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
