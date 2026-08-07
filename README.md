# Rugby Next Match

Tiny GitHub Pages site showing the next known Saracens or England Rugby match, line-ups, recent form and an AI-written pre-game briefing.

## How it works

- `scripts/update_fixtures.py` gathers fixtures, line-ups, TV details, previews and recent scored results from TheSportsDB and Saracens' official site.
- `scripts/generate_ai_briefing.py` sends only the next fixture's available facts to a local Ollama model and stores a 70–110 word briefing in `fixtures.json`.
- The briefing's deliberately underqualified voice has **strong opinions and no playing experience**. Missing line-ups or form must be acknowledged rather than invented.
- The daily GitHub Action refreshes source data and preserves the latest briefing for the same fixture. A local Hermes automation regenerates the AI copy after the source refresh.

## Run locally

```bash
python3 -m unittest discover -s tests -v
python3 scripts/update_fixtures.py
python3 scripts/generate_ai_briefing.py
python3 -m http.server 8912
```

The generator defaults to `qwen3.6:27b` on Ollama at `http://localhost:11434`. Override with `RUGBY_AI_MODEL` or `OLLAMA_HOST`.
