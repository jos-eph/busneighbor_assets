"""Tests for the real-time coverage sampler.

Offline throughout. Fixtures are built with the bindings themselves — set the
fields by name, serialize — rather than hand-assembled from the wire format,
which is the whole reason this repository uses gtfs-realtime-bindings.

Two tests you might expect are deliberately absent: unknown field numbers and
unknown wire types are protobuf's contract, not ours, and asserting on them
would only test the library. Forward compatibility with SEPTA adding fields
comes free, since unknown fields are preserved rather than errors.
"""

import datetime
import io
import json
import os
import sys
import tempfile
import unittest
import urllib.error
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fetching
import gtfs_static

try:
    import gtfs_rt
    import sample_realtime_coverage as sampler
except ImportError as exc:  # pragma: no cover - exercised by the meta workflow
    # The release workflow installs nothing and runs this same directory, so
    # these tests skip there rather than failing it. The sampler workflow
    # installs requirements.txt and asserts the import separately, so a broken
    # install cannot hide behind this skip.
    raise unittest.SkipTest(f"gtfs-realtime-bindings not installed: {exc}")

SAMPLED_AT = datetime.datetime(2026, 9, 1, 21, 2, 53,
                               tzinfo=datetime.timezone.utc)
FEED_TIMESTAMP = 1788296573

PHILADELPHIA = (39.9526, -75.1652)


def make_feed(vehicles=(), *, timestamp=FEED_TIMESTAMP, extra_entities=0):
    """Serialize a FeedMessage from (route_id, lat, lon) triples.

    A lat/lon of None omits the position submessage entirely. Passing
    extra_entities adds entities carrying no vehicle at all, the way a feed
    mixing trip updates into the same message would.

    gtfs_realtime_version is required in proto2: omitting it makes
    SerializeToString raise an EncodeError that reads nothing like the bug you
    would be chasing.
    """
    feed = gtfs_rt.gtfs_realtime_pb2.FeedMessage()
    feed.header.gtfs_realtime_version = "2.0"
    feed.header.timestamp = timestamp

    for index, (route_id, lat, lon) in enumerate(vehicles):
        entity = feed.entity.add()
        entity.id = f"v{index}"
        if route_id is not None:
            entity.vehicle.trip.route_id = route_id
        else:
            # Touch the trip submessage so the vehicle exists without a route.
            entity.vehicle.trip.trip_id = f"t{index}"
        if lat is not None:
            entity.vehicle.position.latitude = lat
            entity.vehicle.position.longitude = lon

    for index in range(extra_entities):
        entity = feed.entity.add()
        entity.id = f"other{index}"

    return feed.SerializeToString()


def tracked(route_id):
    return (route_id, *PHILADELPHIA)


def summarize(body, feed_url="test://feed"):
    return sampler.summarize(
        gtfs_rt.parse_feed(body),
        feed_url=feed_url,
        body_bytes=len(body),
        sampled_at=SAMPLED_AT,
    )


class SummarizeTest(unittest.TestCase):
    def test_counts_positions_per_route(self):
        body = make_feed([tracked("47"), tracked("23"), tracked("47")])
        document = summarize(body)
        self.assertEqual(document["positions_by_route"], {"23": 1, "47": 2})
        self.assertEqual(document["distinct_routes"], 2)
        self.assertEqual(document["entities"], 3)
        self.assertEqual(document["entities_with_valid_position"], 3)

    def test_entity_without_position_is_excluded_but_still_counted(self):
        body = make_feed([tracked("47"), ("L1", None, None)])
        document = summarize(body)
        self.assertEqual(document["positions_by_route"], {"47": 1})
        self.assertEqual(document["entities"], 2)
        self.assertEqual(document["entities_with_valid_position"], 1)

    def test_null_island_is_excluded(self):
        body = make_feed([tracked("47"), ("B1", 0.0, 0.0)])
        document = summarize(body)
        self.assertEqual(document["positions_by_route"], {"47": 1})
        self.assertEqual(document["entities_with_valid_position"], 1)

    def test_missing_route_id_counts_toward_no_route(self):
        body = make_feed([tracked("47"), (None, *PHILADELPHIA)])
        document = summarize(body)
        self.assertEqual(document["positions_by_route"], {"47": 1})
        self.assertEqual(document["distinct_routes"], 1)
        # It had a real position, so it is not hidden from the totals — the gap
        # against positions_by_route is the visible evidence of it.
        self.assertEqual(document["entities_with_valid_position"], 2)

    def test_empty_route_id_counts_toward_no_route(self):
        body = make_feed([tracked("47"), ("", *PHILADELPHIA)])
        document = summarize(body)
        self.assertEqual(document["positions_by_route"], {"47": 1})
        self.assertEqual(document["distinct_routes"], 1)

    def test_entity_without_vehicle_is_counted_but_not_measured(self):
        body = make_feed([tracked("47")], extra_entities=2)
        document = summarize(body)
        self.assertEqual(document["entities"], 3)
        self.assertEqual(document["entities_with_valid_position"], 1)

    def test_carries_feed_timestamp_and_shape(self):
        body = make_feed([tracked("47")])
        document = summarize(body, feed_url="test://septa")
        self.assertEqual(document["feed_timestamp"], FEED_TIMESTAMP)
        self.assertEqual(document["sampled_at"], "2026-09-01T21:02:53Z")
        self.assertEqual(document["feed_url"], "test://septa")
        self.assertEqual(document["bytes"], len(body))

    def test_truncated_buffer_raises(self):
        body = make_feed([tracked(str(n)) for n in range(40)])
        with self.assertRaises(gtfs_rt.DecodeError):
            gtfs_rt.parse_feed(body[: len(body) // 2])


class OutputTest(unittest.TestCase):
    def test_output_is_byte_stable_and_key_sorted(self):
        body = make_feed([tracked("47"), tracked("23"), tracked("G1")])
        with tempfile.TemporaryDirectory() as tmp:
            first = os.path.join(tmp, "a.json")
            second = os.path.join(tmp, "b", "c.json")
            sampler.write_sample(summarize(body), first)
            sampler.write_sample(summarize(body), second)
            with open(first, "rb") as a, open(second, "rb") as b:
                self.assertEqual(a.read(), b.read())
            with open(first, encoding="utf-8") as handle:
                text = handle.read()

        self.assertTrue(text.endswith("\n"))
        keys = list(json.loads(text))
        self.assertEqual(keys, sorted(keys))
        routes = list(json.loads(text)["positions_by_route"])
        self.assertEqual(routes, sorted(routes))


class PositionsTest(unittest.TestCase):
    def test_fields_and_row_line_up(self):
        feed = gtfs_rt.gtfs_realtime_pb2.FeedMessage()
        feed.header.gtfs_realtime_version = "2.0"
        feed.header.timestamp = FEED_TIMESTAMP
        vehicle = feed.entity.add(id="3641").vehicle
        vehicle.trip.trip_id = "879622"
        vehicle.trip.route_id = "42"
        vehicle.trip.direction_id = 0
        vehicle.position.latitude = 39.950264
        vehicle.position.longitude = -75.199646
        vehicle.position.bearing = 196.79
        vehicle.position.speed = 8.11824608
        vehicle.timestamp = 1791746100
        vehicle.stop_id = "21435"
        vehicle.current_stop_sequence = 26
        vehicle.current_status = (
            gtfs_rt.gtfs_realtime_pb2.VehiclePosition.IN_TRANSIT_TO)
        vehicle.vehicle.id = "3641"

        document = sampler.positions_snapshot(feed, sampled_at=SAMPLED_AT)

        self.assertEqual(document["sampled_at"], "2026-09-01T21:02:53Z")
        self.assertEqual(document["feed_timestamp"], FEED_TIMESTAMP)
        (row,) = document["vehicles"]
        record = dict(zip(document["fields"], row))
        self.assertEqual(record, {
            "vehicle_id": "3641", "route_id": "42", "trip_id": "879622",
            "direction_id": 0, "lat": 39.950264, "lon": -75.199646,
            "bearing": 196.8, "speed": 8.12, "timestamp": 1791746100,
            "stop_id": "21435", "current_stop_sequence": 26,
            "current_status": "IN_TRANSIT_TO",
            "direction": None, "trip_headsign": None, "stop_name": None,
        })

    def test_names_come_from_the_static_bundle(self):
        feed = gtfs_rt.gtfs_realtime_pb2.FeedMessage()
        feed.header.gtfs_realtime_version = "2.0"
        vehicle = feed.entity.add(id="3025").vehicle
        vehicle.trip.trip_id = "879705"
        vehicle.trip.route_id = "42"
        vehicle.trip.direction_id = 1
        vehicle.position.latitude, vehicle.position.longitude = PHILADELPHIA
        vehicle.stop_id = "311"
        names = gtfs_static.Names(
            stops={"311": "Pine St & 3rd St"},
            headsigns={"879705": "Wycombe"},
            directions={("42", "1"): "Westbound"})

        document = sampler.positions_snapshot(feed, sampled_at=SAMPLED_AT,
                                              names=names)

        record = dict(zip(document["fields"], document["vehicles"][0]))
        self.assertEqual(
            (record["direction"], record["trip_headsign"], record["stop_name"]),
            ("Westbound", "Wycombe", "Pine St & 3rd St"))

    def test_unset_fields_are_null_not_zero(self):
        feed = gtfs_rt.parse_feed(make_feed([(None, *PHILADELPHIA)]))

        document = sampler.positions_snapshot(feed, sampled_at=SAMPLED_AT)

        record = dict(zip(document["fields"], document["vehicles"][0]))
        for field in ("vehicle_id", "route_id", "direction_id", "bearing",
                      "speed", "timestamp", "stop_id",
                      "current_stop_sequence", "current_status"):
            self.assertIsNone(record[field], field)

    def test_invalid_positions_and_non_vehicles_are_left_out(self):
        feed = gtfs_rt.parse_feed(make_feed(
            [tracked("17"), ("23", None, None), ("47", 0.0, 0.0)],
            extra_entities=2))

        document = sampler.positions_snapshot(feed, sampled_at=SAMPLED_AT)

        self.assertEqual(len(document["vehicles"]), 1)


class MainTest(unittest.TestCase):
    def _run(self, argv):
        stdout, sys.stdout = sys.stdout, io.StringIO()
        stderr, sys.stderr = sys.stderr, io.StringIO()
        try:
            code = sampler.main(argv, sleep=lambda _: None)
            return code, sys.stdout.getvalue()
        finally:
            sys.stdout, sys.stderr = stdout, stderr

    def test_reads_a_local_file_and_prints_the_utc_date(self):
        with tempfile.TemporaryDirectory() as tmp:
            pb = os.path.join(tmp, "feed.pb")
            with open(pb, "wb") as handle:
                handle.write(make_feed([tracked("47"), tracked("23")]))
            out = os.path.join(tmp, "out", "sample.json")
            code, printed = self._run(["--pb", pb, "--output", out])

            self.assertEqual(code, 0)
            self.assertTrue(os.path.exists(out))
            with open(out, encoding="utf-8") as handle:
                document = json.load(handle)
            self.assertEqual(document["positions_by_route"], {"23": 1, "47": 1})
            self.assertEqual(printed.strip(), document["sampled_at"][:10])

    def test_positions_come_from_the_same_fetch(self):
        with tempfile.TemporaryDirectory() as tmp:
            pb = os.path.join(tmp, "feed.pb")
            with open(pb, "wb") as handle:
                handle.write(make_feed([tracked("47"), tracked("23")]))
            out = os.path.join(tmp, "sample.json")
            positions = os.path.join(tmp, "out", "positions.json")
            code, _ = self._run(["--pb", pb, "--output", out,
                                 "--positions-output", positions])

            self.assertEqual(code, 0)
            with open(out, encoding="utf-8") as handle:
                sample = json.load(handle)
            with open(positions, encoding="utf-8") as handle:
                snapshot = json.load(handle)
            self.assertEqual(snapshot["sampled_at"], sample["sampled_at"])
            self.assertEqual(len(snapshot["vehicles"]), 2)

    def test_positions_are_named_from_a_bundle(self):
        with tempfile.TemporaryDirectory() as tmp:
            pb = os.path.join(tmp, "feed.pb")
            with open(pb, "wb") as handle:
                handle.write(make_feed([tracked("47")]))
            bundle = os.path.join(tmp, "bus.zip")
            with zipfile.ZipFile(bundle, "w") as feed_zip:
                feed_zip.writestr("routes.txt", "route_id\n47\n")
                feed_zip.writestr("stops.txt", "stop_id,stop_name\n")
                feed_zip.writestr("trips.txt", "trip_id,trip_headsign\n")
            positions = os.path.join(tmp, "positions.json")
            code, _ = self._run(["--pb", pb, "--output",
                                 os.path.join(tmp, "sample.json"),
                                 "--positions-output", positions,
                                 "--gtfs-bundle", bundle])

            self.assertEqual(code, 0)
            with open(positions, encoding="utf-8") as handle:
                self.assertIn("stop_name", json.load(handle)["fields"])

    def test_an_unreadable_bundle_costs_names_not_the_sample(self):
        with tempfile.TemporaryDirectory() as tmp:
            pb = os.path.join(tmp, "feed.pb")
            with open(pb, "wb") as handle:
                handle.write(make_feed([tracked("47")]))
            bundle = os.path.join(tmp, "broken.zip")
            with open(bundle, "wb") as handle:
                handle.write(b"not a zip")
            positions = os.path.join(tmp, "positions.json")
            code, _ = self._run(["--pb", pb, "--output",
                                 os.path.join(tmp, "sample.json"),
                                 "--positions-output", positions,
                                 "--gtfs-bundle", bundle])

            self.assertEqual(code, 0)
            with open(positions, encoding="utf-8") as handle:
                self.assertEqual(len(json.load(handle)["vehicles"]), 1)

    def test_positions_are_optional(self):
        with tempfile.TemporaryDirectory() as tmp:
            pb = os.path.join(tmp, "feed.pb")
            with open(pb, "wb") as handle:
                handle.write(make_feed([tracked("47")]))
            code, _ = self._run(["--pb", pb, "--output",
                                 os.path.join(tmp, "sample.json")])

            self.assertEqual(code, 0)
            self.assertEqual(sorted(os.listdir(tmp)),
                             ["feed.pb", "sample.json"])

    def test_empty_feed_exits_non_zero_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            pb = os.path.join(tmp, "feed.pb")
            with open(pb, "wb") as handle:
                handle.write(make_feed([]))
            out = os.path.join(tmp, "sample.json")
            code, _ = self._run(["--pb", pb, "--output", out])

            self.assertEqual(code, 1)
            self.assertFalse(os.path.exists(out))

    def test_unparseable_feed_exits_non_zero_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            pb = os.path.join(tmp, "feed.pb")
            body = make_feed([tracked(str(n)) for n in range(40)])
            with open(pb, "wb") as handle:
                handle.write(body[: len(body) // 2])
            out = os.path.join(tmp, "sample.json")
            code, _ = self._run(["--pb", pb, "--output", out])

            self.assertEqual(code, 1)
            self.assertFalse(os.path.exists(out))

    def test_a_quiet_hour_is_recorded_not_rejected(self):
        """Few routes at 04:00 is the correct answer, not a failure."""
        with tempfile.TemporaryDirectory() as tmp:
            pb = os.path.join(tmp, "feed.pb")
            with open(pb, "wb") as handle:
                handle.write(make_feed([tracked("L1_OWL")]))
            out = os.path.join(tmp, "sample.json")
            code, _ = self._run(["--pb", pb, "--output", out])

            self.assertEqual(code, 0)
            with open(out, encoding="utf-8") as handle:
                self.assertEqual(json.load(handle)["distinct_routes"], 1)


class FetchingTest(unittest.TestCase):
    def setUp(self):
        # with_retries narrates each attempt to stderr, which is right in a
        # workflow log and noise in a test run.
        self._stderr, sys.stderr = sys.stderr, io.StringIO()
        self.addCleanup(lambda: setattr(sys, "stderr", self._stderr))

    def test_server_error_is_retried(self):
        attempts = []

        def flaky():
            attempts.append(1)
            if len(attempts) < 3:
                raise urllib.error.HTTPError("u", 503, "busy", {}, None)
            return b"ok"

        self.assertEqual(
            fetching.with_retries(flaky, "GET", sleep=lambda _: None), b"ok")
        self.assertEqual(len(attempts), 3)

    def test_client_error_is_not_retried(self):
        """A client error will not fix itself. Retrying one costs minutes and
        then reports a misleading network failure."""
        attempts = []

        def forbidden():
            attempts.append(1)
            raise urllib.error.HTTPError("u", 403, "Forbidden", {}, None)

        with self.assertRaises(urllib.error.HTTPError):
            fetching.with_retries(forbidden, "GET", sleep=lambda _: None)
        self.assertEqual(len(attempts), 1)

    def test_network_error_is_retried_then_raised(self):
        attempts = []

        def down():
            attempts.append(1)
            raise urllib.error.URLError("no route to host")

        with self.assertRaises(urllib.error.URLError):
            fetching.with_retries(down, "GET", sleep=lambda _: None)
        self.assertEqual(len(attempts), fetching.ATTEMPTS)

    def test_request_carries_an_explicit_user_agent(self):
        self.assertNotIn("urllib", gtfs_rt.FEED_USER_AGENT)


if __name__ == "__main__":
    unittest.main()
