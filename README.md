# Rugby Next Match

An iPhone-first GitHub Pages dashboard showing the next known men's Saracens or England Rugby match, Saracens' recent results and upcoming fixtures, line-ups, an AI-written pre-game briefing and the current men's PREM league table.

## How it works

- `scripts/update_fixtures.py` gathers men's fixtures, line-ups, TV details, previews and recent scored results from TheSportsDB and Saracens' official site. Explicitly women's, female, ladies and girls fixtures are discarded before enrichment and publication.
- The updater also normalizes a dedicated senior men's Saracens season snapshot: up to five recent scored results and five upcoming fixtures from the official club feed. A failed refresh preserves the last schema-valid snapshot and marks it stale; without one, the UI reports it unavailable.
- The same updater retrieves the current standings and three-match form from the structured feed used by [PREM Rugby's official standings page](https://www.premrugby.com/standings). `fixtures.json` records the official source URL and successful retrieval time. A failed refresh preserves the last schema-valid table and marks it stale; if no valid table has ever been saved, the UI reports it unavailable.
- `scripts/generate_ai_briefing.py` sends only the next fixture's available facts to a local Ollama model and stores a 70–110 word briefing in `fixtures.json`.
- The briefing's deliberately underqualified voice has **strong opinions and no playing experience**. Missing line-ups or form must be acknowledged rather than invented.
- The daily GitHub Action refreshes fixtures and standings together and preserves the latest briefing for the same fixture. A local Hermes automation regenerates the AI copy after the source refresh.

## Run locally

```bash
python3 -m unittest discover -s tests -v
python3 scripts/update_fixtures.py
python3 scripts/generate_ai_briefing.py
python3 -m http.server 8912
```

The generator defaults to `qwen3.6:27b` on Ollama at `http://localhost:11434`. Override with `RUGBY_AI_MODEL` or `OLLAMA_HOST`.
