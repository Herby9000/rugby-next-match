import copy
import json
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import update_fixtures  # noqa: E402


class SaracensSeasonTests(unittest.TestCase):
    NOW = datetime(2026, 9, 28, 12, tzinfo=timezone.utc)

    def fixture(self, date, home, away, score="", competition="Gallagher PREM", venue="Ground"):
        return {
            "date_time": int(datetime.fromisoformat(date).timestamp()),
            "date_time_content": {"is_future": 0 if score else 1},
            "event_name": competition,
            "venue": venue,
            "teams": {
                "score": score,
                "team_home": {"alt": home},
                "team_away": {"alt": away},
            },
        }

    def payload(self):
        fixtures = []
        for day in range(1, 7):
            fixtures.append(self.fixture(
                f"2026-09-{day:02d}T15:00:00+00:00",
                "Saracens Men" if day % 2 else f"Opponent {day}",
                f"Opponent {day}" if day % 2 else "Saracens Men",
                f"{20 + day} - {10 + day}" if day % 2 else f"{10 + day} - {20 + day}",
                venue=f"Ground {day}",
            ))
        for day in range(1, 7):
            fixtures.append(self.fixture(
                f"2026-10-{day:02d}T15:30:00+00:00",
                "Saracens Men" if day % 2 else f"Future {day}",
                f"Future {day}" if day % 2 else "Saracens Men",
                venue=f"Future Ground {day}",
            ))
        fixtures.extend([
            self.fixture("2026-09-20T14:00:00+00:00", "Saracens Women", "Sale Sharks", "30 - 10", "PWR"),
            self.fixture("2026-09-21T14:00:00+00:00", "Saracens Men's Academy", "Bath Academy", "30 - 10", "Academy"),
        ])
        return {"fixtures": fixtures}

    def test_normalizes_exactly_five_results_and_five_upcoming_with_match_details(self):
        season = update_fixtures.normalize_saracens_season(
            self.payload(), "2026-09-28T12:00:00Z", now=self.NOW
        )

        self.assertEqual(season["status"], "current")
        self.assertFalse(season["stale"])
        self.assertEqual(len(season["recent_results"]), 5)
        self.assertEqual(len(season["upcoming_fixtures"]), 5)
        self.assertEqual([item["opponent"] for item in season["recent_results"]], [
            "Opponent 6", "Opponent 5", "Opponent 4", "Opponent 3", "Opponent 2"
        ])
        away_result = season["recent_results"][0]
        self.assertEqual(away_result["home_away"], "Away")
        self.assertEqual(away_result["score"], "Opponent 6 16–26 Saracens Men")
        self.assertEqual(away_result["result"], "W")
        self.assertEqual(away_result["competition"], "Gallagher PREM")
        self.assertEqual(away_result["venue"], "Ground 6")
        first_future = season["upcoming_fixtures"][0]
        self.assertEqual(first_future["opponent"], "Future 1")
        self.assertEqual(first_future["home_away"], "Home")
        self.assertEqual(first_future["start_utc"], "2026-10-01T15:30:00Z")
        self.assertEqual(first_future["kickoff_status"], "Confirmed")
        self.assertEqual(first_future["venue"], "Future Ground 1")

    def test_schema_rejects_partial_or_over_bound_snapshots(self):
        valid = update_fixtures.normalize_saracens_season(
            self.payload(), "2026-09-28T12:00:00Z", now=self.NOW
        )
        self.assertTrue(update_fixtures.valid_saracens_season(valid))

        missing = copy.deepcopy(valid)
        del missing["upcoming_fixtures"][0]["opponent"]
        self.assertFalse(update_fixtures.valid_saracens_season(missing))

        over_bound = copy.deepcopy(valid)
        over_bound["recent_results"].append(copy.deepcopy(valid["recent_results"][0]))
        self.assertFalse(update_fixtures.valid_saracens_season(over_bound))

    def test_malformed_official_saracens_item_is_rejected_not_partially_published(self):
        payload = self.payload()
        del payload["fixtures"][0]["venue"]

        with self.assertRaises(ValueError):
            update_fixtures.normalize_saracens_season(
                payload, "2026-09-28T12:00:00Z", now=self.NOW
            )

    def test_fetch_failure_preserves_last_valid_snapshot_and_marks_it_stale(self):
        existing = update_fixtures.normalize_saracens_season(
            self.payload(), "2026-09-27T12:00:00Z", now=self.NOW
        )
        original = copy.deepcopy(existing)

        with patch.object(update_fixtures, "fetch_saracens_season", side_effect=OSError("offline")):
            season, note = update_fixtures.refresh_saracens_season(
                {"saracens_season": existing}, "2026-09-28T12:00:00Z"
            )

        self.assertEqual(season["recent_results"], original["recent_results"])
        self.assertEqual(season["upcoming_fixtures"], original["upcoming_fixtures"])
        self.assertEqual(season["status"], "stale")
        self.assertTrue(season["stale"])
        self.assertEqual(season["retrieved_at_utc"], original["retrieved_at_utc"])
        self.assertEqual(season["last_attempt_at_utc"], "2026-09-28T12:00:00Z")
        self.assertIn("preserved", note.lower())

    def test_fetch_failure_without_snapshot_returns_unavailable_state(self):
        with patch.object(update_fixtures, "fetch_saracens_season", side_effect=OSError("offline")):
            season, note = update_fixtures.refresh_saracens_season(
                {}, "2026-09-28T12:00:00Z"
            )

        self.assertEqual(season["status"], "unavailable")
        self.assertTrue(season["stale"])
        self.assertEqual(season["recent_results"], [])
        self.assertEqual(season["upcoming_fixtures"], [])
        self.assertIn("unavailable", note.lower())


class PublishedSeasonSchemaTests(unittest.TestCase):
    def test_checked_in_fixture_data_has_a_valid_season_snapshot(self):
        data = json.loads((ROOT / "fixtures.json").read_text())
        self.assertTrue(update_fixtures.valid_saracens_season(data.get("saracens_season")))


if __name__ == "__main__":
    unittest.main()
