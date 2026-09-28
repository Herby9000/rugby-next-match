import json
import re
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


class FrontendSeasonAndNavigationTests(unittest.TestCase):
    def render(self, season):
        page = (ROOT / "index.html").read_text()
        script = page.split("<script>", 1)[1].split("async function load()", 1)[0]
        program = (
            script
            + "\nconsole.log(JSON.stringify(renderSaracensSeason("
            + json.dumps(season)
            + ")));"
        )
        result = subprocess.run(
            ["node", "-e", program], check=True, capture_output=True, text=True
        )
        return json.loads(result.stdout)

    def test_season_renderer_shows_results_form_and_emphasizes_nearest_fixture(self):
        rendered = self.render({
            "status": "current",
            "stale": False,
            "retrieved_at_utc": "2026-09-28T12:00:00Z",
            "source_url": "https://saracens.com/fixtures-results/",
            "recent_results": [{
                "date": "2026-09-05", "opponent": "Northampton Saints",
                "home_away": "Home", "competition": "Prem Rugby Cup",
                "venue": "StoneX Stadium", "score": "Saracens Men 96–42 Northampton Saints",
                "result": "W",
            }],
            "upcoming_fixtures": [{
                "date": "2026-10-04", "start_utc": "2026-10-04T15:00:00Z",
                "opponent": "Sale <Sharks>", "home_away": "Home",
                "competition": "Gallagher PREM", "venue": "StoneX Stadium",
                "kickoff_status": "Confirmed",
            }],
        })

        self.assertIn("Saracens season", rendered)
        self.assertIn("Recent results", rendered)
        self.assertIn("Next five", rendered)
        self.assertIn('class="season-item next-up"', rendered)
        self.assertIn('aria-label="Win"', rendered)
        self.assertIn("Saracens Men 96–42 Northampton Saints", rendered)
        self.assertIn("Sale &lt;Sharks&gt;", rendered)
        self.assertNotIn("Sale <Sharks>", rendered)

    def test_unavailable_and_stale_season_states_are_explicit(self):
        unavailable = self.render(None)
        self.assertIn("Season data unavailable", unavailable)

        stale = self.render({
            "status": "stale", "stale": True,
            "retrieved_at_utc": "2026-09-27T12:00:00Z",
            "source_url": "https://saracens.com/fixtures-results/",
            "recent_results": [], "upcoming_fixtures": [],
        })
        self.assertIn("Showing the last successful season update", stale)

    def test_navigation_is_semantic_keyboard_native_and_targets_page_sections(self):
        page = (ROOT / "index.html").read_text()

        self.assertIn('<nav class="section-nav" aria-label="Page sections">', page)
        self.assertIn('href="#next-match"', page)
        self.assertIn('href="#season"', page)
        self.assertIn('href="#prem-table"', page)
        self.assertIn('id="next-match"', page)
        self.assertIn('id="season"', page)
        self.assertIn('id="prem-table"', page)
        self.assertRegex(page, re.compile(r"\.section-nav a\s*\{[^}]*min-height:\s*44px", re.S))
        self.assertIn(":focus-visible", page)

    def test_mobile_overflow_intent_theme_and_existing_features_remain(self):
        page = (ROOT / "index.html").read_text()
        manifest = json.loads((ROOT / "site.webmanifest").read_text())

        self.assertIn("overflow-x: hidden", page)
        self.assertIn("max-width: 100%", page)
        self.assertIn("function renderAiBriefing", page)
        self.assertIn("function renderLineups", page)
        self.assertIn("function renderPremTable", page)
        self.assertIn("saracens-row", page)
        self.assertIn('<meta name="theme-color" content="#090a0c"', page)
        self.assertEqual(manifest["theme_color"], "#090a0c")
        self.assertEqual(manifest["background_color"], "#090a0c")


if __name__ == "__main__":
    unittest.main()
