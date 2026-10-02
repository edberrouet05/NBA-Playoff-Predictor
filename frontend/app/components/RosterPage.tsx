"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { playerHref, teamHref } from "./teamLinks";
import type { League } from "./TeamPage";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// ── Types (mirror get_team_roster in api/main.py) ──────────────────────────────

interface RosterPlayer {
  id: string; name: string; jersey: string | null; position: string; age: number | null;
  experience: number | null; headshot: string | null; injury: string | null;
  height: string | null; weight: string | null; college: string | null; bats_throws: string | null;
}
interface RosterData {
  league: League;
  team: { name: string; abbr: string; color: string; logo: string | null };
  groups: { name: string; players: RosterPlayer[] }[];
}

const card = "bg-white dark:bg-gray-900 border border-gray-100 dark:border-transparent shadow-sm rounded-2xl p-5";

function Headshot({ src, color }: { src: string | null; color: string }) {
  const [err, setErr] = useState(false);
  if (!src || err) return <div className="w-9 h-9 rounded-full flex-shrink-0" style={{ background: color }} />;
  return <img src={src} alt="" onError={() => setErr(true)} className="w-9 h-9 rounded-full object-cover bg-gray-100 dark:bg-gray-800 flex-shrink-0" />;
}

function InjuryBadge({ status }: { status: string }) {
  const out = /out|injured|reserve/i.test(status);
  return (
    <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded whitespace-nowrap ${out
      ? "bg-red-100 text-red-600 dark:bg-red-900/40 dark:text-red-300"
      : "bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300"}`}>{status}</span>
  );
}

function GroupTable({ league, name, players, color, showGroup }: {
  league: League; name: string; players: RosterPlayer[]; color: string; showGroup: boolean;
}) {
  const mlb = league === "mlb";
  const th = "text-left font-semibold py-2 px-2 whitespace-nowrap";
  return (
    <div className={card}>
      {showGroup && (
        <p className="text-[10px] font-semibold text-gray-500 uppercase tracking-widest mb-2">{name} · {players.length}</p>
      )}
      <div className="overflow-x-auto -mx-2">
        <table className="w-full text-xs">
          <thead>
            <tr className="text-gray-400 border-b border-gray-100 dark:border-gray-800">
              <th className={th}>Player</th>
              <th className={th}>Pos</th>
              <th className={`${th} text-right`}>Age</th>
              <th className={th}>Ht</th>
              <th className={th}>Wt</th>
              {mlb ? <th className={th}>B/T</th> : <th className={`${th} text-right`}>Exp</th>}
              {!mlb && <th className={th}>College</th>}
            </tr>
          </thead>
          <tbody>
            {players.map(p => (
              <tr key={p.id} className="border-b last:border-0 border-gray-50 dark:border-gray-800/60 hover:bg-gray-50 dark:hover:bg-gray-800/40">
                <td className="py-1.5 px-2">
                  <div className="flex items-center gap-2.5 min-w-[13rem]">
                    <Headshot src={p.headshot} color={color} />
                    <span className="w-7 text-right text-[11px] text-gray-400 tabular-nums">{p.jersey ? `#${p.jersey}` : ""}</span>
                    <Link href={playerHref(league, p.id)}
                      className="inline-block transition-transform hover:scale-105 origin-left text-sm font-semibold text-gray-900 dark:text-white whitespace-nowrap">
                      {p.name}
                    </Link>
                    {p.injury && <InjuryBadge status={p.injury} />}
                  </div>
                </td>
                <td className="py-1.5 px-2 font-semibold text-gray-600 dark:text-gray-300">{p.position}</td>
                <td className="py-1.5 px-2 text-right tabular-nums text-gray-600 dark:text-gray-300">{p.age ?? "—"}</td>
                <td className="py-1.5 px-2 whitespace-nowrap text-gray-600 dark:text-gray-300">{p.height ?? "—"}</td>
                <td className="py-1.5 px-2 whitespace-nowrap text-gray-600 dark:text-gray-300">{p.weight ?? "—"}</td>
                {mlb
                  ? <td className="py-1.5 px-2 text-gray-600 dark:text-gray-300">{p.bats_throws ?? "—"}</td>
                  : <td className="py-1.5 px-2 text-right tabular-nums text-gray-600 dark:text-gray-300">{p.experience === 0 ? "R" : p.experience ?? "—"}</td>}
                {!mlb && <td className="py-1.5 px-2 whitespace-nowrap text-gray-500">{p.college ?? "—"}</td>}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default function RosterPage({ league, team }: { league: League; team: string }) {
  const [data, setData] = useState<RosterData | null>(null);
  const [error, setError] = useState(false);
  const [group, setGroup] = useState<string>("All");

  useEffect(() => {
    let active = true;
    setData(null); setError(false);
    fetch(`${API}/api/team/${league}/${encodeURIComponent(team)}/roster`)
      .then(r => { if (!r.ok) throw new Error(String(r.status)); return r.json(); })
      .then((d: RosterData) => { if (active) setData(d); })
      .catch(() => { if (active) setError(true); });
    return () => { active = false; };
  }, [league, team]);

  const total = data?.groups.reduce((n, g) => n + g.players.length, 0) ?? 0;
  const shown = data ? (group === "All" ? data.groups : data.groups.filter(g => g.name === group)) : [];

  return (
    <main className="px-4 lg:px-8 pt-4 lg:pt-5 pb-8 flex flex-col gap-3">
      <Link href={data ? teamHref(league, data.team.name) : `/${league === "nba" ? "" : league}`}
        className="inline-flex items-center gap-1.5 text-xs text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 transition-colors">
        <svg width="13" height="13" viewBox="0 0 13 13" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
          <path d="M8 2L3 6.5l5 4.5" />
        </svg>
        {data ? data.team.name : "Back"}
      </Link>

      {!data && !error && <div className={`${card} text-center text-xs text-gray-400`}>Loading roster…</div>}
      {error && <div className={`${card} text-center text-xs text-gray-400`}>Could not load this roster.</div>}

      {data && (
        <>
          <div className={`${card} relative overflow-hidden flex flex-col sm:flex-row sm:items-center gap-4`}>
            <div className="absolute inset-x-0 top-0 h-1" style={{ background: data.team.color }} />
            {data.team.logo && <img src={data.team.logo} alt="" className="w-14 h-14 object-contain" />}
            <div className="flex-1">
              <p className="text-[11px] font-semibold text-gray-400 uppercase tracking-widest">Roster · {total} players</p>
              <h1 className="text-2xl font-black text-gray-900 dark:text-white">{data.team.name}</h1>
            </div>
            {data.groups.length > 1 && (
              <div className="flex flex-wrap gap-1.5">
                {["All", ...data.groups.map(g => g.name)].map(name => (
                  <button key={name} onClick={() => setGroup(name)}
                    className={`text-xs font-semibold rounded-full px-3 py-1.5 transition-colors ${group === name
                      ? "bg-gray-900 text-white dark:bg-white dark:text-gray-900"
                      : "bg-gray-50 text-gray-600 hover:bg-gray-100 dark:bg-gray-800 dark:text-gray-300 dark:hover:bg-gray-700"}`}>
                    {name}
                  </button>
                ))}
              </div>
            )}
          </div>

          {shown.map(g => (
            <GroupTable key={g.name} league={league} name={g.name} players={g.players}
              color={data.team.color} showGroup={data.groups.length > 1} />
          ))}
        </>
      )}
    </main>
  );
}
