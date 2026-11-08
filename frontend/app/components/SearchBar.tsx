"use client";
import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { playerHref, teamHref } from "./teamLinks";

// Search box in the header: teams and players of the three leagues, as you type.

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

type League = "nba" | "nfl" | "mlb";
interface TeamHit { type: "team"; league: League; id: string; name: string; abbr: string; logo: string | null }
interface PlayerHit {
  type: "player"; league: League; id: string; name: string;
  team: string | null; team_name: string | null; position: string | null; headshot: string | null;
}
type Hit = TeamHit | PlayerHit;

function hrefOf(h: Hit): string {
  return h.type === "team" ? teamHref(h.league, h.name) : playerHref(h.league, h.id);
}

function SearchIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round">
      <circle cx="7" cy="7" r="4.8" /><path d="M10.6 10.6L14 14" />
    </svg>
  );
}

function HitImage({ hit }: { hit: Hit }) {
  // Remember which URL failed, so the next result gets a fresh attempt
  const [failedSrc, setFailedSrc] = useState<string | null>(null);
  const src = hit.type === "team" ? hit.logo : hit.headshot;
  const round = hit.type === "player" ? "rounded-full bg-gray-100 dark:bg-gray-800" : "";
  if (!src || failedSrc === src) {
    return (
      <div className={`w-8 h-8 flex-shrink-0 rounded-full bg-gray-100 dark:bg-gray-800 flex items-center justify-center text-[10px] font-bold text-gray-500`}>
        {hit.type === "team" ? hit.abbr : hit.name.split(" ").map(w => w[0]).slice(0, 2).join("")}
      </div>
    );
  }
  // eslint-disable-next-line @next/next/no-img-element
  return <img src={src} alt="" className={`w-8 h-8 flex-shrink-0 object-cover ${round}`} onError={() => setFailedSrc(src)} />;
}

export default function SearchBar() {
  const router = useRouter();
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  // Results are stored with the query they answer, so stale ones are never shown
  const [result, setResult] = useState<{ q: string; hits: Hit[] } | null>(null);
  const [failed, setFailed] = useState<string | null>(null);
  const boxRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const q = query.trim();
  const ready = q.length >= 2;

  // Fetch a moment after the last keystroke
  useEffect(() => {
    if (!ready) return;
    const ctrl = new AbortController();
    const timer = setTimeout(() => {
      fetch(`${API}/api/search?q=${encodeURIComponent(q)}`, { signal: ctrl.signal })
        .then(r => { if (!r.ok) throw new Error(); return r.json(); })
        .then((d: { teams: TeamHit[]; players: PlayerHit[] }) => {
          setResult({ q, hits: [...d.teams, ...d.players] });
          setActive(0);
        })
        .catch(e => { if (e.name !== "AbortError") setFailed(q); });
    }, 200);
    return () => { clearTimeout(timer); ctrl.abort(); };
  }, [q, ready]);

  // Close when clicking elsewhere; "/" focuses the box from anywhere on the page
  useEffect(() => {
    const onDown = (e: MouseEvent) => {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement)?.tagName;
      if (e.key === "/" && tag !== "INPUT" && tag !== "TEXTAREA") {
        e.preventDefault();
        inputRef.current?.focus();
      }
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("mousedown", onDown); document.removeEventListener("keydown", onKey); };
  }, []);

  const hits = ready && result?.q === q ? result.hits : [];
  const loading = ready && result?.q !== q && failed !== q;
  const teams = hits.filter((h): h is TeamHit => h.type === "team");
  const players = hits.filter((h): h is PlayerHit => h.type === "player");

  function go(h: Hit) {
    setOpen(false);
    setQuery("");
    inputRef.current?.blur();
    router.push(hrefOf(h));
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Escape") { setOpen(false); inputRef.current?.blur(); return; }
    if (!hits.length) return;
    if (e.key === "ArrowDown") { e.preventDefault(); setActive(a => (a + 1) % hits.length); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setActive(a => (a - 1 + hits.length) % hits.length); }
    else if (e.key === "Enter") { e.preventDefault(); go(hits[Math.min(active, hits.length - 1)]); }
  }

  function row(h: Hit) {
    const i = hits.indexOf(h);
    const detail = h.type === "team"
      ? `${h.league.toUpperCase()} · Team`
      : [h.league.toUpperCase(), h.position, h.team_name ?? "Free agent"].filter(Boolean).join(" · ");
    return (
      <Link key={`${h.type}-${h.league}-${h.id}`} href={hrefOf(h)}
        onClick={e => { e.preventDefault(); go(h); }}
        onMouseEnter={() => setActive(i)}
        className={`flex items-center gap-3 px-3 py-2 rounded-xl transition-colors ${
          i === active ? "bg-gray-100 dark:bg-gray-800" : ""}`}>
        <HitImage hit={h} />
        <div className="min-w-0">
          <p className="text-sm font-semibold text-gray-900 dark:text-white truncate">{h.name}</p>
          <p className="text-[11px] text-gray-500 truncate">{detail}</p>
        </div>
      </Link>
    );
  }

  return (
    <div ref={boxRef} className="relative">
      {/* Phones: a magnifier that opens the box over the header; wider screens: the box itself */}
      <div
        onClick={() => { if (!open) { setOpen(true); requestAnimationFrame(() => inputRef.current?.focus()); } }}
        className={`flex items-center gap-2 h-8 rounded-lg px-2.5 transition-all bg-gray-100 dark:bg-gray-800 text-gray-400 ${
          open ? "fixed left-3 right-3 top-2 z-40 sm:static sm:w-72 ring-2 ring-red-500/40"
               : "w-8 justify-center cursor-pointer sm:w-56 sm:justify-start sm:cursor-text"}`}>
        <SearchIcon />
        <input
          ref={inputRef}
          value={query}
          onChange={e => { setQuery(e.target.value); setOpen(true); }}
          onFocus={() => setOpen(true)}
          onKeyDown={onKeyDown}
          placeholder="Search teams & players"
          aria-label="Search teams and players"
          className={`${open ? "" : "hidden sm:block"} flex-1 min-w-0 bg-transparent text-sm text-gray-900 dark:text-white placeholder:text-gray-400 outline-none`}
        />
        {!open && <kbd className="hidden sm:inline text-[10px] font-semibold text-gray-400 border border-gray-300 dark:border-gray-600 rounded px-1">/</kbd>}
      </div>

      {open && ready && (
        <div className="fixed left-3 right-3 top-12 sm:absolute sm:left-auto sm:right-0 sm:top-auto sm:mt-2 sm:w-[22rem] max-h-[70vh] overflow-y-auto bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 shadow-xl rounded-2xl p-2 z-30">
          {loading && hits.length === 0 && <p className="text-xs text-gray-400 text-center py-4">Searching…</p>}
          {failed === q && <p className="text-xs text-gray-400 text-center py-4">Search is unavailable right now.</p>}
          {!loading && failed !== q && hits.length === 0 && (
            <p className="text-xs text-gray-400 text-center py-4">No team or player found for “{q}”.</p>
          )}
          {teams.length > 0 && (
            <>
              <p className="px-3 pt-1 pb-1 text-[10px] font-semibold uppercase tracking-widest text-gray-400">Teams</p>
              {teams.map(row)}
            </>
          )}
          {players.length > 0 && (
            <>
              <p className="px-3 pt-2 pb-1 text-[10px] font-semibold uppercase tracking-widest text-gray-400">Players</p>
              {players.map(row)}
            </>
          )}
        </div>
      )}
    </div>
  );
}
