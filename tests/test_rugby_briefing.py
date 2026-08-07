import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import update_fixtures  # noqa: E402
import generate_ai_briefing  # noqa: E402


class RecentResultsTests(unittest.TestCase):
    def test_official_results_are_filtered_to_team_and_labelled_from_its_perspective(self):
        fixtures = [
            {
                "date_time": 1770000000,
                "date_time_content": {"is_future": 0},
                "event_name": "Premiership",
                "teams": {
                    "score": "32 - 12",
                    "team_home": {"alt": "Exeter Chiefs"},
                    "team_away": {"alt": "Saracens Men"},
                },
            },
            {
                "date_time": 1760000000,
                "date_time_content": {"is_future": 0},
                "event_name": "Premiership",
                "teams": {
                    "score": "26 - 12",
                    "team_home": {"alt": "Saracens Men"},
                    "team_away": {"alt": "Harlequins"},
                },
            },
            {
                "date_time": 1750000000,
                "date_time_content": {"is_future": 0},
                "event_name": "PWR",
                "teams": {
                    "score": "24 - 62",
                    "team_home": {"alt": "Loughborough Lightning"},
                    "team_away": {"alt": "Saracens Women"},
                },
            },
        ]

        results = update_fixtures.official_recent_results(fixtures, "Saracens Men", limit=3)

        self.assertEqual([r["result"] for r in results], ["L", "W"])
        self.assertEqual(results[0]["score"], "Exeter Chiefs 32–12 Saracens Men")
        self.assertEqual(results[1]["score"], "Saracens Men 26–12 Harlequins")

    def test_existing_ai_briefing_is_preserved_for_same_fixture(self):
        new_matches = [{"title": "Saracens vs Bath", "start_utc": "2026-09-01T12:00:00Z"}]
        existing = {
            "matches": [{
                "title": "Saracens vs Bath",
                "start_utc": "2026-09-01T12:00:00Z",
                "ai_briefing": {"text": "Bath will regret getting on the bus."},
            }]
        }

        update_fixtures.preserve_ai_briefings(new_matches, existing)

        self.assertEqual(new_matches[0]["ai_briefing"]["text"], "Bath will regret getting on the bus.")


class AIBriefingTests(unittest.TestCase):
    def sample_data(self):
        return {
            "matches": [{
                "title": "Saracens vs Bath",
                "team": "Saracens Men",
                "opponent": "Bath",
                "competition": "Premiership",
                "venue": "StoneX Stadium",
                "start_utc": "2099-09-01T12:00:00Z",
                "lineup": {
                    "available": True,
                    "teams": {
                        "Saracens": {"starters": [{"number": "10", "name": "Fly Half", "position": "FH"}], "replacements": []},
                        "Bath": {"starters": [{"number": "10", "name": "Other Ten", "position": "FH"}], "replacements": []},
                    },
                },
                "recent_results": [
                    {"result": "W", "score": "Saracens 28–20 Sale", "competition": "Premiership"},
                    {"result": "L", "score": "Leicester 24–18 Saracens", "competition": "Premiership"},
                ],
            }]
        }

    def test_prompt_contains_fixture_lineups_results_and_requested_voice(self):
        prompt = generate_ai_briefing.build_prompt(self.sample_data())

        self.assertIn("Saracens vs Bath", prompt)
        self.assertIn("Fly Half", prompt)
        self.assertIn("Saracens 28–20 Sale", prompt)
        self.assertIn("strong opinions", prompt)
        self.assertIn("no playing experience", prompt)
        self.assertIn("70 to 110 words", prompt)
        self.assertIn("Do not infer age, size, experience", prompt)
        self.assertIn("Label the winner or margin as your prediction", prompt)

    def test_request_disables_hidden_thinking_so_tokens_are_reserved_for_preview(self):
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return json.dumps({"response": "Saracens by seven. The spreadsheet has spoken."}).encode()

        captured = {}

        def fake_open(request, timeout):
            captured.update(json.loads(request.data.decode()))
            return FakeResponse()

        with patch("urllib.request.urlopen", side_effect=fake_open):
            generate_ai_briefing.request_briefing("prompt", model="test-model")

        self.assertIs(captured["think"], False)

    def test_generated_text_is_saved_beneath_matching_next_match(self):
        data = self.sample_data()
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "fixtures.json"
            path.write_text(json.dumps(data))
            with patch.object(generate_ai_briefing, "request_briefing", return_value="Bath are walking into a tactical weather system."):
                generate_ai_briefing.update_file(path, model="test-model")
            saved = json.loads(path.read_text())

        briefing = saved["matches"][0]["ai_briefing"]
        self.assertEqual(briefing["text"], "Bath are walking into a tactical weather system.")
        self.assertEqual(briefing["model"], "test-model")
        self.assertIn("generated_at_utc", briefing)


if __name__ == "__main__":
    unittest.main()
