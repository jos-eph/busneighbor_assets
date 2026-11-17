"""Unit tests for route_facts. Stdlib only, no network."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import route_facts  # noqa: E402

# About 11 m per 0.0001 degree of latitude.
STOPS = {
    "a": ["Godfrey Loop - FS", 40.0400, -75.1300],
    "b": ["5th St & Godfrey Av", 40.0390, -75.1300],
    "c": ["5th St & Olney Av", 40.0380, -75.1300],
    "d": ["5th St & Tabor Rd", 40.0370, -75.1300],
    "e": ["5th St & Fisher Av - MBFS", 40.0360, -75.1300],
    "f": ["8th St & Market St", 39.9516, -75.1537],
    "g": ["Whitman Plaza - 1", 39.9150, -75.1550],
    "h": ["Whitman Plaza - 2", 39.9151, -75.1550],
    "x": ["Market St & 8th St", 39.9517, -75.1538],   # route 9, about 14 m from f
    "y": ["Olney Transit Center", 40.0381, -75.1301],  # route 9, by c
}
SHAPES = {
    "47": [
        {"dir": 0, "name": "Southbound", "stops": ["a", "b", "c", "d", "e", "f", "g", "gone"]},
        {"dir": 1, "name": "Northbound", "stops": ["h", "f", "e", "e", "a"]},
    ],
    "9": [{"dir": 0, "name": "Eastbound", "stops": ["x", "y"]}],
    "99": [{"dir": 0, "name": "Eastbound", "stops": ["g"]}],
}
RAIL = [["Olney", 40.0383, -75.1330], ["Far Away", 41.0, -76.0]]


class CleanStopNameTest(unittest.TestCase):
    def test_position_notes_dropped(self):
        clean = route_facts.clean_stop_name
        self.assertEqual(clean("Godfrey Loop - FS"), "Godfrey Loop")
        self.assertEqual(clean("Whitman Plaza - 1"), "Whitman Plaza")
        self.assertEqual(clean("Oregon Av & 5th St - 2 MBFS"), "Oregon Avenue & 5th Street")
        self.assertEqual(clean("Bethlehem Pk & Main St  - onsite"), "Bethlehem Pike & Main Street")

    def test_abbreviations_after_a_word_only(self):
        clean = route_facts.clean_stop_name
        self.assertEqual(clean("Washington Sq & Locust St"), "Washington Square & Locust Street")
        self.assertEqual(clean("City Av & St Josephs Univ"), "City Avenue & St Josephs Univ")
        self.assertEqual(clean("Rising Sun Av & St. Vincent St"),
                         "Rising Sun Avenue & St. Vincent Street")
        self.assertEqual(clean("Street Rd & Knights Rd"), "Street Road & Knights Road")

    def test_other_notes_kept(self):
        self.assertEqual(route_facts.clean_stop_name("Frankford Transit Center - Main Dropoff"),
                         "Frankford Transit Center - Main Dropoff")


class RouteFactsTest(unittest.TestCase):
    def test_stop_lists(self):
        lists = route_facts.stop_lists(SHAPES["47"], STOPS)
        self.assertEqual(lists[0]["name"], "Southbound")
        self.assertEqual(lists[0]["stops"][0], "Godfrey Loop")
        self.assertEqual(lists[0]["stops"][-1], "Whitman Plaza")  # unknown id skipped
        # A stop listed twice in a row appears once.
        self.assertEqual(lists[1]["stops"], ["Whitman Plaza", "8th Street & Market Street",
                                             "5th Street & Fisher Avenue", "Godfrey Loop"])

    def test_end_points(self):
        self.assertEqual(route_facts.end_points(SHAPES["47"], STOPS),
                         ("Godfrey Loop", "Whitman Plaza"))
        self.assertIsNone(route_facts.end_points([], STOPS))

    def test_main_streets(self):
        self.assertEqual(route_facts.main_streets(SHAPES["47"], STOPS), ["5th Street"])

    def test_connections(self):
        routes = ["47", "9", "99"]
        self.assertEqual(route_facts.connections("47", routes, SHAPES, STOPS), ["9", "99"])
        self.assertEqual(route_facts.connections("9", routes, SHAPES, STOPS), ["47"])
        # Only routes in the list count, and never the route itself.
        self.assertEqual(route_facts.connections("47", ["47", "9"], SHAPES, STOPS), ["9"])

    def test_connection_radius(self):
        near = {"p": ["A", 40.0, -75.0], "q": ["B", 40.0008, -75.0]}  # about 88 m
        far = {"p": ["A", 40.0, -75.0], "q": ["B", 40.0010, -75.0]}   # about 111 m
        shapes = {"1": [{"stops": ["p"]}], "2": [{"stops": ["q"]}]}
        self.assertEqual(route_facts.connections("1", ["1", "2"], shapes, near), ["2"])
        self.assertEqual(route_facts.connections("1", ["1", "2"], shapes, far), [])

    def test_connection_east_west(self):
        # 0.0011 degrees of longitude is about 94 m here.
        stops = {"p": ["A", 40.0, -75.0], "q": ["B", 40.0, -75.0011]}
        shapes = {"1": [{"stops": ["p"]}], "2": [{"stops": ["q"]}]}
        self.assertEqual(route_facts.connections("1", ["1", "2"], shapes, stops), ["2"])

    def test_stations(self):
        stations = route_facts.stations(SHAPES["9"], STOPS, RAIL)
        self.assertEqual(stations, {"centers": ["Olney Transit Center"], "rail": ["Olney"]})
        self.assertEqual(route_facts.stations(SHAPES["99"], STOPS, RAIL),
                         {"centers": [], "rail": []})


if __name__ == "__main__":
    unittest.main()
