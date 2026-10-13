"""Tests for folding vehicle position snapshots into day CSVs. Stdlib only."""

import contextlib
import csv
import io
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import merge_vehicle_positions as merger

FIELDS = ["vehicle_id", "route_id", "trip_id", "direction_id", "lat", "lon",
          "bearing", "speed", "timestamp", "stop_id", "current_stop_sequence",
          "current_status"]
T1 = "2026-10-11T02:17:40Z"
T2 = "2026-10-11T05:17:12Z"
FEED_AT = 1791685045     # 2026-10-11T02:17:25Z
REPORTED = 1791685040    # 2026-10-11T02:17:20Z, 20 s before T1


def vehicle(vehicle_id="3641", route_id="42", **overrides):
    row = dict(vehicle_id=vehicle_id, route_id=route_id, trip_id="950094",
               direction_id=0, lat=39.95, lon=-75.2, bearing=90.0, speed=4.5,
               timestamp=REPORTED, stop_id="311", current_stop_sequence=43,
               current_status="IN_TRANSIT_TO")
    row.update(overrides)
    return [row[field] for field in FIELDS]


def snapshot(sampled_at=T1, vehicles=None, fields=FIELDS):
    return {"sampled_at": sampled_at, "feed_timestamp": FEED_AT,
            "fields": list(fields),
            "vehicles": vehicles if vehicles is not None else [vehicle()]}


def column(rows, name):
    return [row[name] for row in rows]


class SnapshotRowsTest(unittest.TestCase):
    def test_columns_are_named_and_readable(self):
        (row,) = merger.merge(None, snapshot())

        self.assertEqual(tuple(row), merger.COLUMNS)
        self.assertEqual(row["sampled_at"], T1)
        self.assertEqual(row["feed_time"], "2026-10-11T02:17:25Z")
        self.assertEqual(row["reported_at"], "2026-10-11T02:17:20Z")
        self.assertEqual(row["report_age_s"], "20")
        self.assertEqual(row["bearing_deg"], "90.0")
        self.assertEqual(row["speed_mps"], "4.5")
        self.assertEqual(row["stop_sequence"], "43")
        self.assertEqual(row["status"], "IN_TRANSIT_TO")

    def test_what_the_feed_left_out_is_blank(self):
        tripless = vehicle(route_id=None, trip_id=None, direction_id=None,
                           bearing=None, stop_id=None,
                           current_stop_sequence=None, current_status=None)
        (row,) = merger.merge(None, snapshot(vehicles=[tripless]))

        for name in ("route_id", "trip_id", "direction_id", "bearing_deg",
                     "stop_id", "stop_sequence", "status"):
            self.assertEqual(row[name], "", name)

    def test_no_report_time_leaves_both_times_blank(self):
        (row,) = merger.merge(None, snapshot(vehicles=[vehicle(timestamp=None)]))

        self.assertEqual((row["reported_at"], row["report_age_s"]), ("", ""))

    def test_fields_are_matched_by_name_not_position(self):
        shuffled = list(reversed(FIELDS))
        (row,) = merger.merge(None, snapshot(
            vehicles=[list(reversed(vehicle()))], fields=shuffled))

        self.assertEqual((row["vehicle_id"], row["route_id"]), ("3641", "42"))

    def test_names_from_the_sampler_are_kept(self):
        fields = FIELDS + ["direction", "trip_headsign", "stop_name"]
        named = vehicle() + ["Westbound", "Wycombe", "Pine St & 3rd St"]
        (row,) = merger.merge(None, snapshot(vehicles=[named], fields=fields))

        self.assertEqual(
            (row["direction"], row["trip_headsign"], row["stop_name"]),
            ("Westbound", "Wycombe", "Pine St & 3rd St"))

    def test_a_snapshot_without_names_leaves_them_blank(self):
        (row,) = merger.merge(None, snapshot())

        self.assertEqual(
            (row["direction"], row["trip_headsign"], row["stop_name"]),
            ("", "", ""))

    def test_a_snapshot_missing_a_needed_field_is_refused(self):
        with self.assertRaises(ValueError):
            merger.merge(None, snapshot(fields=FIELDS[:-1]))


class OrderTest(unittest.TestCase):
    def test_routes_run_numbers_first_then_letters_then_no_trip(self):
        rows = merger.merge(None, snapshot(vehicles=[
            vehicle("1", "101"), vehicle("2", None), vehicle("3", "T1"),
            vehicle("4", "9"), vehicle("5", "42")]))

        self.assertEqual(column(rows, "route_id"), ["9", "42", "101", "T1", ""])

    def test_vehicles_within_a_route_are_in_numeric_order(self):
        rows = merger.merge(None, snapshot(vehicles=[
            vehicle("100"), vehicle("99"), vehicle("1003")]))

        self.assertEqual(column(rows, "vehicle_id"), ["99", "100", "1003"])

    def test_a_late_snapshot_still_lands_in_time_order(self):
        rows = merger.merge(None, snapshot(T2))
        rows = merger.merge(rows, snapshot(T1))

        self.assertEqual(column(rows, "sampled_at"), [T1, T2])


class MergeTest(unittest.TestCase):
    def test_same_snapshot_twice_is_a_no_op(self):
        once = merger.merge(None, snapshot())
        self.assertEqual(merger.merge(once, snapshot()), once)

    def test_snapshot_from_another_day_is_refused(self):
        rows = merger.merge(None, snapshot())
        with self.assertRaises(ValueError):
            merger.merge(rows, snapshot("2026-10-12T02:17:40Z"))

    def test_a_day_file_with_other_columns_is_refused(self):
        with self.assertRaises(ValueError):
            merger.parse_day("vehicle_id,route_id\n3641,42\n")

    def test_render_and_parse_round_trip(self):
        rows = merger.merge(None, snapshot())
        self.assertEqual(merger.parse_day(merger.render(rows)), rows)


class MainTest(unittest.TestCase):
    def test_round_trip_through_files_is_byte_stable(self):
        with tempfile.TemporaryDirectory() as tmp:
            snap = os.path.join(tmp, "snap.json")
            day = os.path.join(tmp, "day.csv")
            with open(snap, "w", encoding="utf-8") as handle:
                json.dump(snapshot(), handle)
            with contextlib.redirect_stderr(io.StringIO()):
                first = merger.main(["--snapshot", snap, "--output", day])
                with open(day, encoding="utf-8") as handle:
                    before = handle.read()
                again = merger.main(["--snapshot", snap, "--day", day,
                                     "--output", day])
            with open(day, encoding="utf-8") as handle:
                after = handle.read()

        self.assertEqual((first, again), (0, 0))
        self.assertEqual(after, before)
        rows = list(csv.DictReader(io.StringIO(after)))
        self.assertEqual(len(rows), 1)

    def test_bad_day_file_fails_without_writing(self):
        with tempfile.TemporaryDirectory() as tmp:
            snap = os.path.join(tmp, "snap.json")
            day = os.path.join(tmp, "day.csv")
            out = os.path.join(tmp, "out.csv")
            with open(snap, "w", encoding="utf-8") as handle:
                json.dump(snapshot(), handle)
            with open(day, "w", encoding="utf-8") as handle:
                handle.write("not,the,columns\n")
            with contextlib.redirect_stderr(io.StringIO()):
                code = merger.main(["--snapshot", snap, "--day", day,
                                    "--output", out])

            self.assertEqual(code, 1)
            self.assertFalse(os.path.exists(out))


if __name__ == "__main__":
    unittest.main()
