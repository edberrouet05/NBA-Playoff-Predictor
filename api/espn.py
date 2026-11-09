"""ESPN's public API: JSON fetch, scores, rosters, athlete ids and names."""


def _espn_json(url: str, timeout: int = 15) -> dict:
    import json, urllib.request
    req = urllib.request.Request(url.replace("http://", "https://"), headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def _espn_score(c: dict) -> int | None:
    s = c.get("score")
    if isinstance(s, dict):
        s = s.get("value", s.get("displayValue"))
    try:
        return int(float(s)) if s not in (None, "") else None
    except (TypeError, ValueError):
        return None


_ROSTER_GROUP_LABELS = {
    "offense": "Offense", "defense": "Defense", "specialTeam": "Special Teams",
    "injuredReserveOrOut": "Injured Reserve / Out", "suspended": "Suspended", "practiceSquad": "Practice Squad",
}
# Display order inside a group (unlisted positions go last)
_ROSTER_POS_ORDER = {
    "nfl": ["QB", "RB", "FB", "WR", "TE", "OT", "G", "C", "OL", "DE", "DT", "NT", "DL", "LB", "OLB", "ILB",
            "CB", "S", "SAF", "DB", "PK", "K", "P", "LS"],
    "mlb": ["SP", "RP", "P", "C", "1B", "2B", "3B", "SS", "IF", "LF", "CF", "RF", "OF", "DH"],
    "nba": ["PG", "SG", "G", "SF", "F", "PF", "C"],
    "nhl": ["C", "LW", "RW", "F", "D", "G"],
}


def _team_roster(sport: str, league: str, team_id: str) -> tuple[list[dict], dict[str, dict]]:
    """Roster grouped like ESPN (offense / defense…, pitchers / catchers…) + raw athletes by id."""
    try:
        r = _espn_json(f"https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}/teams/{team_id}/roster")
    except Exception:
        return [], {}
    athletes = r.get("athletes", [])
    raw_groups = athletes if athletes and "items" in athletes[0] else [{"position": "Roster", "items": athletes}]
    order = _ROSTER_POS_ORDER.get(league, [])
    by_id: dict[str, dict] = {}
    groups = []
    for g in raw_groups:
        players = []
        for p in g.get("items", []):
            by_id[str(p.get("id"))] = p
            pos = (p.get("position") or {}).get("abbreviation", "")
            inj = (p.get("injuries") or [{}])[0]
            players.append({
                "id": str(p.get("id")), "name": p.get("displayName", ""), "jersey": p.get("jersey"),
                "position": pos, "age": p.get("age"), "experience": (p.get("experience") or {}).get("years"),
                "headshot": (p.get("headshot") or {}).get("href"),
                "injury": inj.get("status"),
                "height": p.get("displayHeight"), "weight": p.get("displayWeight"),
                "college": (p.get("college") or {}).get("name"),
                "bats_throws": "/".join(x for x in ((p.get("bats") or {}).get("abbreviation"),
                                                     (p.get("throws") or {}).get("abbreviation")) if x) or None,
            })
        if not players:
            continue
        players.sort(key=lambda x: (order.index(x["position"]) if x["position"] in order else len(order),
                                    int(x["jersey"]) if str(x["jersey"] or "").isdigit() else 999))
        name = g.get("position", "")
        groups.append({"name": _ROSTER_GROUP_LABELS.get(name, name), "players": players})
    return groups, by_id


def _norm_name(s: str) -> str:
    """'Ja'Marr Chase' → 'jamarr chase', 'Luka Dončić' → 'luka doncic', 'Hines-Allen' → 'hines allen'."""
    import unicodedata
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    s = "".join(c for c in s if c not in "'.`’")
    return " ".join("".join(c if c.isalnum() else " " for c in s).split())


def _stat_num(v: str) -> float | None:
    """'3-7' → 3, '6.2' innings stay as-is (converted separately), '1,234' → 1234, '-' → None."""
    if v in (None, "", "-", "--"):
        return None
    s = str(v).replace(",", "")
    if "-" in s[1:]:
        s = s.split("-")[0]
    try:
        return float(s)
    except ValueError:
        return None


def _innings_to_float(v: float) -> float:
    whole = int(v)
    return whole + round((v - whole) * 10) / 3   # 6.2 innings = 6⅔


def _espn_athlete_id(ath: dict) -> str | None:
    """Athlete id from an ESPN athlete object (direct field or profile link)."""
    import re
    if ath.get("id"):
        return str(ath["id"])
    for link in ath.get("links", []) or []:
        m = re.search(r"/id/(\d+)", link.get("href", ""))
        if m:
            return m.group(1)
    return None
