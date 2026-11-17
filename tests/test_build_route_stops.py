"""Unit tests for build_route_stops. Stdlib only, no network."""

import io
import json
import os
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import build_route_stops  # noqa: E402

FEED_INFO = (
    "feed_publisher_name,feed_lang,feed_start_date,feed_end_date,feed_version\n"
    "SEPTA,en,20261101,20270220,v202611010\n"
)
BUS_STOPS = (
    "stop_id,stop_name,stop_lat,stop_lon\n"
    "s1,8th St & Market St ,39.9516123,-75.1537456\n"
    "s2,8th St & Godfrey Av,40.0411,-75.1271\n"
    "unused,Nowhere,40.0,-75.0\n"
)
ROUTE_STOPS_HEADER = "route_id,direction_id,stop_id,route_stop_sort_order\n"
ROUTE_STOPS = ROUTE_STOPS_HEADER + "47,0,s2,2\n47,0,s1,1\n47,1,s1,1\n"
RAIL_STATIONS = (
    "stop_id,stop_name,stop_lat,stop_lon,location_type\n"
    "90001,Olney,40.0336,-75.1423,1\n"
    "90002,Olney platform,40.0337,-75.1424,0\n"
    "90003,Jefferson Station,39.9525,-75.1580,1\n"
)
RAIL_PLAIN = (
    "stop_id,stop_name,stop_lat,stop_lon\n"
    "90001,Olney,40.0336,-75.1423\n"
)


def _zip(members: dict[str, str | bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return buffer.getvalue()


def make_bundle(bus_stops=BUS_STOPS, rail_stops=RAIL_STATIONS, route_stops=ROUTE_STOPS) -> bytes:
    # The feed's text files start with a byte order mark.
    bus = _zip({"feed_info.txt": FEED_INFO, "stops.txt": "\ufeff" + bus_stops,
                "route_stops.txt": route_stops})
    rail = _zip({"stops.txt": rail_stops})
    return _zip({"google_bus.zip": bus, "google_rail.zip": rail})


class RouteStopsTest(unittest.TestCase):
    def build(self, bundle: bytes) -> dict:
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "gtfs_public.zip")
            with open(path, "wb") as handle:
                handle.write(bundle)
            return build_route_stops.build(path)

    def test_document(self):
        document = self.build(make_bundle())
        self.assertEqual(document["gtfs_version"], "v202611010")
        self.assertEqual(document["stops"], {
            "s1": ["8th St & Market St", 39.95161, -75.15375],
            "s2": ["8th St & Godfrey Av", 40.0411, -75.1271],
        })
        self.assertEqual(document["rail_stations"], [
            ["Jefferson Station", 39.9525, -75.158],
            ["Olney", 40.0336, -75.1423],
        ])

    def test_feed_without_stations_uses_every_stop(self):
        document = self.build(make_bundle(rail_stops=RAIL_PLAIN))
        self.assertEqual(document["rail_stations"], [["Olney", 40.0336, -75.1423]])

    def test_a_few_undefined_stops_are_skipped(self):
        many = "".join(f"s{i},Stop {i},40.0,-75.0\n" for i in range(1, 201))
        routes = "".join(f"47,0,s{i},{i}\n" for i in range(1, 202))  # s201 is undefined
        document = self.build(make_bundle(bus_stops="stop_id,stop_name,stop_lat,stop_lon\n" + many,
                                          route_stops=ROUTE_STOPS_HEADER + routes))
        self.assertEqual(len(document["stops"]), 200)
        self.assertNotIn("s201", document["stops"])

    def test_many_undefined_stops_are_an_error(self):
        with self.assertRaises(ValueError):
            self.build(make_bundle(bus_stops="stop_id,stop_name,stop_lat,stop_lon\n"
                                             "s1,A,40.0,-75.0\n"))

    def test_missing_rail_feed_is_an_error(self):
        bus = zipfile.ZipFile(io.BytesIO(make_bundle())).read("google_bus.zip")
        with self.assertRaises(ValueError):
            self.build(_zip({"google_bus.zip": bus}))

    def test_output_is_byte_stable(self):
        first = build_route_stops.serialize(self.build(make_bundle()))
        second = build_route_stops.serialize(self.build(make_bundle()))
        self.assertEqual(first, second)
        self.assertEqual(json.loads(first)["v"], build_route_stops.SCHEMA_VERSION)

    def test_main_writes_the_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle = os.path.join(tmp, "gtfs_public.zip")
            with open(bundle, "wb") as handle:
                handle.write(make_bundle())
            out = os.path.join(tmp, "out")
            self.assertEqual(build_route_stops.main(["--gtfs-zip", bundle, "--output-dir", out]), 0)
            with open(os.path.join(out, build_route_stops.OUTPUT_NAME), encoding="utf-8") as handle:
                self.assertIn("s1", json.load(handle)["stops"])


if __name__ == "__main__":
    unittest.main()
