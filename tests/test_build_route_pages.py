"""Unit tests for build_route_pages. Stdlib only, no network."""

import contextlib
import io
import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import build_route_pages  # noqa: E402
import build_septa_shapes  # noqa: E402

LINE = [(39.95, -75.15), (39.96, -75.15), (39.97, -75.149)]
META = {
    "buses": {"route_list": ["L1", "47", " 23 ", "47", "<b>", "T1", "MANN", "310"]},
    "realtime": {"overrides": {"no_vehicle_positions": ["L1"]}},
}
SOUTH = ["s1", "s2", "s3", "s4", "s5", "s6"]
SHAPES = {"routes": {
    "47": [
        {"dir": 0, "name": "Southbound", "primary": build_septa_shapes.encode_polyline(LINE),
         "stops": SOUTH},
        {"dir": 1, "name": "Northbound", "primary": build_septa_shapes.encode_polyline(LINE[::-1]),
         "stops": SOUTH[::-1]},
    ],
    "23": [{"dir": 0, "name": "", "stops": ["c1"]}],
    "MANN": [{"dir": 0, "name": "", "stops": ["c2"]}],
    "310": [{"dir": 0, "name": "Loop", "stops": ["l1", "l2", "l1b"]}],
}}
STOPS = {
    "stops": {
        "s1": ["Godfrey Loop - FS", 40.040, -75.130],
        "s2": ["5th St & Godfrey Av", 40.039, -75.130],
        "s3": ["5th St & Olney Av", 40.038, -75.130],
        "s4": ["5th St & Tabor Rd", 40.037, -75.130],
        "s5": ["5th St & Fisher Av", 40.036, -75.130],
        "s6": ["Whitman Plaza - 1", 39.915, -75.155],
        "c1": ["Whitman Plaza", 39.9151, -75.155],   # route 23, beside s6
        "c2": ["Shuttle stop", 40.0401, -75.130],     # a shuttle, beside s1
        "l1": ["Loop Start", 40.1, -75.2],
        "l2": ["Middle St & Far Av", 40.11, -75.2],
        "l1b": ["Loop Start - 2", 40.1, -75.2],
    },
    "rail_stations": [["Olney", 40.0381, -75.1302]],
}
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
        self.assertEqual(build_route_pages.offered_routes(META), ["47", "23", "T1", "MANN", "310"])

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
        written, _ = build_route_pages.build(META, SHAPES, NAMES, out, only, PLACES, STOPS)
        return out, written

    def test_writes_one_page_per_route(self):
        out, written = self.build()
        self.assertEqual(written, ["47", "23", "T1", "310"])  # no page for the shuttle
        self.assertEqual(sorted(p.name for p in out.iterdir()),
                         ["23.html", "310.html", "47.html", "T1.html"])

    def test_subset(self):
        _, written = self.build(["47"])
        self.assertEqual(written, ["47"])

    def test_subset_must_be_offered(self):
        with self.assertRaises(ValueError):
            self.build(["L1"])

    def test_page_content(self):
        out, _ = self.build()
        page = (out / "47.html").read_text(encoding="utf-8")
        self.assertIn("<title>SEPTA Route 47 Bus Tracker: Whitman Plaza to 5th-Godfrey | "
                      "BusNeighbor</title>", page)
        self.assertIn('href="https://bus.dydx.org/route/47"', page)
        self.assertIn('Whitman Plaza to <span class="nowrap">5th-Godfrey</span>', page)
        self.assertIn("Southbound and Northbound", page)
        self.assertIn("preselect: ['47']", page)
        self.assertIn("runs mostly north and south", page)
        self.assertNotIn("$", page)
        self.assertNotIn("#include", page)
        self.assertIn("not affiliated with, endorsed by, or operated by SEPTA", page)

    def test_summary_and_stations(self):
        out, _ = self.build()
        page = (out / "47.html").read_text(encoding="utf-8")
        self.assertIn("<p>Route 47 runs between <strong>Godfrey Loop</strong> and "
                      "<strong>Whitman Plaza</strong>, mostly along 5th Street.</p>", page)
        self.assertIn("<strong>Regional Rail stations near its stops:</strong> Olney.", page)

    def test_loop_summary(self):
        out, _ = self.build()
        page = (out / "310.html").read_text(encoding="utf-8")
        self.assertIn("<p>Route 310 loops from <strong>Loop Start</strong>.</p>", page)

    def test_trolley_summary(self):
        shapes = {"routes": {"T1": [{"dir": 0, "name": "Westbound", "stops": ["s1", "s6"]}]}}
        out = Path(tempfile.mkdtemp())
        build_route_pages.build(META, shapes, NAMES, out, ["T1"], {}, STOPS)
        page = (out / "T1.html").read_text(encoding="utf-8")
        self.assertIn("The Route T1 trolley line runs between", page)

    def test_connections(self):
        out, _ = self.build()
        page = (out / "47.html").read_text(encoding="utf-8")
        self.assertIn("1 other route stops within 100 meters of a Route 47 stop.", page)
        # 23 has a page in this build, so it's a link; the shuttle never appears.
        self.assertIn('<a class="route-tag" href="/route/23">23</a>', page)
        self.assertNotIn("MANN", page)

    def test_connection_without_a_page_is_not_a_link(self):
        out = Path(tempfile.mkdtemp())
        build_route_pages.build(META, SHAPES, NAMES, out, ["47"], PLACES, STOPS)
        page = (out / "47.html").read_text(encoding="utf-8")
        self.assertIn('<span class="route-tag">23</span>', page)
        self.assertNotIn('href="/route/23"', page)

    def test_every_route_link_has_a_page(self):
        out, written = self.build()
        for path in out.iterdir():
            for target in re.findall(r'href="/route/([^"]+)"', path.read_text(encoding="utf-8")):
                self.assertIn(target, written)

    def test_stop_lists(self):
        out, _ = self.build()
        page = (out / "47.html").read_text(encoding="utf-8")
        self.assertIn("<summary>Southbound to Whitman Plaza (6 stops)</summary>", page)
        self.assertIn("<summary>Northbound to Godfrey Loop (6 stops)</summary>", page)
        self.assertIn("<li>5th Street &amp; Godfrey Avenue</li>", page)

    def test_schedule_link_and_independence(self):
        out, _ = self.build()
        for path in out.iterdir():
            page = path.read_text(encoding="utf-8")
            route_id = path.stem
            self.assertIn(f'<a href="https://www.septa.org/schedules/{route_id}" '
                          f'rel="noopener external">Route {route_id} schedule on septa.org</a>',
                          page)
            paragraph = page[page.rindex("<p>", 0, page.index("schedule on septa.org")):]
            self.assertTrue(paragraph.startswith(
                "<p>BusNeighbor is an independent app and doesn't publish schedules."))

    def test_description(self):
        out, _ = self.build()
        page = (out / "47.html").read_text(encoding="utf-8")
        description = re.search(r'<meta name="description" content="([^"]*)">', page).group(1)
        self.assertTrue(description.startswith(
            "Track SEPTA Route 47 buses between Godfrey Loop and Whitman Plaza"))
        self.assertTrue(description.endswith("Free, independent app."))
        self.assertLessEqual(len(description), build_route_pages.MAX_DESCRIPTION)

    def test_long_description_drops_whole_sentences(self):
        def text(first, last):
            facts = build_route_pages.Facts(ends=(first, last), streets=[], centers=[],
                                            rail=[], connections=[], stop_lists=[])
            return build_route_pages.description_text("47", "bus", facts)

        medium = text("A" * 30, "B" * 30)
        self.assertIn("between", medium)
        self.assertTrue(medium.endswith("with detours. Free, independent app."))
        huge = text("A" * 80, "B" * 80)
        self.assertNotIn("between", huge)
        for description in (medium, huge):
            self.assertLessEqual(len(description), build_route_pages.MAX_DESCRIPTION)
            self.assertNotIn("…", description)

    def test_structured_data(self):
        out, _ = self.build()
        page = (out / "47.html").read_text(encoding="utf-8")
        block = re.search(r'<script type="application/ld\+json">(.*?)</script>', page, re.S)
        document = json.loads(block.group(1))
        types = [item["@type"] for item in document["@graph"]]
        self.assertEqual(types, ["BreadcrumbList", "MobileApplication"])
        crumbs = document["@graph"][0]["itemListElement"]
        self.assertEqual([c["item"] for c in crumbs], ["https://bus.dydx.org/",
                                                       "https://bus.dydx.org/routes.html",
                                                       "https://bus.dydx.org/route/47"])

    def test_places_section(self):
        out, _ = self.build()
        page = (out / "47.html").read_text(encoding="utf-8")
        self.assertIn('<h2 id="goes">Where Route 47 goes</h2>', page)
        self.assertIn("<strong>Neighborhoods it stops in:</strong> "
                      "Olney, Bella Vista, and Lower Moyamensing.", page)
        self.assertIn("<strong>Near its stops:</strong> "
                      "Pennsylvania Hospital and Whitman Plaza.", page)
        self.assertIn("by Abaca Labs, via OpenDataPhilly", page)
        self.assertIn('Landmarks: © <a href="https://www.openstreetmap.org/copyright">'
                      'OpenStreetMap contributors</a>.', page)

    def test_towns_only_and_no_landmarks(self):
        out, _ = self.build()
        page = (out / "23.html").read_text(encoding="utf-8")
        self.assertIn("<strong>Towns it stops in:</strong> Cheltenham Township.", page)
        self.assertNotIn("Near its stops", page)
        self.assertNotIn("Abaca Labs", page)
        self.assertIn("Towns: U.S. Census Bureau.", page)
        self.assertNotIn("Landmarks: ©", page)

    def test_no_facts_no_sections(self):
        out, _ = self.build()
        page = (out / "T1.html").read_text(encoding="utf-8")
        for section in ("goes", "connections", "stops"):
            self.assertNotIn(f'id="{section}"', page)
        self.assertNotIn("$", page)

    def test_place_names_are_escaped(self):
        places = {"routes": {"47": {"areas": [], "landmarks": ["A & B <Mall>"]}}}
        out = Path(tempfile.mkdtemp())
        build_route_pages.build(META, SHAPES, NAMES, out, ["47"], places, STOPS)
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
        self.assertIn("<title>SEPTA Route T1 Trolley Tracker | BusNeighbor</title>", page)
        self.assertIn("Route T1", page)
        self.assertNotIn("<svg", page)



class NameOverridesTest(unittest.TestCase):
    def test_applies_only_while_feed_name_matches(self):
        overrides = {"names": {"47": {"name": "Whitman Plaza to 5th-Godfrey Loop",
                                      "feed_name": "Whitman Plaza to 5th-Godfrey"},
                               "23": {"name": "Old name, spelled out", "feed_name": "Old name"}}}
        named = build_route_pages.apply_name_overrides(NAMES, overrides)
        self.assertEqual(named["47"], "Whitman Plaza to 5th-Godfrey Loop")
        self.assertEqual(named["23"], NAMES["23"])  # the feed renamed it since

    def test_committed_file(self):
        overrides = build_route_pages._load(str(build_route_pages.NAME_OVERRIDES))
        for route_id, entry in overrides["names"].items():
            self.assertRegex(route_id, build_route_pages.ROUTE_ID)
            self.assertNotEqual(entry["name"], entry["feed_name"])


class IndexAndSitemapTest(unittest.TestCase):
    def setUp(self):
        self.out = Path(tempfile.mkdtemp())
        self.routes, self.src = build_route_pages.build(META, SHAPES, NAMES, self.out / "route",
                                                        None, PLACES, STOPS)

    def test_index_lists_every_page(self):
        path = self.out / "routes.html"
        build_route_pages.build_index(self.routes, NAMES, self.src, path)
        page = path.read_text(encoding="utf-8")
        links = re.findall(r'<a href="/route/([^"]+)">', page)
        self.assertEqual(links, self.routes)
        self.assertNotIn("#include", page)
        self.assertNotIn("$", page)
        self.assertIn("Whitman Plaza to 5th-Godfrey", page)
        self.assertIn("Along 5th Street", page)
        self.assertIn("A &amp; B &lt;Loop&gt;", page)
        self.assertIn(">Route T1<", page)  # no name: falls back to the number
        self.assertIn(f"these {len(self.routes)} routes", page)

    def test_sitemap(self):
        fixed = ["https://bus.dydx.org/", "https://bus.dydx.org/support.html"]
        xml = build_route_pages.sitemap_xml(fixed, self.routes, "2026-11-14")
        locs = re.findall(r"<loc>([^<]+)</loc>", xml)
        self.assertEqual(locs, fixed + ["https://bus.dydx.org/routes.html"]
                         + [f"https://bus.dydx.org/route/{r}" for r in self.routes])
        self.assertEqual(xml.count("<lastmod>2026-11-14</lastmod>"), len(self.routes) + 1)
        self.assertNotIn("MANN", xml)
        self.assertNotIn("lastmod", build_route_pages.sitemap_xml(fixed, self.routes, ""))

    def test_fixed_sitemap_entries(self):
        entries = build_route_pages.fixed_sitemap_entries()
        self.assertIn("https://bus.dydx.org/", entries)
        self.assertIn("https://bus.dydx.org/share.html", entries)

    def test_main_writes_index_and_sitemap(self):
        files = {}
        for name, document in (("meta", META), ("shapes", {**SHAPES, "generated": "2026-11-14T12:00:00Z"}),
                               ("names", NAMES), ("stops", STOPS), ("places", PLACES)):
            files[name] = self.out / f"{name}.json"
            files[name].write_text(json.dumps(document), encoding="utf-8")
        argv = [f"--{k}={v}" for k, v in files.items()]
        argv += [f"--output-dir={self.out / 'site' / 'route'}", f"--index={self.out / 'site' / 'routes.html'}",
                 f"--sitemap={self.out / 'site' / 'sitemap.xml'}"]
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(build_route_pages.main(argv), 0)
        self.assertTrue((self.out / "site" / "routes.html").exists())
        xml = (self.out / "site" / "sitemap.xml").read_text(encoding="utf-8")
        self.assertIn("<loc>https://bus.dydx.org/route/47</loc><lastmod>2026-11-14</lastmod>", xml)

if __name__ == "__main__":
    unittest.main()
