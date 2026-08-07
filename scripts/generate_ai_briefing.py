#!/usr/bin/env python3
"""Generate an opinionated pre-match briefing with a local Ollama model."""
from __future__ import annotations

import argparse
import json
import os
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FIXTURES = ROOT / "fixtures.json"
DEFAULT_MODEL = "qwen3.6:27b"
DEFAULT_HOST = "http://localhost:11434"


def next_match(data: dict[str, Any]) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    candidates = []
    for match in data.get("matches") or []:
        value = str(match.get("start_utc") or "").replace("Z", "+00:00")
        try:
            start = datetime.fromisoformat(value)
        except ValueError:
            continue
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        if start > now:
            candidates.append((start, match))
    if not candidates:
        raise ValueError("No future match is available for an AI briefing")
    return min(candidates, key=lambda item: item[0])[1]


def lineup_summary(lineup: dict[str, Any] | None) -> str:
    if not lineup or not lineup.get("available"):
        return "Line-ups: not announced yet. Do not invent players."
    lines = []
    for team, groups in (lineup.get("teams") or {}).items():
        starters = groups.get("starters") or []
        names = ", ".join(
            f"{player.get('number', '')} {player.get('name', '')}".strip()
            for player in starters
            if player.get("name")
        )
        lines.append(f"{team} starters: {names or 'not listed'}")
    return "\n".join(lines) or "Line-ups: not announced yet. Do not invent players."


def results_summary(results: list[dict[str, Any]] | None) -> str:
    if not results:
        return "Recent scored results: unavailable. Say form is hard to judge; do not invent results."
    return "Recent results:\n" + "\n".join(
        f"- {result.get('result', '?')}: {result.get('score', '')} ({result.get('competition', 'Rugby')})"
        for result in results[:3]
    )


def build_prompt(data: dict[str, Any]) -> str:
    match = next_match(data)
    return f"""You are an AI rugby pundit with strong opinions and absolutely no playing experience.
Write one sharp pre-game briefing of 70 to 110 words for a match dashboard.
Base it ONLY on the supplied fixture, line-ups and recent results. Never invent a player, score, injury, tactic or fact.
Do not infer age, size, experience, playing style, weather, crowd, injuries or tactics from a team name.
When line-ups and form are missing, say the evidence is thin; the only safe angles are the stated fixture, competition, venue and home/away status.
You may predict a winner and margin as opinion, but Label the winner or margin as your prediction, not a known fact.
Sound confident, witty and specific, not cruel. Include one clear match prediction. No heading, bullets, markdown, odds or disclaimer.

Fixture: {match.get('title')}
Tracked team: {match.get('team')}
Competition: {match.get('competition')}
Venue: {match.get('venue')}
Kick-off UTC: {match.get('start_utc')}
Home/away: {match.get('home_away')}

{lineup_summary(match.get('lineup'))}

{results_summary(match.get('recent_results'))}
"""


def request_briefing(prompt: str, model: str = DEFAULT_MODEL, host: str = DEFAULT_HOST) -> str:
    body = json.dumps(
        {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "think": False,
            "options": {"temperature": 0.8, "num_predict": 220},
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        host.rstrip("/") + "/api/generate",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=180) as response:
        payload = json.loads(response.read().decode("utf-8"))
    text = " ".join(str(payload.get("response") or "").strip().strip('"').split())
    if not text:
        raise RuntimeError("The AI model returned an empty briefing")
    if len(text.split()) > 130:
        raise RuntimeError("The AI model ignored the requested briefing length")
    return text


def update_file(path: Path, model: str = DEFAULT_MODEL, host: str = DEFAULT_HOST) -> str:
    data = json.loads(path.read_text())
    match = next_match(data)
    text = request_briefing(build_prompt(data), model=model, host=host)
    match["ai_briefing"] = {
        "text": text,
        "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "model": model,
        "inputs": {
            "lineups_available": bool((match.get("lineup") or {}).get("available")),
            "recent_results": len(match.get("recent_results") or []),
        },
    }
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    return text


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", type=Path, default=DEFAULT_FIXTURES)
    parser.add_argument("--model", default=os.environ.get("RUGBY_AI_MODEL", DEFAULT_MODEL))
    parser.add_argument("--host", default=os.environ.get("OLLAMA_HOST", DEFAULT_HOST))
    args = parser.parse_args()
    text = update_file(args.path, model=args.model, host=args.host)
    print(f"AI briefing: {text}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
