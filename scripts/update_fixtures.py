#!/usr/bin/env python3
"""Fetch the next Saracens or England Rugby fixture and update fixtures.json.

Designed to run daily in GitHub Actions using only Python stdlib.
"""
from __future__ import annotations

import html
import json
import re
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "fixtures.json"
NOW = datetime.now(timezone.utc)

SOURCES = [
    "https://www.thesportsdb.com/api/v1/json/3/eventsnext.php?id=137123",
    "https://www.thesportsdb.com/api/v1/json/3/eventsnext.php?id=135208",
    "https://saracens.com/fixtures-results/",
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


def sportsdb_matches(team_id: str, team_name: str) -> tuple[list[dict[str, Any]], str | None]:
    url = f"https://www.thesportsdb.com/api/v1/json/3/eventsnext.php?id={team_id}"
    try:
        payload = json.loads(fetch_text(url))
    except Exception as exc:  # network/JSON failure should not kill all sources
        return [], f"{team_name}: TheSportsDB fetch failed: {exc}"

    matches: list[dict[str, Any]] = []
    for event in payload.get("events") or []:
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
                "team": team_name,
                "opponent": away if home_away == "Home" else home if home_away == "Away" else f"{home} / {away}",
                "title": event.get("strEvent") or f"{home} vs {away}",
                "competition": event.get("strLeague") or "Rugby",
                "venue": venue,
                "start_utc": start.isoformat().replace("+00:00", "Z"),
                "home_away": home_away,
                "source": "TheSportsDB",
            }
        )
    return matches, None if matches else f"{team_name}: no future TheSportsDB fixture returned."


def saracens_official_matches() -> tuple[list[dict[str, Any]], str | None]:
    url = "https://saracens.com/fixtures-results/"
    try:
        page = fetch_text(url)
        match = re.search(r'<script type="application/json" id="fixture_data">\s*(\{.*?\})\s*</script>', page, re.S)
        if not match:
            return [], "Saracens: official fixture JSON not found."
        payload = json.loads(html.unescape(match.group(1)))
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
            }
        )
    return matches, None if matches else "Saracens: official fixtures page returned no future fixture."


def main() -> int:
    all_matches: list[dict[str, Any]] = []
    notes: list[str] = []

    for matches, note in [
        sportsdb_matches("137123", "England Rugby"),
        sportsdb_matches("135208", "Saracens"),
        saracens_official_matches(),
    ]:
        all_matches.extend(matches)
        if note:
            notes.append(note)

    # Deduplicate by title/start/source-ish, then sort future matches.
    seen: set[tuple[str, str]] = set()
    deduped: list[dict[str, Any]] = []
    for m in all_matches:
        key = (m["title"], m["start_utc"])
        if key not in seen:
            seen.add(key)
            deduped.append(m)
    deduped.sort(key=lambda m: m["start_utc"])

    output = {
        "generated_at_utc": NOW.isoformat().replace("+00:00", "Z"),
        "sources": SOURCES,
        "matches": deduped,
        "notes": notes,
    }
    OUT.write_text(json.dumps(output, indent=2, ensure_ascii=False) + "\n")
    print(f"Wrote {OUT} with {len(deduped)} future match(es).")
    for m in deduped[:3]:
        print(f"- {m['start_utc']} {m['title']} ({m['source']})")
    if notes:
        print("Notes:")
        for note in notes:
            print(f"- {note}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
