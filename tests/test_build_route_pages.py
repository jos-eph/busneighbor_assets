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
PLACES = {"routes": {
    "47": {
        "areas": [{"name": "Olney", "in_philadelphia": True},
                  {"name": "Bella Vista", "in_philadelphia": True},
                  {"name": "Lower Moyamensing", "in_philadelphia": True}],
        "landmarks": ["Pennsylvania Hospital", "Whitman Plaza"],
    },
    "23": {"areas": [{"name": "Cheltenham Township", "in_philadelphia": False}],
           "landmarks": []},
}}


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


class JoinListTest(unittest.TestCase):
    def test_serial_comma(self):
        join = build_route_pages.join_list
        self.assertEqual(join(["A"]), "A")
        self.assertEqual(join(["A", "B"]), "A and B")
        self.assertEqual(join(["A", "B", "C"]), "A, B, and C")


class AreaLabelTest(unittest.TestCase):
    def test_city_suburbs_and_both(self):
        city = {"name": "Olney", "in_philadelphia": True}
        town = {"name": "Media", "in_philadelphia": False}
        label = build_route_pages.area_label
        self.assertEqual(label([city]), "Neighborhoods")
        self.assertEqual(label([town]), "Towns")
        self.assertEqual(label([city, town]), "Neighborhoods and towns")


class BuildTest(unittest.TestCase):
    def build(self, only=None):
        out = Path(tempfile.mkdtemp())
        written = build_route_pages.build(META, SHAPES, NAMES, out, only, PLACES)
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
        self.assertIn('Whitman Plaza to <span class="nowrap">5th-Godfrey</span>', page)
        self.assertIn("Southbound and Northbound", page)
        self.assertIn("preselect: ['47']", page)
        self.assertIn("runs mostly north and south", page)
        self.assertNotIn("$", page)
        self.assertNotIn("#include", page)
        self.assertIn("not affiliated with, endorsed by, or operated by SEPTA", page)

    def test_places_section(self):
        out, _ = self.build()
        page = (out / "47.html").read_text(encoding="utf-8")
        self.assertIn('<h2 id="goes">Where Route 47 goes</h2>', page)
        self.assertIn("<strong>Neighborhoods it stops in:</strong> "
                      "Olney, Bella Vista, and Lower Moyamensing.", page)
        self.assertIn("<strong>Near its stops:</strong> "
                      "Pennsylvania Hospital and Whitman Plaza.", page)
        self.assertIn("Abaca Labs", page)
        self.assertIn("Landmarks from OpenStreetMap.", page)

    def test_towns_only_and_no_landmarks(self):
        out, _ = self.build()
        page = (out / "23.html").read_text(encoding="utf-8")
        self.assertIn("<strong>Towns it stops in:</strong> Cheltenham Township.", page)
        self.assertNotIn("Near its stops", page)
        self.assertNotIn("Abaca Labs", page)
        self.assertNotIn("OpenStreetMap.</p>", page)

    def test_no_places_no_section(self):
        out, _ = self.build()
        page = (out / "T1.html").read_text(encoding="utf-8")
        self.assertNotIn('id="goes"', page)
        self.assertNotIn("$", page)

    def test_place_names_are_escaped(self):
        places = {"routes": {"47": {"areas": [], "landmarks": ["A & B <Mall>"]}}}
        out = Path(tempfile.mkdtemp())
        build_route_pages.build(META, SHAPES, NAMES, out, ["47"], places)
        page = (out / "47.html").read_text(encoding="utf-8")
        self.assertIn("A &amp; B &lt;Mall&gt;", page)
        self.assertNotIn("<Mall>", page)

    def test_committed_places_file(self):
        places = build_route_pages._load(str(build_route_pages.PLACES))
        for route_id, entry in places["routes"].items():
            self.assertRegex(route_id, build_route_pages.ROUTE_ID)
            self.assertTrue(entry["areas"] or entry["landmarks"])
            for area in entry["areas"]:
                self.assertIsInstance(area["name"], str)
                self.assertIsInstance(area["in_philadelphia"], bool)

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
