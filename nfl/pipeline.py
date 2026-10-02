#!/usr/bin/env python3
"""
NFL Data Pipeline
Builds NFL features from nflverse open data and outputs:
  data/nfl/nfl_stats_current.csv          — live team state (standings, form, Elo, EPA, QB)
  data/nfl/nfl_game_features_current.csv  — per-game feature rows for every current-season
                                            game (played → pre-game values, upcoming → latest)
  data/nfl/nfl_qb_ratings.csv             — shrunk EPA/dropback for every QB (API QB overrides)
  data/nfl/nfl_power_history.csv          — every team's state entering each week (power-index trend)
  data/processed/nfl_training_data.csv    — labelled rows for model training

Sources (no API key, cached under data/nfl/raw/):
  - nflverse games.csv : schedule, scores, rest, division flag, venue, starting QBs
                          (projected starters for next week's games), ESPN event ids
  - nflverse play-by-play : EPA per play → team offense/defense efficiency and QB ratings

Features (one row per team per game, mirrored for the opponent):
  - Elo rating (538-style: margin-of-victory multiplier, 1/3 regression between
    seasons), run continuously since 1999 so there's no week-1 cold start
  - Recency-weighted offensive / defensive EPA per play, carried across seasons
  - Starting-QB EPA/dropback (shrunk toward replacement level) + QB-change flag
  - Rest / bye week, home field (travel distance and division game are also
    exported but not used by the model — they showed no predictive value)
  - Legacy points-and-record features (last-5 form, prior-season record)

Run:
    python nfl/pipeline.py

Estimated runtime: ~3-5 minutes on first run (play-by-play download), <1 min after.
"""

import json
import math
import re
import time
import urllib.request
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

ROOT      = Path(__file__).parent.parent
NFL_DIR   = ROOT / "data" / "nfl"
RAW_DIR   = NFL_DIR / "raw"
PROCESSED = ROOT / "data" / "processed"
for _d in (NFL_DIR, RAW_DIR, PROCESSED):
    _d.mkdir(parents=True, exist_ok=True)

CURRENT_SEASON = 2026
TRAIN_SEASONS  = list(range(2015, CURRENT_SEASON))  # rows used for training
PBP_START      = 2013                                # 2 seasons of EPA/QB burn-in before training rows

GAMES_URL = "https://github.com/nflverse/nfldata/raw/master/data/games.csv"
PBP_URL   = "https://github.com/nflverse/nflverse-data/releases/download/pbp/play_by_play_{season}.csv.gz"
INJ_URL   = "https://github.com/nflverse/nflverse-data/releases/download/injuries/injuries_{season}.csv"
SNAPS_URL = "https://github.com/nflverse/nflverse-data/releases/download/snap_counts/snap_counts_{season}.csv"
ESPN_BASE = "https://site.api.espn.com/apis/site/v2/sports/football/nfl"

# ── Model constants ─────────────────────────────────────────────────────────────
ELO_MEAN      = 1505.0
ELO_K         = 20.0
ELO_HFA       = 48.0     # home-field bonus used only inside the Elo update
ELO_REVERT    = 1 / 3    # fraction regressed to the mean between seasons

EPA_DECAY        = 0.90  # per-game weight decay (~6.5-game half-life)
EPA_SEASON_DECAY = 0.50  # extra decay at a season boundary
EPA_PRIOR_W      = 1.5   # pseudo-games of league-average (0 EPA) → shrinks early-season noise

QB_DECAY    = 0.98       # per-game decay of a QB's dropback history
QB_PRIOR_N  = 150        # pseudo-dropbacks of replacement-level play
QB_PRIOR    = -0.10      # replacement-level EPA/dropback

BYE_REST = 13            # rest days ≥ this ⇒ coming off a bye

# Non-QB injuries: a player's weight is his snap share over the team's last ROLE_WINDOW
# games (so long-term absences the team already adapted to count ~0), times his status.
ROLE_WINDOW   = 4
INJURY_WEIGHT = {"Out": 1.0, "Doubtful": 0.8, "Questionable": 0.25}

# Relocated franchises → current abbreviation (keeps Elo / EPA history continuous)
TEAM_ALIASES = {"OAK": "LV", "SD": "LAC", "STL": "LA"}

# nflverse abbreviation → ESPN displayName (what the API / frontend use)
TEAM_NAMES = {
    "ARI": "Arizona Cardinals",    "ATL": "Atlanta Falcons",       "BAL": "Baltimore Ravens",
    "BUF": "Buffalo Bills",        "CAR": "Carolina Panthers",     "CHI": "Chicago Bears",
    "CIN": "Cincinnati Bengals",   "CLE": "Cleveland Browns",      "DAL": "Dallas Cowboys",
    "DEN": "Denver Broncos",       "DET": "Detroit Lions",         "GB":  "Green Bay Packers",
    "HOU": "Houston Texans",       "IND": "Indianapolis Colts",    "JAX": "Jacksonville Jaguars",
    "KC":  "Kansas City Chiefs",   "LV":  "Las Vegas Raiders",     "LAC": "Los Angeles Chargers",
    "LA":  "Los Angeles Rams",     "MIA": "Miami Dolphins",        "MIN": "Minnesota Vikings",
    "NE":  "New England Patriots", "NO":  "New Orleans Saints",    "NYG": "New York Giants",
    "NYJ": "New York Jets",        "PHI": "Philadelphia Eagles",   "PIT": "Pittsburgh Steelers",
    "SF":  "San Francisco 49ers",  "SEA": "Seattle Seahawks",      "TB":  "Tampa Bay Buccaneers",
    "TEN": "Tennessee Titans",     "WAS": "Washington Commanders",
}

# Venue coordinates (lat, lon) by nflverse stadium_id
STADIUM_COORDS = {
    "ATL00": (33.757, -84.401), "ATL97": (33.755, -84.401), "BAL00": (39.278, -76.623),
    "BOS00": (42.091, -71.264), "BUF00": (42.774, -78.787), "BUF01": (43.641, -79.389),
    "CAR00": (35.226, -80.853), "CHI98": (41.862, -87.617), "CIN00": (39.095, -84.516),
    "CLE00": (41.506, -81.700), "DAL00": (32.748, -97.093), "DEN00": (39.744, -105.020),
    "DET00": (42.340, -83.046), "GNB00": (44.501, -88.062), "HOU00": (29.685, -95.411),
    "IND00": (39.760, -86.164), "JAX00": (30.324, -81.637), "KAN00": (39.049, -94.484),
    "LAX01": (33.953, -118.339), "LAX97": (33.864, -118.261), "LAX99": (34.014, -118.288),
    "MIA00": (25.958, -80.239), "MIN00": (44.974, -93.258), "MIN01": (44.974, -93.258),
    "MIN98": (44.976, -93.225), "NAS00": (36.166, -86.771), "NOR00": (29.951, -90.081),
    "NYC01": (40.813, -74.074), "OAK00": (37.752, -122.201), "PHI00": (39.901, -75.168),
    "PHO00": (33.528, -112.263), "PIT00": (40.447, -80.016), "SDG00": (32.783, -117.120),
    "SEA00": (47.595, -122.332), "SFO00": (37.714, -122.386), "SFO01": (37.403, -121.970),
    "STL00": (38.633, -90.189), "TAM00": (27.976, -82.503), "VEG00": (36.091, -115.184),
    "WAS00": (38.908, -76.864),
    # International / neutral sites
    "LON00": (51.556, -0.280), "LON01": (51.456, -0.342), "LON02": (51.604, -0.066),
    "MEX00": (19.303, -99.150), "GER00": (48.219, 11.625), "MUN01": (48.219, 11.625),
    "FRA00": (50.069, 8.645),   "MAD01": (40.453, -3.688), "MEL00": (-37.820, 144.983),
    "SAO00": (-23.545, -46.474), "RIO00": (-22.912, -43.230), "PAR00": (48.924, 2.360),
}

# Team home stadium (current); relocations handled in _team_home()
TEAM_STADIUM = {
    "ARI": "PHO00", "ATL": "ATL97", "BAL": "BAL00", "BUF": "BUF00", "CAR": "CAR00",
    "CHI": "CHI98", "CIN": "CIN00", "CLE": "CLE00", "DAL": "DAL00", "DEN": "DEN00",
    "DET": "DET00", "GB":  "GNB00", "HOU": "HOU00", "IND": "IND00", "JAX": "JAX00",
    "KC":  "KAN00", "LA":  "LAX01", "LAC": "LAX01", "LV":  "VEG00", "MIA": "MIA00",
    "MIN": "MIN01", "NE":  "BOS00", "NO":  "NOR00", "NYG": "NYC01", "NYJ": "NYC01",
    "PHI": "PHI00", "PIT": "PIT00", "SEA": "SEA00", "SF":  "SFO01", "TB":  "TAM00",
    "TEN": "NAS00", "WAS": "WAS00",
}


# ── Helpers ─────────────────────────────────────────────────────────────────────

def _progress(msg: str) -> None:
    print(msg, flush=True)


def _download(url: str, dest: Path, timeout: int = 120) -> Path:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        dest.write_bytes(resp.read())
    return dest


def _get_json(url: str, timeout: int = 20) -> dict:
    # ESPN's edge 403s incomplete browser UAs; the bare "Mozilla/5.0" passes.
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def _norm(team: str) -> str:
    return TEAM_ALIASES.get(team, team)


def _team_home(team: str, season: int) -> tuple[float, float]:
    if team == "LV" and season < 2020:
        return STADIUM_COORDS["OAK00"]
    if team == "LAC" and season < 2017:
        return STADIUM_COORDS["SDG00"]
    if team == "LA" and season < 2016:
        return STADIUM_COORDS["STL00"]
    return STADIUM_COORDS[TEAM_STADIUM[team]]


def _haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 6371.0 * 2 * math.asin(math.sqrt(h))


def _clean_id(v) -> str | None:
    return v if isinstance(v, str) and v else None


def _vegas_home_prob(home_ml, away_ml) -> float | None:
    """No-vig implied home win probability from American moneylines."""
    if pd.isna(home_ml) or pd.isna(away_ml):
        return None
    def _imp(ml: float) -> float:
        return -ml / (-ml + 100) if ml < 0 else 100 / (ml + 100)
    h, a = _imp(float(home_ml)), _imp(float(away_ml))
    return h / (h + a)


# ── Data loading ────────────────────────────────────────────────────────────────

def load_games() -> pd.DataFrame:
    """nflverse schedule/results, always re-downloaded (QB projections change daily)."""
    path = RAW_DIR / "games.csv"
    try:
        _download(GAMES_URL, path)
    except Exception as e:
        if not path.exists():
            raise
        _progress(f"  WARNING: games.csv download failed ({e}) — using cached copy")
    g = pd.read_csv(path, low_memory=False)
    g["home_team"] = g["home_team"].map(_norm)
    g["away_team"] = g["away_team"].map(_norm)
    g = g.sort_values(["season", "gameday", "gametime", "game_id"]).reset_index(drop=True)
    return g


def load_pbp(seasons: list[int]) -> pd.DataFrame:
    """Play-by-play for the given seasons (past seasons cached; current season refreshed)."""
    cols = ["game_id", "posteam", "defteam", "epa", "pass", "rush", "qb_dropback", "qb_epa", "id", "play_type"]
    frames = []
    for season in seasons:
        path = RAW_DIR / f"play_by_play_{season}.csv.gz"
        if season >= CURRENT_SEASON or not path.exists():
            _progress(f"  Downloading play-by-play {season}...")
            try:
                _download(PBP_URL.format(season=season), path)
            except Exception as e:
                if not path.exists():
                    _progress(f"    WARNING: no play-by-play for {season} ({e})")
                    continue
                _progress(f"    WARNING: download failed ({e}) — using cached copy")
        frames.append(pd.read_csv(path, usecols=cols, low_memory=False))
    pbp = pd.concat(frames, ignore_index=True)
    pbp["posteam"] = pbp["posteam"].map(_norm, na_action="ignore")
    pbp["defteam"] = pbp["defteam"].map(_norm, na_action="ignore")
    return pbp


# ── Non-QB injuries ─────────────────────────────────────────────────────────────

def player_key(name: str) -> str:
    """Name key shared by injury reports and snap counts ('A.J. Brown Jr.' → 'aj brown')."""
    s = re.sub(r"[^a-z ]", "", str(name).lower())
    return " ".join(w for w in s.split() if w not in ("jr", "sr", "ii", "iii", "iv", "v"))


def _load_yearly(url: str, sub: str, seasons: list[int]) -> pd.DataFrame:
    """nflverse yearly CSVs (past seasons cached; current season refreshed)."""
    folder = RAW_DIR / sub
    folder.mkdir(exist_ok=True)
    frames = []
    for season in seasons:
        path = folder / f"{sub}_{season}.csv"
        if season >= CURRENT_SEASON or not path.exists():
            try:
                _download(url.format(season=season), path)
            except Exception as e:
                if not path.exists():
                    _progress(f"    WARNING: no {sub} for {season} ({e})")
                    continue
        frames.append(pd.read_csv(path, low_memory=False))
    out = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if not out.empty:
        out["team"] = out["team"].map(_norm)
    return out


class PlayerRoles:
    """Each player's snap share over his team's last ROLE_WINDOW games before a given week."""

    def __init__(self, snaps: pd.DataFrame):
        snaps = snaps.assign(key=snaps["player"].map(player_key))
        self.games: dict[str, list[tuple[int, int]]] = {}
        self.shares: dict[tuple[str, int, int], pd.DataFrame] = {}
        for (team, season, week), g in snaps.groupby(["team", "season", "week"]):
            self.games.setdefault(team, []).append((int(season), int(week)))
            self.shares[(team, int(season), int(week))] = g.set_index("key")[["player", "offense_pct", "defense_pct"]]
        for team in self.games:
            self.games[team].sort()

    def before(self, team: str, season: int, week: int) -> pd.DataFrame:
        """key → (player, off share, def share) averaged over the last games before (season, week);
        a player who missed one of those games counts 0 for it."""
        prev = [g for g in self.games.get(team, []) if g < (season, week)][-ROLE_WINDOW:]
        if not prev:
            return pd.DataFrame(columns=["player", "offense_pct", "defense_pct"])
        hist = pd.concat(self.shares[(team, s, w)] for s, w in prev)
        shares = hist.groupby(level=0)[["offense_pct", "defense_pct"]].sum() / len(prev)
        return shares.join(hist.groupby(level=0)["player"].first())


def injury_loss(injuries: pd.DataFrame, roles: PlayerRoles) -> dict[tuple[int, int, str], float]:
    """(season, week, team) → status-weighted snap share of non-QB players on the injury report
    (≈ number of every-down starters missing)."""
    rep = injuries[injuries["report_status"].isin(INJURY_WEIGHT) & (injuries["position"] != "QB")]
    rep = rep.assign(key=rep["full_name"].map(player_key))
    out = {}
    for (season, week, team), g in rep.groupby(["season", "week", "team"]):
        r = roles.before(team, int(season), int(week))
        if r.empty:
            continue
        share = (r["offense_pct"] + r["defense_pct"]).reindex(g["key"]).fillna(0.0).to_numpy()
        out[(int(season), int(week), team)] = float((share * g["report_status"].map(INJURY_WEIGHT).to_numpy()).sum())
    return out


def add_injury_feature(rows: pd.DataFrame, loss: dict[tuple[int, int, str], float]) -> pd.DataFrame:
    def get(season, week, team):
        return loss.get((int(season), int(week), team), 0.0)
    team_loss = [get(s, w, t) for s, w, t in zip(rows["season"], rows["week"], rows["team"])]
    opp_loss  = [get(s, w, t) for s, w, t in zip(rows["season"], rows["week"], rows["opp"])]
    return rows.assign(inj_total_diff=np.array(team_loss) - np.array(opp_loss))


def save_current_roles(roles: PlayerRoles, season: int) -> None:
    """Snap shares going into each team's next game — the API weighs ESPN's live injury report with these."""
    out = []
    for team, games in roles.games.items():
        r = roles.before(team, season + 1, 0)   # i.e. after the team's latest game
        r = r[(r["offense_pct"] + r["defense_pct"]) > 0]
        out.append(r.reset_index().rename(columns={"index": "key"}).assign(team=TEAM_NAMES.get(team, team)))
    df = pd.concat(out, ignore_index=True)[["team", "key", "player", "offense_pct", "defense_pct"]]
    df.round(3).to_csv(NFL_DIR / "nfl_player_roles.csv", index=False)
    _progress(f"  Saved: {NFL_DIR / 'nfl_player_roles.csv'}  ({len(df):,} players)")


def summarise_pbp(pbp: pd.DataFrame) -> tuple[dict, dict]:
    """Return per-game team EPA and per-game QB dropback totals.

    team_game[(game_id, team)] = {off_epa, off_pass_epa, def_epa, def_pass_epa,   (per play)
                                  off_pts, def_pts, st_pts}                         (per game totals)
    qb_game[game_id]           = [(qb_id, epa_sum, dropbacks), ...]
    """
    plays = pbp[((pbp["pass"] == 1) | (pbp["rush"] == 1)) & pbp["epa"].notna() & pbp["posteam"].notna()]
    passes = plays[plays["pass"] == 1]

    off  = plays.groupby(["game_id", "posteam"])["epa"].mean()
    offp = passes.groupby(["game_id", "posteam"])["epa"].mean()
    dfn  = plays.groupby(["game_id", "defteam"])["epa"].mean()
    dfnp = passes.groupby(["game_id", "defteam"])["epa"].mean()

    team_game: dict[tuple[str, str], dict] = {}
    for key, v in off.items():
        team_game.setdefault(key, {})["off_epa"] = v
    for key, v in offp.items():
        team_game.setdefault(key, {})["off_pass_epa"] = v
    for key, v in dfn.items():
        team_game.setdefault(key, {})["def_epa"] = v
    for key, v in dfnp.items():
        team_game.setdefault(key, {})["def_pass_epa"] = v

    # Per-game EPA totals ≈ points added: offense, defense allowed, special teams
    for key, v in plays.groupby(["game_id", "posteam"])["epa"].sum().items():
        team_game.setdefault(key, {})["off_pts"] = v
    for key, v in plays.groupby(["game_id", "defteam"])["epa"].sum().items():
        team_game.setdefault(key, {})["def_pts"] = v
    # Special-teams EPA is from the possession team's view (receiving team on kickoffs/punts)
    st = pbp[pbp["play_type"].isin(["kickoff", "punt", "field_goal", "extra_point"]) & pbp["epa"].notna()]
    st_for = st.groupby(["game_id", "posteam"])["epa"].sum()
    st_against = st.groupby(["game_id", "defteam"])["epa"].sum()
    for key in set(st_for.index) | set(st_against.index):
        team_game.setdefault(key, {})["st_pts"] = st_for.get(key, 0.0) - st_against.get(key, 0.0)

    db = pbp[(pbp["qb_dropback"] == 1) & pbp["qb_epa"].notna() & pbp["id"].notna()]
    agg = db.groupby(["game_id", "id"])["qb_epa"].agg(["sum", "count"]).reset_index()
    qb_game: dict[str, list] = defaultdict(list)
    for r in agg.itertuples(index=False):
        qb_game[r.game_id].append((r.id, float(r.sum), int(r.count)))
    return team_game, qb_game


# ── Rolling state trackers ──────────────────────────────────────────────────────

class Elo:
    def __init__(self):
        self.rating: dict[str, float] = defaultdict(lambda: ELO_MEAN)
        self.season: dict[str, int] = {}

    def start_game(self, team: str, season: int) -> float:
        if team in self.season and self.season[team] != season:
            self.rating[team] = self.rating[team] * (1 - ELO_REVERT) + ELO_MEAN * ELO_REVERT
        self.season[team] = season
        return self.rating[team]

    def update(self, home: str, away: str, margin: int, neutral: bool) -> None:
        dr = self.rating[home] + (0.0 if neutral else ELO_HFA) - self.rating[away]
        exp_home = 1 / (1 + 10 ** (-dr / 400))
        if margin == 0:
            res, mult = 0.5, 1.0
        else:
            res = 1.0 if margin > 0 else 0.0
            winner_dr = dr if margin > 0 else -dr
            mult = math.log(abs(margin) + 1) * 2.2 / (winner_dr * 0.001 + 2.2)
        shift = ELO_K * mult * (res - exp_home)
        self.rating[home] += shift
        self.rating[away] -= shift


class TeamEPA:
    """Exponentially-weighted EPA per play, shrunk toward league average (0)."""
    KEYS = ("off_epa", "off_pass_epa", "def_epa", "def_pass_epa", "off_pts", "def_pts", "st_pts")

    def __init__(self):
        self.sums: dict[str, dict[str, list[float]]] = defaultdict(lambda: {k: [0.0, 0.0] for k in self.KEYS})
        self.season: dict[str, int] = {}

    def value(self, team: str, season: int) -> dict[str, float]:
        if team in self.season and self.season[team] != season:
            for k in self.KEYS:
                self.sums[team][k][0] *= EPA_SEASON_DECAY
                self.sums[team][k][1] *= EPA_SEASON_DECAY
        self.season[team] = season
        return {k: sx / (sw + EPA_PRIOR_W) for k, (sx, sw) in self.sums[team].items()}

    def update(self, team: str, game_vals: dict[str, float]) -> None:
        for k in self.KEYS:
            s = self.sums[team][k]
            s[0] *= EPA_DECAY
            s[1] *= EPA_DECAY
            v = game_vals.get(k)
            if v is not None and not pd.isna(v):
                s[0] += v
                s[1] += 1.0


class QBRatings:
    """Decayed EPA per dropback per QB, shrunk toward replacement level."""

    def __init__(self):
        self.epa: dict[str, float] = defaultdict(float)
        self.n: dict[str, float] = defaultdict(float)
        self.name: dict[str, str] = {}
        self.starts: dict[str, int] = defaultdict(int)

    def rating(self, qb_id: str | None) -> float:
        if not qb_id:
            return QB_PRIOR
        return (self.epa[qb_id] + QB_PRIOR_N * QB_PRIOR) / (self.n[qb_id] + QB_PRIOR_N)

    def update(self, qb_id: str, epa_sum: float, dropbacks: int) -> None:
        self.epa[qb_id] = self.epa[qb_id] * QB_DECAY + epa_sum
        self.n[qb_id]   = self.n[qb_id] * QB_DECAY + dropbacks


def _rolling_form(history: list[dict]) -> tuple[float, float]:
    """(recency-weighted win% over last 5, avg point diff over last 5) — current season only."""
    recent = history[-5:]
    if not recent:
        return 0.5, 0.0
    weights = [0.85 ** i for i in range(len(recent) - 1, -1, -1)]
    win_pct = sum(w * (1.0 if g["won"] else 0.0) for w, g in zip(weights, recent)) / sum(weights)
    pt_diff = sum(g["point_diff"] for g in recent) / len(recent)
    return round(win_pct, 3), round(pt_diff, 2)


# ── Feature builder ─────────────────────────────────────────────────────────────

def build_features(games: pd.DataFrame, team_game: dict, qb_game: dict, first_row_season: int):
    """Walk every game chronologically, emitting pre-game feature rows (two per game)
    for seasons ≥ first_row_season, then updating all rolling state with the result.

    Returns (rows DataFrame, end-state dict for the current-season team table, QBRatings).
    """
    elo, epa, qbs = Elo(), TeamEPA(), QBRatings()
    last_qb: dict[str, str] = {}
    season_hist: dict[tuple[str, int], list[dict]] = defaultdict(list)
    season_record: dict[tuple[str, int], list[float]] = defaultdict(lambda: [0.0, 0.0, 0.0])  # games, win pts, point diff

    rows: list[dict] = []
    snapshots: list[dict] = []      # current season: every team's state entering each week
    snap_week = 0
    week_games: dict[int, list[bool]] = defaultdict(list)   # current season: week -> [completed?]
    for g in games.itertuples(index=False):
        season, home, away = int(g.season), g.home_team, g.away_team
        if home not in TEAM_NAMES or away not in TEAM_NAMES:
            continue
        completed = not pd.isna(g.home_score) and not pd.isna(g.away_score)

        if season == CURRENT_SEASON and g.game_type == "REG" and int(g.week) > snap_week:
            snap_week = int(g.week)
            for team in TEAM_NAMES:
                snapshots.append({"week": snap_week, "team": team,
                                  "elo": round(elo.start_game(team, season), 1),
                                  **{k: round(v, 4) for k, v in epa.value(team, season).items()},
                                  "qb_epa": round(qbs.rating(last_qb.get(team)), 4)})
        if season == CURRENT_SEASON and g.game_type == "REG":
            week_games[int(g.week)].append(completed)
        neutral = g.location == "Neutral"

        elo_h, elo_a = elo.start_game(home, season), elo.start_game(away, season)
        epa_h, epa_a = epa.value(home, season), epa.value(away, season)

        if season >= first_row_season:
            venue = STADIUM_COORDS.get(g.stadium_id) if neutral else None
            venue = venue or _team_home(home, season)

            side = {}
            for team, qb_col, rest_col in ((home, "home_qb_id", "home_rest"), (away, "away_qb_id", "away_rest")):
                qb_id = _clean_id(getattr(g, qb_col)) or last_qb.get(team)
                rest = getattr(g, rest_col)
                rest = 7 if pd.isna(rest) else int(rest)
                prev = season_record.get((team, season - 1), [0.0, 0.0, 0.0])
                l5, pd5 = _rolling_form(season_hist[(team, season)])
                side[team] = {
                    "qb_id":        qb_id,
                    "qb_epa":       qbs.rating(qb_id),
                    "qb_changed":   int(team in last_qb and qb_id is not None and qb_id != last_qb[team]),
                    "rest_days":    min(rest, 14),
                    "off_bye":      int(rest >= BYE_REST),
                    "travel_km":    _haversine_km(_team_home(team, season), venue),
                    "prev_win_pct": prev[1] / prev[0] if prev[0] else 0.5,
                    "prev_pd_pg":   prev[2] / prev[0] if prev[0] else 0.0,
                    "win_pct_last5": l5, "point_diff_last5": pd5,
                }
            side[home].update(elo=elo_h, **epa_h)
            side[away].update(elo=elo_a, **epa_a)

            margin_home = (g.home_score - g.away_score) if completed else None
            vegas_home = _vegas_home_prob(g.home_moneyline, g.away_moneyline)
            for team, opp, is_home in ((home, away, 1), (away, home, 0)):
                t, o = side[team], side[opp]
                won = None
                if completed and margin_home != 0:
                    won = int((margin_home > 0) == bool(is_home))
                rows.append({
                    "season": season, "week": int(g.week), "game_type": g.game_type,
                    "game_date": g.gameday, "game_id": g.game_id,
                    "espn_id": None if pd.isna(g.espn) else str(g.espn).split(".")[0],
                    "team": team, "opp": opp,
                    "team_name": TEAM_NAMES[team], "opp_name": TEAM_NAMES[opp],
                    "home": int(is_home and not neutral),
                    "div_game": int(g.div_game) if not pd.isna(g.div_game) else 0,
                    "elo": round(t["elo"], 1), "opp_elo": round(o["elo"], 1),
                    "elo_diff": round(t["elo"] - o["elo"], 1),
                    "off_epa": round(t["off_epa"], 4), "def_epa": round(t["def_epa"], 4),
                    "opp_off_epa": round(o["off_epa"], 4), "opp_def_epa": round(o["def_epa"], 4),
                    "off_pass_epa": round(t["off_pass_epa"], 4), "def_pass_epa": round(t["def_pass_epa"], 4),
                    "opp_off_pass_epa": round(o["off_pass_epa"], 4), "opp_def_pass_epa": round(o["def_pass_epa"], 4),
                    "net_epa_diff": round((t["off_epa"] - t["def_epa"]) - (o["off_epa"] - o["def_epa"]), 4),
                    "qb_id": t["qb_id"], "opp_qb_id": o["qb_id"],
                    "last_qb_id": last_qb.get(team), "opp_last_qb_id": last_qb.get(opp),
                    "qb_epa": round(t["qb_epa"], 4), "opp_qb_epa": round(o["qb_epa"], 4),
                    "qb_epa_diff": round(t["qb_epa"] - o["qb_epa"], 4),
                    "qb_changed": t["qb_changed"], "opp_qb_changed": o["qb_changed"],
                    "rest_days": t["rest_days"], "opp_rest_days": o["rest_days"],
                    "rest_diff": t["rest_days"] - o["rest_days"],
                    "off_bye": t["off_bye"], "opp_off_bye": o["off_bye"],
                    "travel_km": round(t["travel_km"]), "opp_travel_km": round(o["travel_km"]),
                    "travel_diff_1000km": round((t["travel_km"] - o["travel_km"]) / 1000, 3),
                    "prev_season_win_pct_diff": round(t["prev_win_pct"] - o["prev_win_pct"], 3),
                    "prev_season_point_diff_diff": round(t["prev_pd_pg"] - o["prev_pd_pg"], 2),
                    "win_pct_last5": t["win_pct_last5"], "point_diff_last5": t["point_diff_last5"],
                    "opp_win_pct_last5": o["win_pct_last5"], "opp_point_diff_last5": o["point_diff_last5"],
                    # Evaluation only (not a model feature): closing no-vig moneyline probability
                    "vegas_prob": None if vegas_home is None else round(vegas_home if is_home else 1 - vegas_home, 4),
                    "win": won,
                })

        if not completed:
            continue

        # ── Post-game state updates ────────────────────────────────────────────
        margin = int(g.home_score - g.away_score)
        elo.update(home, away, margin, neutral)
        for team, opp, m in ((home, away, margin), (away, home, -margin)):
            if (g.game_id, team) in team_game:
                epa.update(team, team_game[(g.game_id, team)])
            if g.game_type == "REG":
                rec = season_record[(team, season)]
                rec[0] += 1
                rec[1] += 1.0 if m > 0 else 0.5 if m == 0 else 0.0
                rec[2] += m
                season_hist[(team, season)].append({"won": m > 0, "point_diff": m})
        for qb_id, epa_sum, n in qb_game.get(g.game_id, []):
            qbs.update(qb_id, epa_sum, n)
        for team, qb_col, name_col in ((home, "home_qb_id", "home_qb_name"), (away, "away_qb_id", "away_qb_name")):
            qb_id = _clean_id(getattr(g, qb_col))
            if qb_id:
                last_qb[team] = qb_id
                qbs.starts[qb_id] += 1
                if isinstance(getattr(g, name_col), str):
                    qbs.name[qb_id] = getattr(g, name_col)

    state = {}
    for team in TEAM_NAMES:
        e = epa.value(team, CURRENT_SEASON)
        qb_id = last_qb.get(team)
        prev = season_record.get((team, CURRENT_SEASON - 1), [0.0, 0.0, 0.0])
        l5, pd5 = _rolling_form(season_hist[(team, CURRENT_SEASON)])
        state[team] = {
            "elo": round(elo.start_game(team, CURRENT_SEASON), 1),
            **{k: round(v, 4) for k, v in e.items()},
            "qb_id": qb_id, "qb_name": qbs.name.get(qb_id, ""), "qb_epa": round(qbs.rating(qb_id), 4),
            "prev_season_win_pct": round(prev[1] / prev[0], 3) if prev[0] else 0.5,
            "prev_season_point_diff_per_game": round(prev[2] / prev[0], 2) if prev[0] else 0.0,
            "win_pct_last5": l5, "point_diff_last5": pd5,
        }
    # Keep snapshots up to the last fully completed week: "entering week N" is last
    # week's ranking once week N is over, which is what the power-index trend compares to
    full_weeks = [w for w, done in week_games.items() if done and all(done)]
    snaps = pd.DataFrame(snapshots)
    if not snaps.empty:
        snaps = snaps[snaps["week"] <= max(full_weeks, default=1)]
    return pd.DataFrame(rows), state, qbs, snaps


# ── Current-season team table (inference + standings page) ──────────────────────

def get_espn_standings(season: int) -> dict[str, dict]:
    try:
        data = _get_json(f"https://site.api.espn.com/apis/v2/sports/football/nfl/standings?season={season}&level=3")
    except Exception as e:
        _progress(f"    WARNING: standings fetch failed for {season}: {e}")
        return {}
    result: dict[str, dict] = {}
    for conf in data.get("children", []):
        for div in conf.get("children", []):
            for entry in div.get("standings", {}).get("entries", []):
                name  = entry.get("team", {}).get("displayName", "")
                stats = {s["name"]: s.get("value") for s in entry.get("stats", [])}
                w, l, t = (float(stats.get(k, 0) or 0) for k in ("wins", "losses", "ties"))
                result.setdefault(name, {}).update(
                    conference=conf.get("abbreviation") or conf.get("name", ""), division=div.get("name", ""))
                gp = w + l + t
                pd_ = float(stats.get("pointDifferential", 0) or 0)
                result[name].update({
                    "wins": int(w), "losses": int(l), "ties": int(t), "games_played": int(gp),
                    "win_pct": round((w + 0.5 * t) / gp, 3) if gp > 0 else 0.5,
                    "point_diff_per_game": round(pd_ / gp, 2) if gp > 0 else 0.0,
                })
    return result


def save_games_history(games: pd.DataFrame) -> pd.DataFrame:
    """Completed games with ESPN team names — used by the API for head-to-head records."""
    done = games[games["home_score"].notna() & games["away_score"].notna()].copy()
    done["away_team"] = done["away_team"].map(TEAM_NAMES)
    done["home_team"] = done["home_team"].map(TEAM_NAMES)
    done["espn"] = pd.to_numeric(done["espn"], errors="coerce").astype("Int64")
    cols = ["season", "game_type", "week", "gameday", "location", "away_team", "home_team",
            "away_score", "home_score", "overtime", "away_qb_name", "home_qb_name",
            "away_coach", "home_coach", "stadium", "espn"]
    out = done[cols].dropna(subset=["away_team", "home_team"])
    out = out.astype({"away_score": int, "home_score": int})
    out.to_csv(NFL_DIR / "nfl_games_history.csv", index=False)
    _progress(f"  Saved: {NFL_DIR / 'nfl_games_history.csv'}  ({len(out):,} games)")
    return out


def build_current_stats(state: dict) -> pd.DataFrame:
    standings = get_espn_standings(CURRENT_SEASON)
    team_ids: dict[str, int] = {}
    try:
        data = _get_json(f"{ESPN_BASE}/teams")
        team_ids = {t["team"]["displayName"]: int(t["team"]["id"])
                    for t in data["sports"][0]["leagues"][0]["teams"]}
    except Exception as e:
        _progress(f"    WARNING: ESPN team list fetch failed: {e}")

    rows = []
    for abbr, s in state.items():
        name = TEAM_NAMES[abbr]
        cur = standings.get(name, {"wins": 0, "losses": 0, "ties": 0, "games_played": 0,
                                   "win_pct": 0.5, "point_diff_per_game": 0.0,
                                   "conference": "", "division": ""})
        rows.append({"team_id": team_ids.get(name), "team_name": name, "abbr": abbr, **cur, **s})

    df = pd.DataFrame(rows)
    df.to_csv(NFL_DIR / "nfl_stats_current.csv", index=False)
    _progress(f"  Saved: {NFL_DIR / 'nfl_stats_current.csv'}  ({len(df)} teams)")

    _progress("  Top-5 by Elo:")
    for _, r in df.sort_values("elo", ascending=False).head(5).iterrows():
        _progress(f"    {r['team_name']:26s} Elo={r['elo']:.0f}  offEPA={r['off_epa']:+.3f}  "
                  f"defEPA={r['def_epa']:+.3f}  QB={r['qb_name']} ({r['qb_epa']:+.3f})")
    return df


# ── Entry point ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    _progress("=" * 60)
    _progress("  NFL Data Pipeline (nflverse)")
    _progress(f"  Training seasons : {TRAIN_SEASONS[0]}-{TRAIN_SEASONS[-1]}")
    _progress(f"  Inference season : {CURRENT_SEASON}")
    _progress("=" * 60)
    t0 = time.time()

    _progress("\nLoading schedule / results...")
    games = load_games()
    _progress(f"  {len(games):,} games ({games['season'].min()}-{games['season'].max()})")
    save_games_history(games)

    _progress("\nLoading play-by-play...")
    pbp = load_pbp(list(range(PBP_START, CURRENT_SEASON + 1)))
    _progress(f"  {len(pbp):,} plays")
    team_game, qb_game = summarise_pbp(pbp)
    del pbp

    _progress("\nBuilding features...")
    rows, state, qbs, snaps = build_features(games, team_game, qb_game, first_row_season=TRAIN_SEASONS[0])

    _progress("\nNon-QB injuries (injury reports × snap shares)...")
    inj_seasons = list(range(TRAIN_SEASONS[0] - 1, CURRENT_SEASON + 1))
    roles = PlayerRoles(_load_yearly(SNAPS_URL, "snap_counts", inj_seasons))
    rows = add_injury_feature(rows, injury_loss(_load_yearly(INJ_URL, "injuries", inj_seasons), roles))
    _progress(f"  inj_total_diff: mean |gap| {rows['inj_total_diff'].abs().mean():.2f} starters")
    save_current_roles(roles, CURRENT_SEASON)
    snaps.to_csv(NFL_DIR / "nfl_power_history.csv", index=False)
    _progress(f"  Saved: {NFL_DIR / 'nfl_power_history.csv'}  (weeks {sorted(snaps['week'].unique().tolist()) if not snaps.empty else []})")

    train_df = rows[rows["season"].isin(TRAIN_SEASONS) & rows["win"].notna()].copy()
    train_df["win"] = train_df["win"].astype(int)
    train_path = PROCESSED / "nfl_training_data.csv"
    train_df.to_csv(train_path, index=False)

    cur_df = rows[(rows["season"] == CURRENT_SEASON) & rows["espn_id"].notna()]
    cur_df.to_csv(NFL_DIR / "nfl_game_features_current.csv", index=False)
    _progress(f"  Saved: {NFL_DIR / 'nfl_game_features_current.csv'}  ({len(cur_df) // 2} games)")

    qb_df = pd.DataFrame([
        {"qb_id": q, "qb_name": qbs.name.get(q, ""), "qb_epa": round(qbs.rating(q), 4),
         "dropbacks_weighted": round(qbs.n[q], 1), "starts": qbs.starts[q]}
        for q in set(qbs.n) | set(qbs.starts)
    ]).sort_values("qb_epa", ascending=False)
    qb_df.to_csv(NFL_DIR / "nfl_qb_ratings.csv", index=False)
    _progress(f"  Saved: {NFL_DIR / 'nfl_qb_ratings.csv'}  ({len(qb_df)} QBs)")

    _progress(f"\nBuilding current-season team table ({CURRENT_SEASON})...")
    build_current_stats(state)

    _progress(f"\n{'=' * 60}")
    _progress(f"  Done in {round(time.time() - t0)}s")
    _progress(f"  Training rows : {len(train_df):,}")
    _progress(f"  Win rate      : {train_df['win'].mean():.3f}  (should be ~0.500)")
    _progress(f"  Saved         : {train_path}")
    _progress(f"{'=' * 60}")
