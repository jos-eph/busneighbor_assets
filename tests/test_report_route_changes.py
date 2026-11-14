"""Tests for the route change report."""

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import build_septa_meta
import report_route_changes as report

ROUTES_TXT = (
    "route_id,route_short_name,route_long_name,route_type,route_sort_order\n"
    "2,2,20th-Johnston to Pulaski-Hunting Park,3,10\n"
    "FOX_BUS,FOX,Fox Chase Line Shuttle,3,20\n"
    "44,44,,3,30\n"
    "NAMELESS,,,3,40\n"
)

COVERAGE = {
    "days_observed": 16,
    "vehicle_positions": {"routes": {"2": {"days_seen": 13}}},
}


def document(routes, denied=(), version="v202611010"):
    return {
        "meta": {"start_date": "20261101", "end_date": "20270220",
                 "version": version},
        "buses": {"route_list": list(routes)},
        "realtime": {"source": "manual", "observed_through": None,
                     "overrides": {"no_vehicle_positions": list(denied)}},
    }


def feed():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("routes.txt", ROUTES_TXT)
    return zipfile.ZipFile(io.BytesIO(buffer.getvalue()))


class RouteNamesTest(unittest.TestCase):
    def test_long_name_then_short_name_then_nothing(self):
        self.assertEqual(build_septa_meta.route_names(feed()), {
            "2": "20th-Johnston to Pulaski-Hunting Park",
            "FOX_BUS": "Fox Chase Line Shuttle",
            "44": "44",
        })

    def test_a_route_that_left_the_feed_keeps_its_name(self):
        kept = report.names_to_keep(
            ["2", "FXCB", "GONE"], {"2": "New name"},
            {"2": "Old name", "FXCB": "Fox Chase Line Shuttle"})
        self.assertEqual(kept, {"2": "New name",
                                "FXCB": "Fox Chase Line Shuttle"})


class RouteChangesTest(unittest.TestCase):
    def test_added_removed_and_hidden(self):
        old = document(["L1", "2", "4", "FXCB"], denied=["L1"])
        new = document(["L1", "2", "4", "FOX_BUS"], denied=["L1", "4"])
        self.assertEqual(report.route_changes(new, [("live", old)]), [
            ("4", report.HIDDEN), ("FXCB", report.REMOVED),
            ("FOX_BUS", report.ADDED)])

    def test_no_change(self):
        doc = document(["2", "4"])
        self.assertEqual(report.route_changes(doc, [("live", doc)]), [])


class RenderTest(unittest.TestCase):
    CHANGES = [("FXCB", report.REMOVED), ("FOX_BUS", report.ADDED)]

    def _render(self, **overrides):
        arguments = dict(
            version="v202611010",
            new_names={"FOX_BUS": "Fox Chase Line Shuttle"},
            previous_names={"FXCB": "Fox Chase Line Shuttle"},
            coverage=COVERAGE, pending=["FXCB"])
        arguments.update(overrides)
        return report.render(self.CHANGES, **arguments)

    def test_nothing_changed_renders_nothing(self):
        self.assertEqual(report.render(
            [], version="v1", new_names={}, previous_names={},
            coverage=None, pending=[]), "")

    def test_rows_carry_name_sightings_and_rename_hint(self):
        text = self._render()
        self.assertIn("| FXCB | Removed | Fox Chase Line Shuttle | "
                      "0 of 16 days | Same name as FOX_BUS; possibly a rename |",
                      text)
        self.assertIn("| FOX_BUS | Added | Fox Chase Line Shuttle | "
                      "0 of 16 days | Same name as FXCB; possibly a rename |",
                      text)
        self.assertIn("**Waiting for approval:** FXCB.", text)

    def test_seen_route_shows_its_days(self):
        text = report.render(
            [("2", report.REMOVED)], version="v1", new_names={},
            previous_names={}, coverage=COVERAGE, pending=["2"])
        self.assertIn("| 2 | Removed | unknown | 13 of 16 days |  |", text)

    def test_missing_names_and_coverage_show_unknown(self):
        text = self._render(new_names={}, previous_names={}, coverage=None)
        self.assertIn("| FXCB | Removed | unknown | unknown |  |", text)

    def test_malformed_coverage_shows_unknown(self):
        for coverage in ({}, {"days_observed": 16},
                         {"days_observed": "x", "vehicle_positions": {"routes": {}}},
                         {"days_observed": 16, "vehicle_positions": []}):
            with self.subTest(coverage=coverage):
                self.assertIn("| unknown |", self._render(coverage=coverage))

    def test_different_names_give_no_hint(self):
        text = self._render(new_names={"FOX_BUS": "Something else"})
        self.assertNotIn("rename", text)

    def test_nothing_pending_has_no_waiting_line(self):
        self.assertNotIn("Waiting", self._render(pending=[]))

    def test_pipe_in_a_name_does_not_break_the_table(self):
        text = self._render(previous_names={"FXCB": "A | B"})
        self.assertIn("| A / B |", text)


class MainTest(unittest.TestCase):
    def test_writes_report_and_names(self):
        old = document(["2", "FXCB"])
        candidate = document(["2", "FOX_BUS"])
        to_publish = document(["2", "FXCB", "FOX_BUS"])
        with tempfile.TemporaryDirectory() as tmp:
            def write(name, value):
                path = os.path.join(tmp, name)
                with open(path, "w", encoding="utf-8") as handle:
                    json.dump(value, handle)
                return path
            bundle = os.path.join(tmp, "gtfs.zip")
            with zipfile.ZipFile(bundle, "w") as zf:
                zf.writestr("routes.txt", ROUTES_TXT)
            names_path = os.path.join(tmp, "names.json")
            report_path = os.path.join(tmp, "report.md")
            with contextlib.redirect_stderr(io.StringIO()):
                code = report.main([
                    "--candidate", write("candidate.json", candidate),
                    "--to-publish", write("publish.json", to_publish),
                    "--published", write("old.json", old),
                    "--gtfs-zip", bundle,
                    "--previous-names",
                    write("previous.json", {"FXCB": "Fox Chase Line Shuttle"}),
                    "--coverage", os.path.join(tmp, "missing.json"),
                    "--pending", "FXCB",
                    "--names-output", names_path,
                    "--report-output", report_path])
            self.assertEqual(code, 0)
            with open(names_path, encoding="utf-8") as handle:
                self.assertEqual(json.load(handle), {
                    "2": "20th-Johnston to Pulaski-Hunting Park",
                    "FXCB": "Fox Chase Line Shuttle",
                    "FOX_BUS": "Fox Chase Line Shuttle"})
            with open(report_path, encoding="utf-8") as handle:
                text = handle.read()
            self.assertIn("| FXCB | Removed |", text)
            self.assertIn("| unknown |", text)


if __name__ == "__main__":
    unittest.main()
