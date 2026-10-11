"""Tests for the service alert sampler. Offline throughout."""

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
import urllib.error

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import gtfs_rt
    import sample_service_alerts as alerts
except ImportError as exc:  # pragma: no cover - exercised by the meta workflow
    # Same arrangement as the coverage sampler's tests: skipped where nothing
    # is installed, and the sampler workflow asserts the import separately.
    raise unittest.SkipTest(f"gtfs-realtime-bindings not installed: {exc}")

FEED_TIMESTAMP = 1791743783


def new_feed():
    feed = gtfs_rt.gtfs_realtime_pb2.FeedMessage()
    feed.header.gtfs_realtime_version = "2.0"
    feed.header.timestamp = FEED_TIMESTAMP
    return feed


def add_alert(feed, alert_id, header, description=None, *, routes=(),
              trips=(), language="en"):
    entity = feed.entity.add()
    entity.id = alert_id
    alert = entity.alert
    alert.header_text.translation.add(text=header, language=language)
    if description is not None:
        alert.description_text.translation.add(text=description,
                                               language=language)
    for route_id in routes:
        alert.informed_entity.add(route_id=route_id)
    for trip_id, route_id in trips:
        informed = alert.informed_entity.add()
        informed.trip.trip_id = trip_id
        if route_id is not None:
            informed.trip.route_id = route_id
    return entity


def summarize(feed):
    return {"alerts": alerts.summarize_alerts(feed)}


def detour(**overrides):
    record = {
        "route_direction": "SB",
        "reason": "Sink Hole ",
        "start_location": "17th & Diamond Sts",
        "end_location": "17th St btwn Jefferson & Master Sts ",
        "start_date_time": "9/29/2026   7:19 AM",
        "end_date_time": "10/29/2026   4:00 PM",
        "current_message": " 24/7 until 10/29/26 SB via 17th St L  - Diamond St",
    }
    record.update(overrides)
    return record


class SummarizeTest(unittest.TestCase):
    def test_alert_keeps_id_text_and_routes(self):
        feed = new_feed()
        add_alert(feed, "133350", "Shuttle Busing",
                  "Bus service replaces train service.", routes=["M1"])

        document = summarize(feed)

        self.assertEqual(document["alerts"], [{
            "id": "133350",
            "header": "Shuttle Busing",
            "description": "Bus service replaces train service.",
            "routes": ["M1"],
            "active_periods": [],
        }])

    def test_active_periods_keep_open_bounds(self):
        feed = new_feed()
        entity = add_alert(feed, "1", "Detour")
        entity.alert.active_period.add(start=100, end=200)
        entity.alert.active_period.add(start=300)

        (alert,) = summarize(feed)["alerts"]

        self.assertEqual(alert["active_periods"], [[100, 200], [300, None]])

    def test_effect_cause_and_severity_are_named(self):
        feed = new_feed()
        alert_pb = add_alert(feed, "D1", "Construction").alert
        Alert = gtfs_rt.gtfs_realtime_pb2.Alert
        alert_pb.effect = Alert.DETOUR
        alert_pb.cause = Alert.CONSTRUCTION
        alert_pb.severity_level = Alert.WARNING

        (alert,) = summarize(feed)["alerts"]

        self.assertEqual(alert["effect"], "DETOUR")
        self.assertEqual(alert["cause"], "CONSTRUCTION")
        self.assertEqual(alert["severity_level"], "WARNING")

    def test_unknown_enums_are_omitted(self):
        feed = new_feed()
        alert_pb = add_alert(feed, "1", "Notice").alert
        Alert = gtfs_rt.gtfs_realtime_pb2.Alert
        alert_pb.effect = Alert.UNKNOWN_EFFECT
        alert_pb.cause = Alert.UNKNOWN_CAUSE

        (alert,) = summarize(feed)["alerts"]

        self.assertNotIn("effect", alert)
        self.assertNotIn("cause", alert)

    def test_description_repeating_the_header_is_omitted(self):
        feed = new_feed()
        text = "Trip cancellation for trip 869197."
        add_alert(feed, "TU869197", text, text)

        (alert,) = summarize(feed)["alerts"]

        self.assertNotIn("description", alert)
        self.assertEqual(alert["header"], text)

    def test_missing_description_is_omitted(self):
        feed = new_feed()
        add_alert(feed, "1", "Header only")

        (alert,) = summarize(feed)["alerts"]

        self.assertNotIn("description", alert)

    def test_routes_are_distinct_and_sorted(self):
        feed = new_feed()
        add_alert(feed, "1", "Detour", "Details", routes=["57", "17", "57"])

        (alert,) = summarize(feed)["alerts"]

        self.assertEqual(alert["routes"], ["17", "57"])

    def test_route_named_through_a_trip_counts(self):
        feed = new_feed()
        add_alert(feed, "1", "Cancelled", trips=[("t1", "23"), ("t2", None)])

        (alert,) = summarize(feed)["alerts"]

        self.assertEqual(alert["routes"], ["23"])

    def test_alert_without_a_route_is_kept(self):
        feed = new_feed()
        add_alert(feed, "TU1", "Trip cancellation", trips=[("t1", None)])

        (alert,) = summarize(feed)["alerts"]

        self.assertEqual(alert["routes"], [])

    def test_english_translation_is_preferred(self):
        feed = new_feed()
        entity = add_alert(feed, "1", "Desvío", language="es")
        entity.alert.header_text.translation.add(text="Detour", language="en")

        (alert,) = summarize(feed)["alerts"]

        self.assertEqual(alert["header"], "Detour")

    def test_untagged_translation_counts_as_default(self):
        feed = new_feed()
        add_alert(feed, "1", "Detour", language="")

        (alert,) = summarize(feed)["alerts"]

        self.assertEqual(alert["header"], "Detour")

    def test_text_is_kept_verbatim(self):
        feed = new_feed()
        add_alert(feed, "1", "Stop moved",
                  "Use Washington Ave &amp; 3rd St.")

        (alert,) = summarize(feed)["alerts"]

        self.assertEqual(alert["description"],
                         "Use Washington Ave &amp; 3rd St.")

    def test_deleted_and_non_alert_entities_are_skipped(self):
        feed = new_feed()
        add_alert(feed, "kept", "Kept")
        add_alert(feed, "gone", "Gone").is_deleted = True
        feed.entity.add(id="vehicle").vehicle.trip.route_id = "17"

        ids = [alert["id"] for alert in summarize(feed)["alerts"]]

        self.assertEqual(ids, ["kept"])

    def test_alerts_are_ordered_by_id(self):
        feed = new_feed()
        for alert_id in ("b", "c", "a"):
            add_alert(feed, alert_id, alert_id)

        ids = [alert["id"] for alert in summarize(feed)["alerts"]]

        self.assertEqual(ids, ["a", "b", "c"])


class DetoursTest(unittest.TestCase):
    def test_records_are_kept_verbatim(self):
        (record,) = alerts.summarize_detours(
            [{"route_id": "2", "route_info": [detour()]}])

        self.assertEqual(record, {**detour(), "routes": ["2"]})

    def test_identical_detour_on_several_routes_is_recorded_once(self):
        listing = [
            {"route_id": "LUCYGO", "route_info": [detour()]},
            {"route_id": "LUCYGR", "route_info": [detour()]},
            {"route_id": "2", "route_info": [detour(route_direction="NB")]},
        ]

        records = alerts.summarize_detours(listing)

        self.assertEqual(sorted(r["routes"] for r in records),
                         [["2"], ["LUCYGO", "LUCYGR"]])

    def test_empty_listing_is_no_detours(self):
        self.assertEqual(alerts.summarize_detours([]), [])

    def test_unexpected_shape_is_an_error(self):
        for listing in ({"error": "down"}, [{"route_id": "2"}],
                        [{"route_id": "2", "route_info": ["x"]}]):
            with self.subTest(listing=listing):
                with self.assertRaises(ValueError):
                    alerts.summarize_detours(listing)

    def test_failed_fetch_records_none(self):
        def broken(*_args, **_kwargs):
            raise urllib.error.HTTPError("u", 500, "down", {}, None)

        original = alerts.fetching.get_bytes
        alerts.fetching.get_bytes = broken
        try:
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertIsNone(alerts.fetch_detours("u"))
        finally:
            alerts.fetching.get_bytes = original


class MainTest(unittest.TestCase):
    def run_main(self, body, listing=()):
        with tempfile.TemporaryDirectory() as tmp:
            pb = os.path.join(tmp, "alerts.pb")
            detours_json = os.path.join(tmp, "detours.json")
            out = os.path.join(tmp, "out", "alerts.json")
            with open(pb, "wb") as handle:
                handle.write(body)
            with open(detours_json, "w", encoding="utf-8") as handle:
                json.dump(list(listing), handle)
            with contextlib.redirect_stdout(io.StringIO()), \
                    contextlib.redirect_stderr(io.StringIO()):
                code = alerts.main(["--pb", pb, "--detours-json",
                                    detours_json, "--output", out])
            document = None
            if os.path.exists(out):
                with open(out, encoding="utf-8") as handle:
                    document = json.load(handle)
            return code, document

    def test_writes_the_snapshot(self):
        feed = new_feed()
        add_alert(feed, "1", "Detour", routes=["17"])

        code, document = self.run_main(
            feed.SerializeToString(),
            [{"route_id": "2", "route_info": [detour()]}])

        self.assertEqual(code, 0)
        self.assertEqual(document["feed_timestamp"], FEED_TIMESTAMP)
        self.assertEqual(document["alerts"][0]["routes"], ["17"])
        self.assertEqual(document["detours"][0]["routes"], ["2"])

    def test_empty_feed_writes_nothing(self):
        code, document = self.run_main(new_feed().SerializeToString())

        self.assertEqual(code, 1)
        self.assertIsNone(document)

    def test_corrupt_feed_writes_nothing(self):
        code, document = self.run_main(b"\xff\xff\xff")

        self.assertEqual(code, 1)
        self.assertIsNone(document)


if __name__ == "__main__":
    unittest.main()
