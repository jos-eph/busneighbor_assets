"""Tests for folding alert snapshots into day files. Stdlib only."""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import merge_service_alerts as merger

T1 = "2026-10-11T02:17:40Z"
T2 = "2026-10-11T05:17:12Z"
T3 = "2026-10-11T08:17:55Z"

ALERT = {"id": "D17048", "header": "Sink Hole", "routes": ["2"],
         "active_periods": [[1790000000, None]], "effect": "DETOUR"}
DETOUR = {"routes": ["2"], "route_direction": "SB",
          "start_location": "17th & Diamond Sts",
          "current_message": "SB via 17th St L - Diamond St"}


def snapshot(sampled_at, alerts=(ALERT,), detours=(DETOUR,)):
    return {
        "sampled_at": sampled_at,
        "feed_timestamp": 1791700000,
        "alerts": list(alerts),
        "detours": None if detours is None else list(detours),
    }


class MergeTest(unittest.TestCase):
    def test_first_snapshot_starts_the_day(self):
        day = merger.merge(None, snapshot(T1))

        self.assertEqual(day["date"], "2026-10-11")
        self.assertEqual(day["samples"],
                         [{"sampled_at": T1, "feed_timestamp": 1791700000}])
        self.assertEqual(day["alerts"],
                         [{**ALERT, "first_seen": T1, "last_seen": T1}])
        self.assertEqual(day["detours"],
                         [{**DETOUR, "first_seen": T1, "last_seen": T1}])

    def test_repeated_alert_is_stored_once_with_its_span(self):
        day = merger.merge(None, snapshot(T1))
        day = merger.merge(day, snapshot(T3))
        day = merger.merge(day, snapshot(T2))

        (alert,) = day["alerts"]
        self.assertEqual((alert["first_seen"], alert["last_seen"]), (T1, T3))
        (detour,) = day["detours"]
        self.assertEqual((detour["first_seen"], detour["last_seen"]), (T1, T3))
        self.assertEqual([s["sampled_at"] for s in day["samples"]],
                         [T1, T2, T3])

    def test_revised_text_is_a_new_version_under_the_same_id(self):
        revised = {**ALERT, "header": "Sink Hole repaired"}
        day = merger.merge(None, snapshot(T1))
        day = merger.merge(day, snapshot(T2, alerts=[revised]))

        self.assertEqual(sorted(a["header"] for a in day["alerts"]),
                         ["Sink Hole", "Sink Hole repaired"])
        self.assertEqual({a["id"] for a in day["alerts"]}, {"D17048"})

    def test_same_snapshot_twice_is_a_no_op(self):
        once = merger.merge(None, snapshot(T1))
        twice = merger.merge(once, snapshot(T1))

        self.assertEqual(once, twice)

    def test_failed_detour_fetch_is_marked_on_the_sample(self):
        day = merger.merge(None, snapshot(T1, detours=None))

        self.assertEqual(day["samples"][0]["detours"], False)
        self.assertEqual(day["detours"], [])

    def test_no_detours_listed_is_not_a_failure(self):
        day = merger.merge(None, snapshot(T1, detours=[]))

        self.assertNotIn("detours", day["samples"][0])

    def test_snapshot_from_another_day_is_refused(self):
        day = merger.merge(None, snapshot(T1))

        with self.assertRaises(ValueError):
            merger.merge(day, snapshot("2026-10-12T02:17:40Z"))


class MainTest(unittest.TestCase):
    def test_round_trip_through_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            snap_path = os.path.join(tmp, "snap.json")
            day_path = os.path.join(tmp, "day.json")
            with open(snap_path, "w", encoding="utf-8") as handle:
                json.dump(snapshot(T1), handle)

            with open(os.devnull, "w") as devnull:
                stderr, sys.stderr = sys.stderr, devnull
                try:
                    code = merger.main(["--snapshot", snap_path,
                                        "--output", day_path])
                    code2 = merger.main(["--snapshot", snap_path,
                                         "--day", day_path,
                                         "--output", day_path])
                finally:
                    sys.stderr = stderr

            self.assertEqual((code, code2), (0, 0))
            with open(day_path, encoding="utf-8") as handle:
                day = json.load(handle)
            self.assertEqual(len(day["samples"]), 1)


if __name__ == "__main__":
    unittest.main()
