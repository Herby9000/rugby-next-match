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


if __name__ == "__main__":
    unittest.main()
