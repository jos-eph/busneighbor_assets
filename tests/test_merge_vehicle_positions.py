"""Tests for folding vehicle position snapshots into day files. Stdlib only."""

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import merge_vehicle_positions as merger

FIELDS = ["vehicle_id", "route_id", "lat", "lon"]
T1 = "2026-10-11T02:17:40Z"
T2 = "2026-10-11T05:17:12Z"


def snapshot(sampled_at, vehicles=(("3641", "42", 39.95, -75.2),),
             fields=FIELDS):
    return {"sampled_at": sampled_at, "feed_timestamp": 1791700000,
            "fields": list(fields), "vehicles": [list(v) for v in vehicles]}


class MergeTest(unittest.TestCase):
    def test_first_snapshot_starts_the_day(self):
        day = merger.merge(None, snapshot(T1))

        self.assertEqual(day["date"], "2026-10-11")
        self.assertEqual(day["fields"], FIELDS)
        self.assertEqual(day["samples"], [{
            "sampled_at": T1, "feed_timestamp": 1791700000,
            "vehicles": [["3641", "42", 39.95, -75.2]]}])

    def test_snapshots_are_kept_in_time_order(self):
        day = merger.merge(None, snapshot(T2))
        day = merger.merge(day, snapshot(T1))

        self.assertEqual([s["sampled_at"] for s in day["samples"]], [T1, T2])

    def test_same_snapshot_twice_is_a_no_op(self):
        once = merger.merge(None, snapshot(T1))
        self.assertEqual(merger.merge(once, snapshot(T1)), once)

    def test_snapshot_from_another_day_is_refused(self):
        day = merger.merge(None, snapshot(T1))
        with self.assertRaises(ValueError):
            merger.merge(day, snapshot("2026-10-12T02:17:40Z"))

    def test_changed_fields_are_refused(self):
        day = merger.merge(None, snapshot(T1))
        with self.assertRaises(ValueError):
            merger.merge(day, snapshot(T2, fields=FIELDS + ["speed"]))


class MainTest(unittest.TestCase):
    def test_round_trip_through_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            snap = os.path.join(tmp, "snap.json")
            day = os.path.join(tmp, "day.json")
            with open(snap, "w", encoding="utf-8") as handle:
                json.dump(snapshot(T1), handle)
            with contextlib.redirect_stderr(io.StringIO()):
                first = merger.main(["--snapshot", snap, "--output", day])
                again = merger.main(["--snapshot", snap, "--day", day,
                                     "--output", day])
            with open(day, encoding="utf-8") as handle:
                merged = json.load(handle)

        self.assertEqual((first, again), (0, 0))
        self.assertEqual(len(merged["samples"]), 1)


if __name__ == "__main__":
    unittest.main()
