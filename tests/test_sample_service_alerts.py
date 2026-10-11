"""Tests for the service alert archiver. Offline throughout."""

import datetime
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import gtfs_rt
    import sample_service_alerts as alerts
except ImportError as exc:  # pragma: no cover - exercised by the meta workflow
    # Same arrangement as the coverage sampler's tests: skipped where nothing
    # is installed, and the sampler workflow asserts the import separately.
    raise unittest.SkipTest(f"gtfs-realtime-bindings not installed: {exc}")

SAMPLED_AT = datetime.datetime(2026, 10, 11, 14, 17, 5,
                               tzinfo=datetime.timezone.utc)
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
    return alerts.summarize(feed, sampled_at=SAMPLED_AT)


class SummarizeTest(unittest.TestCase):
    def test_alert_keeps_id_text_and_routes(self):
        feed = new_feed()
        add_alert(feed, "133350", "Shuttle Busing",
                  "Bus service replaces train service.", routes=["M1"])

        document = summarize(feed)

        self.assertEqual(document["sampled_at"], "2026-10-11T14:17:05Z")
        self.assertEqual(document["feed_timestamp"], FEED_TIMESTAMP)
        self.assertEqual(document["alerts"], [{
            "id": "133350",
            "header": "Shuttle Busing",
            "description": "Bus service replaces train service.",
            "routes": ["M1"],
        }])

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


class MainTest(unittest.TestCase):
    def run_main(self, body):
        with tempfile.TemporaryDirectory() as tmp:
            pb = os.path.join(tmp, "alerts.pb")
            out = os.path.join(tmp, "out", "alerts.json")
            with open(pb, "wb") as handle:
                handle.write(body)
            code = alerts.main(["--pb", pb, "--output", out])
            document = None
            if os.path.exists(out):
                with open(out, encoding="utf-8") as handle:
                    document = json.load(handle)
            return code, document

    def test_writes_the_snapshot(self):
        feed = new_feed()
        add_alert(feed, "1", "Detour", routes=["17"])

        code, document = self.run_main(feed.SerializeToString())

        self.assertEqual(code, 0)
        self.assertEqual(document["alerts"][0]["routes"], ["17"])

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
