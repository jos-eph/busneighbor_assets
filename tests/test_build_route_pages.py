"""Unit tests for build_route_pages. Stdlib only, no network."""

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import build_route_pages  # noqa: E402
import build_septa_shapes  # noqa: E402

LINE = [(39.95, -75.15), (39.96, -75.15), (39.97, -75.149)]
META = {
    "buses": {"route_list": ["L1", "47", " 23 ", "47", "<b>", "T1"]},
    "realtime": {"overrides": {"no_vehicle_positions": ["L1"]}},
}
SHAPES = {"routes": {
    "47": [
        {"dir": 0, "name": "Southbound", "primary": build_septa_shapes.encode_polyline(LINE)},
        {"dir": 1, "name": "Northbound", "primary": build_septa_shapes.encode_polyline(LINE[::-1])},
    ],
}}
NAMES = {"47": "Whitman Plaza to 5th-Godfrey", "23": "A & B <Loop>"}


class OfferedRoutesTest(unittest.TestCase):
    def test_app_rule(self):
        self.assertEqual(build_route_pages.offered_routes(META), ["47", "23", "T1"])

    def test_empty_list_is_an_error(self):
        with self.assertRaises(ValueError):
            build_route_pages.offered_routes({"buses": {"route_list": ["L1"]},
                                              "realtime": META["realtime"]})


class PolylineTest(unittest.TestCase):
    def test_round_trip(self):
        decoded = build_route_pages.decode_polyline(build_septa_shapes.encode_polyline(LINE))
        for (lat, lon), (want_lat, want_lon) in zip(decoded, LINE):
            self.assertAlmostEqual(lat, want_lat, places=5)
            self.assertAlmostEqual(lon, want_lon, places=5)


class BuildTest(unittest.TestCase):
    def build(self, only=None):
        out = Path(tempfile.mkdtemp())
        written = build_route_pages.build(META, SHAPES, NAMES, out, only)
        return out, written

    def test_writes_one_page_per_route(self):
        out, written = self.build()
        self.assertEqual(written, ["47", "23", "T1"])
        self.assertEqual(sorted(p.name for p in out.iterdir()), ["23.html", "47.html", "T1.html"])

    def test_subset(self):
        _, written = self.build(["47"])
        self.assertEqual(written, ["47"])

    def test_subset_must_be_offered(self):
        with self.assertRaises(ValueError):
            self.build(["L1"])

    def test_page_content(self):
        out, _ = self.build()
        page = (out / "47.html").read_text(encoding="utf-8")
        self.assertIn("<title>SEPTA Route 47 Live Bus Tracker — BusNeighbor</title>", page)
        self.assertIn('href="https://bus.dydx.org/route/47"', page)
        self.assertIn("Whitman Plaza to 5th-Godfrey", page)
        self.assertIn("Southbound and Northbound", page)
        self.assertIn("preselect: ['47']", page)
        self.assertIn("runs mostly north and south", page)
        self.assertNotIn("$", page)

    def test_names_are_escaped(self):
        out, _ = self.build()
        page = (out / "23.html").read_text(encoding="utf-8")
        self.assertIn("A &amp; B &lt;Loop&gt;", page)
        self.assertNotIn("<Loop>", page)

    def test_trolley_and_missing_shape(self):
        out, _ = self.build()
        page = (out / "T1.html").read_text(encoding="utf-8")
        self.assertIn("Live Trolley Tracker", page)
        self.assertIn("Route T1", page)
        self.assertNotIn("<svg", page)


if __name__ == "__main__":
    unittest.main()
