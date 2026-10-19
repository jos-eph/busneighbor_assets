"""Unit tests for build_septa_shapes. Stdlib only, no network."""

import io
import json
import os
import sys
import tempfile
import unittest
import zipfile
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import build_septa_meta  # noqa: E402
import build_septa_shapes  # noqa: E402

GENERATED = datetime(2026, 10, 18, 6, 0, tzinfo=timezone.utc)
FEED_INFO = (
    "feed_publisher_name,feed_lang,feed_start_date,feed_end_date,feed_version\n"
    "SEPTA,en,20260927,20270220,v202609271\n"
)

# Filler routes keep the fixture above the MIN_ROUTES floor. Each has one trip
# on the shared FILLER shape and no stops or direction names.
FILLER_COUNT = build_septa_meta.MIN_ROUTES

# Route 64, direction 0: shape A (two trips) is primary; B is a branch (one
# trip). Direction 1 uses shape C. Shape A's middle point is 1 m off the line
# from start to end, so 5 m simplification drops it.
SHAPES = {
    "A": [(39.95000, -75.16000), (39.95500, -75.15999), (39.96000, -75.16000)],
    "B": [(39.95000, -75.16000), (39.95000, -75.17000)],
    "C": [(39.96000, -75.16000), (39.95000, -75.16000)],
    "FILLER": [(40.00000, -75.20000), (40.00100, -75.20000)],
}


def make_feed(trips_extra="", directions=True, shapes=None):
    shapes = SHAPES if shapes is None else shapes
    routes = "route_id,route_type,route_sort_order\n64,3,1\n" + "".join(
        f"F{i},3,{100 + i}\n" for i in range(FILLER_COUNT)
    )
    trips = (
        "route_id,service_id,trip_id,direction_id,shape_id\n"
        "64,1,t1,0,A\n64,1,t2,0,A\n64,1,t3,0,B\n64,1,t4,1,C\n"
        + "".join(f"F{i},1,f{i},0,FILLER\n" for i in range(FILLER_COUNT))
        + trips_extra
    )
    shape_rows = "shape_id,shape_pt_lat,shape_pt_lon,shape_pt_sequence\n" + "".join(
        f"{shape_id},{lat},{lon},{seq}\n"
        for shape_id, points in shapes.items()
        # Written in reverse to prove points are ordered by sequence.
        for seq, (lat, lon) in reversed(list(enumerate(points, start=1)))
    )
    route_stops = (
        "route_id,direction_id,stop_id,route_stop_sort_order\n"
        "64,0,s3,3\n64,0,s1,1\n64,0,s2,2\n64,1,s3,1\n"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("routes.txt", routes)
        zf.writestr("feed_info.txt", FEED_INFO)
        zf.writestr("trips.txt", trips)
        zf.writestr("shapes.txt", shape_rows)
        zf.writestr("route_stops.txt", route_stops)
        if directions:
            zf.writestr(
                "directions.txt",
                "route_id,direction_id,direction,direction_destination\n"
                "64,0,Northbound,Erdenheim\n64,1,Southbound,Center City\n",
            )
    return buffer.getvalue()


def decode_polyline(encoded, precision=5):
    """Reference decoder, to check the encoder round-trips."""
    points, index, lat, lon = [], 0, 0, 0
    while index < len(encoded):
        deltas = []
        for _ in range(2):
            shift = result = 0
            while True:
                byte = ord(encoded[index]) - 63
                index += 1
                result |= (byte & 0x1F) << shift
                shift += 5
                if byte < 0x20:
                    break
            deltas.append(~(result >> 1) if result & 1 else result >> 1)
        lat += deltas[0]
        lon += deltas[1]
        points.append((lat / 10 ** precision, lon / 10 ** precision))
    return points


class BuildTestCase(unittest.TestCase):
    def build(self, feed_bytes):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "bus.zip")
            with open(path, "wb") as handle:
                handle.write(feed_bytes)
            return build_septa_shapes.build(path, GENERATED)


class TestEncodePolyline(unittest.TestCase):
    def test_google_documented_example(self):
        points = [(38.5, -120.2), (40.7, -120.95), (43.252, -126.453)]
        self.assertEqual(
            build_septa_shapes.encode_polyline(points), "_p~iF~ps|U_ulLnnqC_mqNvxq`@"
        )

    def test_round_trips_through_a_decoder(self):
        points = [(39.95123, -75.16321), (39.95, -75.16), (40.0, -75.2)]
        decoded = decode_polyline(build_septa_shapes.encode_polyline(points))
        for got, want in zip(decoded, points):
            self.assertAlmostEqual(got[0], want[0], places=5)
            self.assertAlmostEqual(got[1], want[1], places=5)

    def test_empty(self):
        self.assertEqual(build_septa_shapes.encode_polyline([]), "")


class TestSimplify(unittest.TestCase):
    def test_drops_a_point_inside_tolerance(self):
        self.assertEqual(
            build_septa_shapes.simplify(SHAPES["A"], 5.0), [SHAPES["A"][0], SHAPES["A"][2]]
        )

    def test_keeps_a_corner(self):
        corner = [(39.95, -75.16), (39.96, -75.16), (39.96, -75.17)]
        self.assertEqual(build_septa_shapes.simplify(corner, 5.0), corner)

    def test_short_lines_unchanged(self):
        line = [(39.95, -75.16), (39.96, -75.16)]
        self.assertEqual(build_septa_shapes.simplify(line, 5.0), line)

    def test_loop_whose_ends_meet(self):
        loop = [(39.95, -75.16), (39.96, -75.16), (39.96, -75.17), (39.95, -75.16)]
        self.assertEqual(len(build_septa_shapes.simplify(loop, 5.0)), 4)

    def test_long_shape_does_not_recurse(self):
        zigzag = [(39.95 + i * 1e-4, -75.16 + (i % 2) * 1e-3) for i in range(5000)]
        self.assertEqual(len(build_septa_shapes.simplify(zigzag, 5.0)), 5000)


class TestBuild(BuildTestCase):
    def test_document_header(self):
        document = self.build(make_feed())
        self.assertEqual(document["v"], 1)
        self.assertEqual(document["gtfs_version"], "v202609271")
        self.assertEqual(document["generated"], "2026-10-18T06:00:00Z")

    def test_primary_is_the_most_used_shape_and_others_are_variants(self):
        north, south = self.build(make_feed())["routes"]["64"]
        self.assertEqual(north["dir"], 0)
        self.assertEqual(decode_polyline(north["primary"]), [SHAPES["A"][0], SHAPES["A"][2]])
        self.assertEqual([decode_polyline(v) for v in north["variants"]], [SHAPES["B"]])
        self.assertEqual(south["dir"], 1)
        self.assertEqual(decode_polyline(south["primary"]), SHAPES["C"])
        self.assertEqual(south["variants"], [])

    def test_tied_shapes_order_by_shape_id(self):
        extra = "64,1,t5,1,B\n"  # direction 1: C and B one trip each
        south = self.build(make_feed(extra))["routes"]["64"][1]
        self.assertEqual(decode_polyline(south["primary"]), SHAPES["B"])

    def test_identical_encodings_appear_once(self):
        shapes = dict(SHAPES, D=list(SHAPES["B"]))
        north = self.build(make_feed("64,1,t5,0,D\n", shapes=shapes))["routes"]["64"][0]
        self.assertEqual(len(north["variants"]), 1)

    def test_stops_in_route_order(self):
        north, south = self.build(make_feed())["routes"]["64"]
        self.assertEqual(north["stops"], ["s1", "s2", "s3"])
        self.assertEqual(south["stops"], ["s3"])

    def test_direction_names(self):
        north, south = self.build(make_feed())["routes"]["64"]
        self.assertEqual((north["name"], south["name"]), ("Northbound", "Southbound"))

    def test_missing_directions_file_means_empty_names(self):
        north, _ = self.build(make_feed(directions=False))["routes"]["64"]
        self.assertEqual(north["name"], "")

    def test_route_without_stops_gets_an_empty_list(self):
        self.assertEqual(self.build(make_feed())["routes"]["F0"][0]["stops"], [])

    def test_routes_follow_route_sort_order(self):
        routes = list(self.build(make_feed())["routes"])
        self.assertEqual(routes[:3], ["64", "F0", "F1"])

    def test_route_without_trips_is_left_out(self):
        feed = make_feed()
        with zipfile.ZipFile(io.BytesIO(feed)) as zf:
            files = {name: zf.read(name).decode() for name in zf.namelist()}
        files["routes.txt"] += "99,3,9999\n"
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as zf:
            for name, text in files.items():
                zf.writestr(name, text)
        self.assertNotIn("99", self.build(buffer.getvalue())["routes"])

    def test_trip_without_shape_is_ignored(self):
        document = self.build(make_feed("64,1,t6,0,\n"))
        self.assertEqual(len(document["routes"]["64"][0]["variants"]), 1)

    def test_unknown_shape_fails(self):
        with self.assertRaisesRegex(ValueError, "absent from shapes.txt"):
            self.build(make_feed("64,1,t7,0,NOPE\n"))

    def test_too_few_routes_with_shapes_fails(self):
        shapes = {k: v for k, v in SHAPES.items() if k != "FILLER"}
        feed = make_feed(shapes=shapes)
        with zipfile.ZipFile(io.BytesIO(feed)) as zf:
            files = {name: zf.read(name).decode() for name in zf.namelist()}
        files["trips.txt"] = "\n".join(
            line for line in files["trips.txt"].splitlines() if "FILLER" not in line
        ) + "\n"
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as zf:
            for name, text in files.items():
                zf.writestr(name, text)
        with self.assertRaisesRegex(ValueError, "sanity floor"):
            self.build(buffer.getvalue())


class TestOutput(BuildTestCase):
    def test_serialize_is_compact_json(self):
        payload = build_septa_shapes.serialize({"v": 1, "routes": {}})
        self.assertEqual(payload, b'{"v":1,"routes":{}}\n')

    def test_same_content_ignores_generated(self):
        a = self.build(make_feed())
        b = dict(a, generated="2027-01-01T00:00:00Z")
        self.assertTrue(build_septa_shapes.same_content(a, b))
        self.assertFalse(build_septa_shapes.same_content(a, dict(a, gtfs_version="v2")))

    def test_main_writes_the_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle = os.path.join(tmp, "bus.zip")
            with open(bundle, "wb") as handle:
                handle.write(make_feed())
            out = os.path.join(tmp, "out")
            self.assertEqual(
                build_septa_shapes.main(["--gtfs-zip", bundle, "--output-dir", out]), 0
            )
            with open(os.path.join(out, "septashapes.json"), encoding="utf-8") as handle:
                document = json.load(handle)
            self.assertEqual(document["v"], 1)
            self.assertIn("64", document["routes"])

    def test_main_compare(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = []
            for name, version in (("a", "v1"), ("b", "v1"), ("c", "v2")):
                path = os.path.join(tmp, f"{name}.json")
                with open(path, "w", encoding="utf-8") as handle:
                    json.dump({"v": 1, "gtfs_version": version, "generated": name}, handle)
                paths.append(path)
            self.assertEqual(build_septa_shapes.main(["--compare", paths[0], paths[1]]), 0)
            self.assertEqual(build_septa_shapes.main(["--compare", paths[0], paths[2]]), 1)


if __name__ == "__main__":
    unittest.main()
