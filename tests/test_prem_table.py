import copy
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import update_fixtures  # noqa: E402


class PremiershipTableTests(unittest.TestCase):
    def sample_payload(self):
        return {
            "data": {
                "competition": {"name": "Gallagher PREM"},
                "competitionId": 1011,
                "seasonId": 202601,
                "groups": [{
                    "teams": [
                        {
                            "position": 5,
                            "teamId": 2581,
                            "name": "Saracens",
                            "played": 1,
                            "won": 1,
                            "drawn": 0,
                            "lost": 0,
                            "pointsFor": 40,
                            "pointsAgainst": 38,
                            "pointsDiff": 2,
                            "triesBonus": 1,
                            "losingBonus": 0,
                            "bonus": 1,
                            "points": 5,
                        },
                        {
                            "position": 6,
                            "teamId": 1711,
                            "name": "Leicester Tigers",
                            "played": 1,
                            "won": 0,
                            "drawn": 0,
                            "lost": 1,
                            "pointsFor": 38,
                            "pointsAgainst": 40,
                            "pointsDiff": -2,
                            "triesBonus": 1,
                            "losingBonus": 1,
                            "bonus": 2,
                            "points": 2,
                        },
                    ]
                }],
            }
        }

    def test_official_payload_is_normalized_with_required_fields_and_saracens_form(self):
        table = update_fixtures.normalize_prem_table(
            self.sample_payload(),
            {2581: ["W", "L", "D"]},
            "2026-09-28T02:05:00Z",
        )

        self.assertEqual(table["competition"], "Gallagher PREM")
        self.assertEqual(table["season"], "2026/27")
        self.assertEqual(table["status"], "current")
        self.assertFalse(table["stale"])
        self.assertEqual(table["source_url"], update_fixtures.PREM_STANDINGS_URL)
        saracens = table["teams"][0]
        self.assertEqual(
            {key: saracens[key] for key in (
                "position", "team", "played", "won", "drawn", "lost",
                "points_for", "points_against", "points_difference",
                "try_bonus_points", "losing_bonus_points", "bonus_points", "points",
            )},
            {
                "position": 5, "team": "Saracens", "played": 1, "won": 1,
                "drawn": 0, "lost": 0, "points_for": 40, "points_against": 38,
                "points_difference": 2, "try_bonus_points": 1,
                "losing_bonus_points": 0, "bonus_points": 1, "points": 5,
            },
        )
        self.assertEqual(saracens["form"], ["W", "L", "D"])
        self.assertTrue(update_fixtures.valid_prem_table(table))

    def test_invalid_payload_is_rejected_instead_of_publishing_partial_standings(self):
        payload = self.sample_payload()
        del payload["data"]["groups"][0]["teams"][0]["points"]

        with self.assertRaises(ValueError):
            update_fixtures.normalize_prem_table(payload, {}, "2026-09-28T02:05:00Z")

    def test_fetch_failure_preserves_last_valid_table_and_marks_it_stale(self):
        existing = update_fixtures.normalize_prem_table(
            self.sample_payload(), {}, "2026-09-27T02:05:00Z"
        )
        original = copy.deepcopy(existing)

        with patch.object(update_fixtures, "fetch_prem_table", side_effect=OSError("offline")):
            table, note = update_fixtures.refresh_prem_table(
                {"prem_table": existing}, "2026-09-28T02:05:00Z"
            )

        self.assertEqual(table["teams"], original["teams"])
        self.assertTrue(table["stale"])
        self.assertEqual(table["status"], "stale")
        self.assertEqual(table["retrieved_at_utc"], original["retrieved_at_utc"])
        self.assertEqual(table["last_attempt_at_utc"], "2026-09-28T02:05:00Z")
        self.assertIn("preserved", note.lower())

    def test_fetch_failure_without_saved_data_returns_explicit_unavailable_shape(self):
        with patch.object(update_fixtures, "fetch_prem_table", side_effect=OSError("offline")):
            table, note = update_fixtures.refresh_prem_table({}, "2026-09-28T02:05:00Z")

        self.assertEqual(table["teams"], [])
        self.assertEqual(table["status"], "unavailable")
        self.assertTrue(table["stale"])
        self.assertIn("unavailable", note.lower())


class PublishedFixtureSchemaTests(unittest.TestCase):
    def test_checked_in_fixture_data_has_a_valid_prem_table_object(self):
        data = json.loads((ROOT / "fixtures.json").read_text())
        self.assertTrue(update_fixtures.valid_prem_table(data.get("prem_table")))


if __name__ == "__main__":
    unittest.main()
