#!/usr/bin/env python3
"""Fetch the next Saracens or England Rugby fixture and update fixtures.json.

Designed to run daily in GitHub Actions using only Python stdlib.
Also tries to enrich near-term matches with team lineups, TV info and a match preview.
"""
from __future__ import annotations

import html
import json
import re
import urllib.parse
import urllib.request
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rugby_scope import is_womens_fixture, mens_matches

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "fixtures.json"
NOW = datetime.now(timezone.utc)
PREM_STANDINGS_URL = "https://www.premrugby.com/standings"
PREM_FEED_BASE_URL = "https://rugby-union-feeds.incrowdsports.com"
SARACENS_FIXTURES_URL = "https://saracens.com/fixtures-results/"

SOURCES = [
    "https://www.thesportsdb.com/api/v1/json/3/eventsnext.php?id=137123",
    "https://www.thesportsdb.com/api/v1/json/3/eventsnext.php?id=135208",
    SARACENS_FIXTURES_URL,
    PREM_STANDINGS_URL,
    "TheSportsDB event TV/lineup endpoints",
    "DuckDuckGo Lite search for ESPN/RugbyPass/official previews",
]


def fetch_text(url: str) -> str:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Herby rugby fixture bot; https://github.com/Herby9000/rugby-next-match)",
            "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", "replace")


def parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    value = value.strip()
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    if dt.tzinfo is None:
        # TheSportsDB timestamps for this endpoint are UTC-like; keep stable.
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def clean_text(value: str) -> str:
    value = re.sub(r"<[^>]+>", " ", value)
    value = html.unescape(value)
    return re.sub(r"\s+", " ", value).strip()


def _is_saracens_senior_men(name: str) -> bool:
    return clean_text(name).casefold() in {"saracens", "saracens men"}


def _official_saracens_payload() -> dict[str, Any]:
    page = fetch_text(SARACENS_FIXTURES_URL)
    match = re.search(
        r'<script type="application/json" id="fixture_data">\s*(\{.*?\})\s*</script>',
        page,
        re.S,
    )
    if not match:
        raise ValueError("Saracens official fixture JSON not found")
    payload = json.loads(html.unescape(match.group(1)))
    if not isinstance(payload.get("fixtures"), list):
        raise ValueError("Saracens official fixture JSON contains no fixtures")
    return payload


def normalize_saracens_season(
    payload: dict[str, Any],
    retrieved_at_utc: str,
    *,
    now: datetime = NOW,
) -> dict[str, Any]:
    """Normalize senior men's results and fixtures from Saracens' official feed."""
    source_fixtures = payload.get("fixtures")
    if not isinstance(source_fixtures, list):
        raise ValueError("Saracens season response contains no fixture list")

    results: list[dict[str, str]] = []
    upcoming: list[dict[str, str]] = []
    for item in source_fixtures:
        if not isinstance(item, dict):
            raise ValueError("Saracens season response contains an invalid fixture")
        teams = item.get("teams") or {}
        home = clean_text(((teams.get("team_home") or {}).get("alt")) or "")
        away = clean_text(((teams.get("team_away") or {}).get("alt")) or "")
        if not (_is_saracens_senior_men(home) or _is_saracens_senior_men(away)):
            continue
        if not item.get("date_time") or "venue" not in item:
            raise ValueError("Official Saracens fixture is missing its date or venue")
        try:
            start = datetime.fromtimestamp(int(item["date_time"]), tz=timezone.utc)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("Official Saracens fixture has an invalid date") from exc
        competition = clean_text(item.get("event_name") or "")
        venue = clean_text(item.get("venue") or "")
        if not home or not away or not competition:
            raise ValueError("Official Saracens fixture is missing team or competition data")

        is_home = _is_saracens_senior_men(home)
        opponent = away if is_home else home
        base = {
            "date": start.date().isoformat(),
            "opponent": opponent,
            "home_away": "Home" if is_home else "Away",
            "competition": competition,
            "venue": venue,
        }
        score_text = clean_text(teams.get("score") or "")
        score_match = re.fullmatch(r"(\d+)\s*-\s*(\d+)", score_text)
        if score_match:
            home_score, away_score = map(int, score_match.groups())
            team_score, opponent_score = (
                (home_score, away_score) if is_home else (away_score, home_score)
            )
            results.append({
                **base,
                "result": (
                    "W" if team_score > opponent_score
                    else "L" if team_score < opponent_score
                    else "D"
                ),
                "score": f"{home} {home_score}–{away_score} {away}",
            })
        elif start > now:
            date_content = item.get("date_time_content") or {}
            source_time = clean_text(date_content.get("formatted_time") or "")
            upcoming.append({
                **base,
                "start_utc": start.isoformat().replace("+00:00", "Z"),
                "kickoff_status": (
                    "Time TBC" if "tbc" in source_time.casefold()
                    else "Confirmed"
                ),
            })

    results.sort(key=lambda fixture: fixture["date"], reverse=True)
    upcoming.sort(key=lambda fixture: fixture["start_utc"])
    season = {
        "status": "current",
        "stale": False,
        "retrieved_at_utc": retrieved_at_utc,
        "source": "Saracens official fixtures",
        "source_url": SARACENS_FIXTURES_URL,
        "recent_results": results[:5],
        "upcoming_fixtures": upcoming[:5],
    }
    if not valid_saracens_season(season):
        raise ValueError("Normalized Saracens season failed schema validation")
    return season


def valid_saracens_season(season: Any) -> bool:
    """Return whether a season snapshot is safe to preserve and publish."""
    if not isinstance(season, dict) or season.get("status") not in {"current", "stale"}:
        return False
    if not isinstance(season.get("retrieved_at_utc"), str) or not season.get("source_url"):
        return False
    results = season.get("recent_results")
    upcoming = season.get("upcoming_fixtures")
    if not isinstance(results, list) or not isinstance(upcoming, list):
        return False
    if len(results) > 5 or len(upcoming) > 5:
        return False
    common = {"date", "opponent", "home_away", "competition", "venue"}
    for item in results:
        if not isinstance(item, dict) or not common | {"score", "result"} <= item.keys():
            return False
        if item.get("result") not in {"W", "D", "L"}:
            return False
        if item.get("home_away") not in {"Home", "Away"}:
            return False
        if any(not isinstance(item.get(key), str) for key in common | {"score"}):
            return False
    for item in upcoming:
        if not isinstance(item, dict) or not common | {"start_utc", "kickoff_status"} <= item.keys():
            return False
        if item.get("home_away") not in {"Home", "Away"}:
            return False
        if any(
            not isinstance(item.get(key), str)
            for key in common | {"start_utc", "kickoff_status"}
        ):
            return False
    return True


def fetch_saracens_season(retrieved_at_utc: str) -> dict[str, Any]:
    return normalize_saracens_season(_official_saracens_payload(), retrieved_at_utc)


def refresh_saracens_season(
    existing: dict[str, Any], attempted_at_utc: str
) -> tuple[dict[str, Any], str | None]:
    """Fetch the season view, preserving the last valid snapshot on failure."""
    try:
        return fetch_saracens_season(attempted_at_utc), None
    except Exception as exc:
        saved = existing.get("saracens_season")
        if valid_saracens_season(saved):
            assert isinstance(saved, dict)
            season = deepcopy(saved)
            season.update({
                "status": "stale",
                "stale": True,
                "last_attempt_at_utc": attempted_at_utc,
            })
            return season, f"Saracens season refresh failed; preserved last valid snapshot: {exc}"
        return {
            "status": "unavailable",
            "stale": True,
            "last_attempt_at_utc": attempted_at_utc,
            "source": "Saracens official fixtures",
            "source_url": SARACENS_FIXTURES_URL,
            "recent_results": [],
            "upcoming_fixtures": [],
        }, f"Saracens season unavailable: {exc}"


PREM_TEAM_FIELDS = {
    "position": "position",
    "name": "team",
    "played": "played",
    "won": "won",
    "drawn": "drawn",
    "lost": "lost",
    "pointsFor": "points_for",
    "pointsAgainst": "points_against",
    "pointsDiff": "points_difference",
    "triesBonus": "try_bonus_points",
    "losingBonus": "losing_bonus_points",
    "bonus": "bonus_points",
    "points": "points",
}


def normalize_prem_table(
    payload: dict[str, Any], forms: dict[int, list[str]], retrieved_at_utc: str
) -> dict[str, Any]:
    """Normalize and strictly validate the official PREM standings response."""
    data = payload.get("data") or {}
    groups = data.get("groups") or []
    source_teams = groups[0].get("teams") if groups else None
    if not isinstance(source_teams, list) or not source_teams:
        raise ValueError("Official PREM response contains no standings teams")

    teams: list[dict[str, Any]] = []
    for source_team in source_teams:
        missing = [field for field in PREM_TEAM_FIELDS if field not in source_team]
        if missing:
            raise ValueError(f"Official PREM row is missing: {', '.join(missing)}")
        row = {
            normalized: source_team[source]
            for source, normalized in PREM_TEAM_FIELDS.items()
        }
        if not row["team"] or any(
            not isinstance(value, int) or isinstance(value, bool)
            for key, value in row.items()
            if key != "team"
        ):
            raise ValueError("Official PREM row contains an invalid name or statistic")
        team_id = source_team.get("teamId")
        row["form"] = [
            result for result in forms.get(team_id, []) if result in {"W", "L", "D"}
        ][:3]
        teams.append(row)

    teams.sort(key=lambda row: row["position"])
    season_id = data.get("seasonId")
    if not isinstance(season_id, int):
        raise ValueError("Official PREM response has no valid season")
    season_start = season_id // 100
    table = {
        "competition": ((data.get("competition") or {}).get("name") or "PREM Rugby"),
        "competition_id": data.get("competitionId"),
        "season": f"{season_start}/{(season_start + 1) % 100:02d}",
        "season_id": season_id,
        "status": "current",
        "stale": False,
        "retrieved_at_utc": retrieved_at_utc,
        "source": "PREM Rugby official standings",
        "source_url": PREM_STANDINGS_URL,
        "teams": teams,
    }
    if not valid_prem_table(table):
        raise ValueError("Normalized PREM table failed schema validation")
    return table


def valid_prem_table(table: Any) -> bool:
    """Return whether a table is safe to preserve and publish as standings."""
    if not isinstance(table, dict) or table.get("status") not in {"current", "stale"}:
        return False
    if not isinstance(table.get("retrieved_at_utc"), str) or not table.get("source_url"):
        return False
    teams = table.get("teams")
    if not isinstance(teams, list) or not teams:
        return False
    required = set(PREM_TEAM_FIELDS.values()) | {"form"}
    for row in teams:
        if not isinstance(row, dict) or not required <= row.keys():
            return False
        if not isinstance(row["team"], str) or not row["team"]:
            return False
        if any(
            not isinstance(row[key], int) or isinstance(row[key], bool)
            for key in required - {"team", "form"}
        ):
            return False
        if not isinstance(row["form"], list) or any(
            result not in {"W", "L", "D"} for result in row["form"]
        ):
            return False
    return True


def _prem_public_config(page: str) -> dict[str, str]:
    """Read the official site's public feed configuration without persisting keys."""
    config: dict[str, str] = {}
    for key in ("apiKey", "appId", "realmId", "dataProvider", "compId"):
        match = re.search(rf"(?<![A-Za-z]){key}:\"([^\"]+)\"", page)
        if not match:
            raise ValueError(f"PREM site public configuration is missing {key}")
        config[key] = match.group(1)
    season = re.search(r"(?<![A-Za-z])season:(\d+)", page)
    if not season:
        raise ValueError("PREM site public configuration is missing season")
    config["season"] = season.group(1)
    return config


def _prem_feed_json(
    path: str, params: dict[str, Any], config: dict[str, str]
) -> dict[str, Any]:
    url = f"{PREM_FEED_BASE_URL}{path}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Herby rugby fixture bot; https://github.com/Herby9000/rugby-next-match)",
            "Accept": "application/json",
            "X-API-KEY": config["apiKey"],
            "X-APP-ID": config["appId"],
            "X-REALM": config["realmId"],
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_prem_table(retrieved_at_utc: str) -> dict[str, Any]:
    """Fetch current standings and recent form from PREM Rugby's official feed."""
    config = _prem_public_config(fetch_text(PREM_STANDINGS_URL))
    params = {"provider": config["dataProvider"], "season": config["season"]}
    payload = _prem_feed_json(f"/v1/tables/{config['compId']}", params, config)
    data = payload.get("data") or {}
    groups = data.get("groups") or []
    teams = groups[0].get("teams") if groups else []
    forms: dict[int, list[str]] = {}
    for team in teams or []:
        team_id = team.get("teamId")
        if not isinstance(team_id, int):
            continue
        try:
            form_payload = _prem_feed_json(
                f"/v1/form/{team_id}",
                {**params, "compId": config["compId"], "max": 3},
                config,
            )
            forms[team_id] = [item.get("result") for item in form_payload.get("data") or []]
        except Exception:
            # Form is an enhancement; a valid official table remains publishable without it.
            forms[team_id] = []
    return normalize_prem_table(payload, forms, retrieved_at_utc)


def refresh_prem_table(
    existing: dict[str, Any], attempted_at_utc: str
) -> tuple[dict[str, Any], str | None]:
    """Fetch standings, preserving the last valid table on any source failure."""
    try:
        return fetch_prem_table(attempted_at_utc), None
    except Exception as exc:
        saved = existing.get("prem_table")
        if valid_prem_table(saved):
            assert isinstance(saved, dict)
            table = deepcopy(saved)
            table.update({
                "status": "stale",
                "stale": True,
                "last_attempt_at_utc": attempted_at_utc,
            })
            return table, f"PREM standings refresh failed; preserved last valid table: {exc}"
        return {
            "competition": "PREM Rugby",
            "status": "unavailable",
            "stale": True,
            "last_attempt_at_utc": attempted_at_utc,
            "source": "PREM Rugby official standings",
            "source_url": PREM_STANDINGS_URL,
            "teams": [],
        }, f"PREM standings unavailable: {exc}"


def official_recent_results(
    fixtures: list[dict[str, Any]], team_name: str, limit: int = 3
) -> list[dict[str, str]]:
    """Return scored official results from the named team's perspective."""
    results: list[dict[str, str]] = []
    for item in fixtures:
        teams = item.get("teams") or {}
        home = ((teams.get("team_home") or {}).get("alt") or "").strip()
        away = ((teams.get("team_away") or {}).get("alt") or "").strip()
        wanted = team_name.strip()
        if wanted not in {home, away}:
            continue
        score_text = clean_text(teams.get("score") or "")
        score_match = re.fullmatch(r"(\d+)\s*-\s*(\d+)", score_text)
        if not score_match:
            continue
        home_score, away_score = map(int, score_match.groups())
        team_score, opponent_score = (
            (home_score, away_score) if wanted == home else (away_score, home_score)
        )
        result = "W" if team_score > opponent_score else "L" if team_score < opponent_score else "D"
        timestamp = int(item.get("date_time") or 0)
        results.append(
            {
                "date": datetime.fromtimestamp(timestamp, tz=timezone.utc).date().isoformat(),
                "competition": item.get("event_name") or "Rugby",
                "result": result,
                "score": f"{home} {home_score}–{away_score} {away}",
            }
        )
    results.sort(key=lambda result: result["date"], reverse=True)
    return results[:limit]


def preserve_ai_briefings(
    matches: list[dict[str, Any]], existing: dict[str, Any]
) -> None:
    """Keep an AI briefing until the local generator refreshes that fixture."""
    saved = {
        (match.get("title"), match.get("start_utc")): match.get("ai_briefing")
        for match in existing.get("matches") or []
        if match.get("ai_briefing")
    }
    for match in matches:
        briefing = saved.get((match.get("title"), match.get("start_utc")))
        if briefing:
            match["ai_briefing"] = briefing


def sportsdb_matches(team_id: str, team_name: str) -> tuple[list[dict[str, Any]], str | None]:
    url = f"https://www.thesportsdb.com/api/v1/json/3/eventsnext.php?id={team_id}"
    try:
        payload = json.loads(fetch_text(url))
    except Exception as exc:  # network/JSON failure should not kill all sources
        return [], f"{team_name}: TheSportsDB fetch failed: {exc}"

    matches: list[dict[str, Any]] = []
    for event in payload.get("events") or []:
        if is_womens_fixture(
            {
                "title": event.get("strEvent"),
                "team": event.get("strHomeTeam"),
                "opponent": event.get("strAwayTeam"),
                "competition": event.get("strLeague"),
                "gender": event.get("strGender"),
            }
        ):
            continue
        start = parse_timestamp(event.get("strTimestamp"))
        if not start or start <= NOW:
            continue
        home = event.get("strHomeTeam") or "TBC"
        away = event.get("strAwayTeam") or "TBC"
        venue_bits = [event.get("strVenue"), event.get("strCity"), event.get("strCountry")]
        venue = ", ".join(x for x in venue_bits if x) or "Venue TBC"
        if team_name.lower().startswith("england"):
            home_away = "Home" if home == "England Rugby" else "Away" if away == "England Rugby" else "Neutral"
        else:
            home_away = "Home" if "Saracens" in home else "Away" if "Saracens" in away else "Neutral"
        matches.append(
            {
                "event_id": event.get("idEvent"),
                "team": team_name,
                "opponent": away if home_away == "Home" else home if home_away == "Away" else f"{home} / {away}",
                "title": event.get("strEvent") or f"{home} vs {away}",
                "competition": event.get("strLeague") or "Rugby",
                "venue": venue,
                "start_utc": start.isoformat().replace("+00:00", "Z"),
                "home_away": home_away,
                "source": "TheSportsDB",
                "source_url": url,
            }
        )
    return matches, None if matches else f"{team_name}: no future TheSportsDB fixture returned."


def saracens_official_matches() -> tuple[list[dict[str, Any]], str | None]:
    url = SARACENS_FIXTURES_URL
    try:
        payload = _official_saracens_payload()
    except Exception as exc:
        return [], f"Saracens: official fixture page fetch failed: {exc}"

    matches: list[dict[str, Any]] = []
    for item in payload.get("fixtures") or []:
        ts = item.get("date_time")
        if not ts:
            continue
        start = datetime.fromtimestamp(int(ts), tz=timezone.utc)
        if start <= NOW:
            continue
        teams = item.get("teams") or {}
        home = ((teams.get("team_home") or {}).get("alt")) or "TBC"
        away = ((teams.get("team_away") or {}).get("alt")) or "TBC"
        if is_womens_fixture(
            {
                "title": f"{home} vs {away}",
                "team": home,
                "opponent": away,
                "competition": item.get("event_name"),
                "gender": item.get("gender"),
                "division": item.get("division"),
                "category": item.get("category"),
            }
        ):
            continue
        if "Saracens" in home:
            team = home
            opponent = away
            home_away = "Home"
        elif "Saracens" in away:
            team = away
            opponent = home
            home_away = "Away"
        else:
            team = "Saracens"
            opponent = f"{home} / {away}"
            home_away = "Neutral"
        matches.append(
            {
                "team": team,
                "opponent": opponent,
                "title": f"{home} vs {away}",
                "competition": item.get("event_name") or "Rugby",
                "venue": item.get("venue") or "Venue TBC",
                "start_utc": start.isoformat().replace("+00:00", "Z"),
                "home_away": home_away,
                "source": "Saracens official fixtures",
                "source_url": url,
                "recent_results": official_recent_results(
                    payload.get("fixtures") or [], team, limit=3
                ),
            }
        )
    return matches, None if matches else "Saracens: official fixtures page returned no future fixture."


def sportsdb_tv(event_id: str | None) -> list[dict[str, str]]:
    if not event_id:
        return []
    try:
        payload = json.loads(fetch_text(f"https://www.thesportsdb.com/api/v1/json/3/lookuptv.php?id={event_id}"))
    except Exception:
        return []
    channels = []
    for item in payload.get("tvevent") or []:
        channels.append({
            "country": item.get("strCountry") or "",
            "channel": item.get("strChannel") or "",
        })
    return [c for c in channels if c["channel"]]


def sportsdb_lineup(event_id: str | None) -> dict[str, Any] | None:
    if not event_id:
        return None
    try:
        payload = json.loads(fetch_text(f"https://www.thesportsdb.com/api/v1/json/3/lookuplineup.php?id={event_id}"))
    except Exception:
        return None
    rows = payload.get("lineup") or []
    if not rows:
        return None
    # The public endpoint rarely has rugby lineups, but keep support if it appears.
    grouped: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        team = row.get("strTeam") or "Team"
        grouped.setdefault(team, []).append({
            "number": row.get("intSquadNumber") or "",
            "name": row.get("strPlayer") or row.get("strPlayerName") or "",
            "position": row.get("strPosition") or "",
        })
    return {"available": True, "source": "TheSportsDB", "teams": grouped}


def espn_event_id(match: dict[str, Any]) -> str | None:
    """Find ESPN's event id for international rugby fixtures by date/name."""
    start = parse_timestamp(match.get("start_utc"))
    if not start or "Nations Championship" not in (match.get("competition") or ""):
        return None
    url = f"https://site.api.espn.com/apis/site/v2/sports/rugby/17567/scoreboard?dates={start:%Y%m%d}"
    try:
        payload = json.loads(fetch_text(url))
    except Exception:
        return None
    wanted_words = set(re.findall(r"[a-z]+", (match.get("title") or "").lower()))
    for event in payload.get("events") or []:
        competitors = []
        for comp in event.get("competitions") or []:
            for competitor in comp.get("competitors") or []:
                competitors.append((competitor.get("team") or {}).get("displayName", ""))
        candidates = " ".join([event.get("name") or "", event.get("shortName") or "", *competitors]).lower()
        candidate_words = set(re.findall(r"[a-z]+", candidates))
        # Handles TheSportsDB's "South Africa Rugby" vs ESPN's "South Africa".
        if len(wanted_words & candidate_words) >= 3:
            return str(event.get("id"))
    return None


def espn_lineup(match: dict[str, Any]) -> dict[str, Any] | None:
    eid = espn_event_id(match)
    if not eid:
        return None
    url = f"https://site.api.espn.com/apis/site/v2/sports/rugby/17567/summary?event={eid}"
    try:
        payload = json.loads(fetch_text(url))
    except Exception:
        return None
    rosters = payload.get("rosters") or []
    if not rosters:
        return None
    teams: dict[str, dict[str, list[dict[str, str]]]] = {}
    for roster in rosters:
        team_name = (roster.get("team") or {}).get("displayName") or roster.get("homeAway") or "Team"
        starters: list[dict[str, str]] = []
        replacements: list[dict[str, str]] = []
        for row in roster.get("roster") or []:
            jersey = str(row.get("jersey") or "")
            athlete = row.get("athlete") or {}
            position = row.get("position") or athlete.get("position") or {}
            player = {
                "number": jersey,
                "name": athlete.get("displayName") or athlete.get("fullName") or "",
                "position": position.get("abbreviation") or position.get("displayName") or "",
            }
            if not player["name"]:
                continue
            try:
                number = int(jersey)
            except ValueError:
                number = 99
            (starters if number <= 15 else replacements).append(player)
        if starters or replacements:
            display_order = [15, 14, 13, 12, 11, 10, 9, 1, 2, 3, 4, 5, 6, 7, 8]
            order = {n: i for i, n in enumerate(display_order)}
            starters.sort(key=lambda p: order.get(int(p["number"]), 99) if str(p["number"]).isdigit() else 99)
            replacements.sort(key=lambda p: int(p["number"]) if str(p["number"]).isdigit() else 99)
            teams[team_name] = {"starters": starters, "replacements": replacements}
    if not teams:
        return None
    match["espn_event_id"] = eid
    return {
        "available": True,
        "source": "ESPN public API",
        "source_url": f"https://www.espn.co.uk/rugby/lineups/_/gameId/{eid}/league/17567",
        "teams": teams,
    }


def ddg_search(query: str, limit: int = 6) -> list[dict[str, str]]:
    url = "https://lite.duckduckgo.com/lite/?q=" + urllib.parse.quote(query)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            page = resp.read().decode("utf-8", "replace")
    except Exception:
        return []
    results = []
    # DuckDuckGo Lite has used both rel=nofollow and result-link anchors.
    patterns = [
        r'<a rel="nofollow" href="([^"]+)"[^>]*>(.*?)</a>',
        r'<a class="result-link" href="([^"]+)"[^>]*>(.*?)</a>',
        r'<a[^>]+href="(//duckduckgo\.com/l/\?uddg=[^"]+)"[^>]*>(.*?)</a>',
    ]
    for pat in patterns:
        for match in re.finditer(pat, page, re.S):
            title = clean_text(match.group(2))
            href = html.unescape(match.group(1))
            if href.startswith("//"):
                href = "https:" + href
            parsed = urllib.parse.urlparse(href)
            qs = urllib.parse.parse_qs(parsed.query)
            target = qs.get("uddg", [href])[0]
            if title and target and not any(r["url"] == target for r in results):
                results.append({"title": title, "url": target})
            if len(results) >= limit:
                return results
        if results:
            return results
    return results


def parse_espn_lineups(url: str) -> dict[str, Any] | None:
    try:
        page = fetch_text(url)
    except Exception:
        return None
    marker = 'id="gamepackage-game-lineups-expanded"'
    if marker not in page:
        return None
    section = page[page.find(marker): page.find('id="mpu2"', page.find(marker))]
    tables = re.findall(r"<table[^>]*class=\"table-accordion\"[^>]*>(.*?)</table>", section, re.S)
    if not tables:
        return None
    teams: dict[str, dict[str, list[dict[str, str]]]] = {}
    for table in tables:
        caption = re.search(r"<caption[^>]*>.*?(?:<!-- react-text: \d+ -->)?\s*([^<]+)\s*(?:<!-- /react-text -->)?", table, re.S)
        team = clean_text(caption.group(1)) if caption else f"Team {len(teams)+1}"
        # Split starters/replacements by the replacement heading.
        parts = re.split(r"<tr class=\"secondTableHeader\"[^>]*>.*?Replacements.*?</tr>", table, flags=re.S)
        starters_html = parts[0]
        replacements_html = parts[1] if len(parts) > 1 else ""

        def rows(block: str) -> list[dict[str, str]]:
            out = []
            for row in re.finditer(r"<tr[^>]*>\s*<td[^>]*class=\"number\"[^>]*>(.*?)</td>\s*<td[^>]*class=\"date\"[^>]*>(.*?)</td>", block, re.S):
                number = clean_text(row.group(1))
                text = clean_text(row.group(2)).rstrip(",")
                if "," in text:
                    name, position = [x.strip() for x in text.rsplit(",", 1)]
                else:
                    name, position = text, ""
                out.append({"number": number, "name": name, "position": position})
            return out

        teams[team] = {"starters": rows(starters_html), "replacements": rows(replacements_html)}
    if not any(v["starters"] or v["replacements"] for v in teams.values()):
        return None
    return {"available": True, "source": "ESPN", "source_url": url, "teams": teams}


def find_lineup(match: dict[str, Any]) -> dict[str, Any]:
    lineup = sportsdb_lineup(match.get("event_id"))
    if lineup:
        return lineup
    lineup = espn_lineup(match)
    if lineup:
        return lineup
    query = f"{match['title']} {match['start_utc'][:10]} rugby lineups ESPN"
    for result in ddg_search(query):
        if "espn" in result["url"] and "/rugby/lineups/" in result["url"]:
            parsed = parse_espn_lineups(result["url"])
            if parsed:
                return parsed
    return {
        "available": False,
        "message": "Lineups not available yet. They usually appear around 24 hours before kick-off.",
        "search_url": "https://duckduckgo.com/?q=" + urllib.parse.quote(query),
    }


def meta_preview(url: str) -> tuple[str | None, str | None]:
    try:
        page = fetch_text(url)
    except Exception:
        return None, None
    title = None
    desc = None
    m = re.search(r"<title[^>]*>(.*?)</title>", page, re.S | re.I)
    if m:
        title = clean_text(m.group(1))
    # Prefer og:description / description
    for pat in [
        r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\']([^"\']+)',
        r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']+)',
    ]:
        m = re.search(pat, page, re.I)
        if m:
            desc = clean_text(m.group(1))
            break
    return title, desc


def build_preview(match: dict[str, Any], lineup: dict[str, Any]) -> dict[str, Any]:
    query = f"{match['title']} rugby match preview {match['start_utc'][:10]}"
    links = ddg_search(query, limit=5)
    picked = None
    for result in links:
        if any(domain in result["url"] for domain in ["englandrugby.com", "saracens.com", "espn", "rugbypass", "planetrugby"]):
            title, desc = meta_preview(result["url"])
            picked = {
                "title": title or result["title"],
                "summary": desc or result["title"],
                "url": result["url"],
            }
            break
    if not picked:
        picked = {
            "title": f"{match['title']} preview",
            "summary": f"{match['team']} face {match['opponent']} in {match['competition']} at {match['venue']}.",
            "url": "https://duckduckgo.com/?q=" + urllib.parse.quote(query),
        }
    if lineup.get("available"):
        picked["lineup_note"] = "Team sheets are available below."
    else:
        picked["lineup_note"] = "Team sheets are not available yet; the daily updater will keep checking."
    return picked


def enrich_match(match: dict[str, Any]) -> dict[str, Any]:
    tv = sportsdb_tv(match.get("event_id"))
    if tv:
        match["tv"] = tv
    lineup = find_lineup(match)
    match["lineup"] = lineup
    match["preview"] = build_preview(match, lineup)
    return match


def main() -> int:
    all_matches: list[dict[str, Any]] = []
    notes: list[str] = []
    try:
        existing = json.loads(OUT.read_text()) if OUT.exists() else {}
    except (OSError, json.JSONDecodeError):
        existing = {}

    generated_at = NOW.isoformat().replace("+00:00", "Z")
    prem_table, table_note = refresh_prem_table(existing, generated_at)
    if table_note:
        notes.append(table_note)
    saracens_season, season_note = refresh_saracens_season(existing, generated_at)
    if season_note:
        notes.append(season_note)

    for matches, note in [
        sportsdb_matches("137123", "England Rugby"),
        sportsdb_matches("135208", "Saracens"),
        saracens_official_matches(),
    ]:
        all_matches.extend(matches)
        if note:
            notes.append(note)

    # Apply the scope rule again at the aggregation boundary so a newly added
    # source cannot publish a women's fixture without explicitly passing it.
    all_matches = mens_matches(all_matches)

    # Deduplicate by title/start/source-ish, then sort future matches.
    seen: set[tuple[str, str]] = set()
    deduped: list[dict[str, Any]] = []
    for m in all_matches:
        key = (m["title"], m["start_utc"])
        if key not in seen:
            seen.add(key)
            deduped.append(m)
    deduped.sort(key=lambda m: m["start_utc"])

    # Enrich the next few events. Lineups/previews are most useful close to kick-off,
    # but running daily means the data will appear automatically once sources publish it.
    enriched = [enrich_match(m) for m in deduped[:5]]
    preserve_ai_briefings(enriched, existing)

    output = {
        "generated_at_utc": generated_at,
        "sources": SOURCES,
        "matches": enriched,
        "saracens_season": saracens_season,
        "prem_table": prem_table,
        "notes": notes,
    }
    OUT.write_text(json.dumps(output, indent=2, ensure_ascii=False) + "\n")
    print(f"Wrote {OUT} with {len(enriched)} future match(es).")
    for m in enriched[:3]:
        lineup_status = "lineups" if (m.get("lineup") or {}).get("available") else "no lineups"
        print(f"- {m['start_utc']} {m['title']} ({m['source']}, {lineup_status})")
    if notes:
        print("Notes:")
        for note in notes:
            print(f"- {note}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
