import json
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class FrontendBriefingTests(unittest.TestCase):
    def test_ai_briefing_is_rendered_before_preview_and_lineups_grid(self):
        page = (ROOT / "index.html").read_text()

        self.assertIn("function renderAiBriefing", page)
        self.assertIn("AI pre-match briefing", page)
        details = page.index('<div class="countdown"')
        briefing = page.index("${renderAiBriefing(next.ai_briefing)}")
        grid = page.index('<div class="grid">', details)
        self.assertLess(details, briefing)
        self.assertLess(briefing, grid)


class FrontendPremTableTests(unittest.TestCase):
    def render(self, table):
        page = (ROOT / "index.html").read_text()
        script = page.split("<script>", 1)[1].split("async function load()", 1)[0]
        program = (
            script
            + "\nconsole.log(JSON.stringify(renderPremTable("
            + json.dumps(table)
            + ")));"
        )
        result = subprocess.run(
            ["node", "-e", program],
            check=True,
            capture_output=True,
            text=True,
        )
        return json.loads(result.stdout)

    def test_table_renderer_is_semantic_accessible_and_highlights_saracens(self):
        rendered = self.render({
            "competition": "Gallagher PREM",
            "season": "2026/27",
            "status": "current",
            "stale": False,
            "retrieved_at_utc": "2026-09-28T02:05:00Z",
            "source_url": "https://www.premrugby.com/standings",
            "teams": [{
                "position": 5, "team": "Saracens", "played": 1, "won": 1,
                "drawn": 0, "lost": 0, "points_difference": 2,
                "try_bonus_points": 1, "losing_bonus_points": 0,
                "bonus_points": 1, "points": 5, "form": ["W"],
            }],
        })

        self.assertIn("<table", rendered)
        self.assertIn("<caption", rendered)
        self.assertIn('scope="col"', rendered)
        self.assertIn('class="saracens-row"', rendered)
        self.assertIn("Saracens are 5th", rendered)
        self.assertIn("Recent form", rendered)
        self.assertIn("Swipe table sideways", rendered)

    def test_missing_table_data_renders_an_explicit_unavailable_state(self):
        rendered = self.render(None)

        self.assertIn("Prem table unavailable", rendered)
        self.assertNotIn("<table", rendered)

    def test_stale_table_retains_rows_and_explains_freshness(self):
        rendered = self.render({
            "competition": "Gallagher PREM",
            "season": "2026/27",
            "status": "stale",
            "stale": True,
            "retrieved_at_utc": "2026-09-27T02:05:00Z",
            "last_attempt_at_utc": "2026-09-28T02:05:00Z",
            "source_url": "https://www.premrugby.com/standings",
            "teams": [{
                "position": 5, "team": "Saracens", "played": 1, "won": 1,
                "drawn": 0, "lost": 0, "points_difference": 2,
                "try_bonus_points": 1, "losing_bonus_points": 0,
                "bonus_points": 1, "points": 5, "form": [],
            }],
        })

        self.assertIn("Showing the last successful update", rendered)
        self.assertIn("Saracens", rendered)


if __name__ == "__main__":
    unittest.main()
