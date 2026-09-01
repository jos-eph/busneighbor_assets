"""Tests for the coverage aggregator.

Offline throughout, from fixture directories built in tmpdirs. The aggregator
does no network I/O by design, so nothing here needs a stub.

Stdlib-only, like the script: samples are JSON by the time they reach the
aggregator, so these tests run in the release workflow too.
"""

import datetime
import io
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import aggregate_realtime_coverage as agg

GENERATED_AT = datetime.datetime(2026, 9, 29, 1, 47, 12,
                                 tzinfo=datetime.timezone.utc)
FEED_VERSION = "v202608233"
# route_sort_order, deliberately not alphabetical, and long enough that two
# denied routes stay under the 20% blast-radius cap the way they do in the real
# feed (4 of 175). A five-route fixture would trip that guard in every test.
ROUTE_LIST = ["T1", "T2", "T3", "T4", "T5", "G1", "M1", "D1", "D2", "47",
              "23", "63", "42", "18", "3", "BLVDDIR", "LUCYGO", "K",
              "L1", "B1"]
UNTRACKED = ("L1", "B1")
ALL_TRACKED = {r: 5 for r in ROUTE_LIST if r not in UNTRACKED}
FEED_META = {"start_date": "20260823", "end_date": "20270220",
             "version": FEED_VERSION}


def write_sample(directory, name, *, sampled_at, feed_timestamp, routes):
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, name)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump({
            "sampled_at": sampled_at,
            "feed_timestamp": feed_timestamp,
            "feed_url": "test://feed",
            "bytes": 1000,
            "entities": sum(routes.values()),
            "entities_with_valid_position": sum(routes.values()),
            "distinct_routes": len(routes),
            "positions_by_route": routes,
        }, handle)
    return path


def a_day(directory, date="2026-09-01", count=4, routes=None):
    """count samples on one UTC day, each with a distinct feed_timestamp."""
    routes = routes if routes is not None else dict(ALL_TRACKED)
    for index in range(count):
        write_sample(directory, f"s{index}.json",
                     sampled_at=f"{date}T{2 + index * 3:02d}:17:09Z",
                     feed_timestamp=1788000000 + index * 10800,
                     routes=routes)
    return directory


def write_septameta(path, route_list=ROUTE_LIST, meta=None):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump({"meta": meta or FEED_META,
                   "buses": {"route_list": list(route_list)}}, handle)
    return path


def state_with(days, window_days=28, min_samples=4):
    return {
        "window_days": window_days,
        "min_samples_per_day": min_samples,
        "days": days,
    }


def day_entry(routes, samples=8, feed_version=FEED_VERSION):
    return {"samples": samples, "feed_version": feed_version,
            "positions_by_route": dict(routes)}


class DailySummaryTest(unittest.TestCase):
    def test_sums_positions_across_samples(self):
        with tempfile.TemporaryDirectory() as tmp:
            a_day(tmp, count=3, routes={"47": 10, "23": 5})
            summary, dropped = agg.daily_summary(agg.load_samples(tmp))
        self.assertEqual(summary["positions_by_route"], {"23": 15, "47": 30})
        self.assertEqual(summary["samples"], 3)
        self.assertEqual(summary["distinct_routes"], 2)
        self.assertEqual(dropped, 0)

    def test_duplicate_feed_timestamp_is_dropped_and_counted(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_sample(tmp, "a.json", sampled_at="2026-09-01T02:17:09Z",
                         feed_timestamp=1788000000, routes={"47": 10})
            write_sample(tmp, "b.json", sampled_at="2026-09-01T05:17:09Z",
                         feed_timestamp=1788000000, routes={"47": 10})
            write_sample(tmp, "c.json", sampled_at="2026-09-01T08:17:09Z",
                         feed_timestamp=1788010000, routes={"47": 4})
            summary, dropped = agg.daily_summary(agg.load_samples(tmp))

        # The frozen feed is counted once, not twice.
        self.assertEqual(summary["positions_by_route"], {"47": 14})
        self.assertEqual(summary["samples"], 2)
        self.assertEqual(summary["samples_dropped_duplicate_feed"], 1)
        self.assertEqual(dropped, 1)

    def test_records_the_days_first_and_last_sample(self):
        with tempfile.TemporaryDirectory() as tmp:
            a_day(tmp, count=4)
            summary, _ = agg.daily_summary(agg.load_samples(tmp))
        self.assertEqual(summary["first_sampled_at"], "2026-09-01T02:17:09Z")
        self.assertEqual(summary["last_sampled_at"], "2026-09-01T11:17:09Z")

    def test_samples_spanning_two_days_need_an_explicit_date(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_sample(tmp, "a.json", sampled_at="2026-09-01T23:17:09Z",
                         feed_timestamp=1788000000, routes={"47": 1})
            write_sample(tmp, "b.json", sampled_at="2026-09-02T02:17:09Z",
                         feed_timestamp=1788010000, routes={"47": 2})
            samples = agg.load_samples(tmp)
            with self.assertRaises(ValueError):
                agg.daily_summary(samples)
            summary, _ = agg.daily_summary(samples, "2026-09-02")
        self.assertEqual(summary["positions_by_route"], {"47": 2})


class StateTest(unittest.TestCase):
    def test_rerunning_a_date_replaces_rather_than_doubles(self):
        summary = {"date": "2026-09-01", "samples": 8,
                   "positions_by_route": {"47": 100}}
        state = agg.empty_state(28, 4)
        state = agg.fold_into_state(state, summary, FEED_VERSION, 28)
        state = agg.fold_into_state(state, summary, FEED_VERSION, 28)
        self.assertEqual(state["days"]["2026-09-01"]["positions_by_route"],
                         {"47": 100})
        self.assertEqual(len(state["days"]), 1)

    def test_a_twenty_ninth_day_evicts_the_oldest(self):
        state = agg.empty_state(28, 4)
        base = datetime.date(2026, 9, 1)
        for offset in range(29):
            date = (base + datetime.timedelta(days=offset)).isoformat()
            state = agg.fold_into_state(
                state, {"date": date, "samples": 8, "positions_by_route": {"47": 1}},
                FEED_VERSION, 28)

        self.assertEqual(len(state["days"]), 28)
        self.assertNotIn("2026-09-01", state["days"])
        self.assertIn("2026-09-02", state["days"])
        self.assertIn("2026-09-29", state["days"])

    def test_days_are_stored_in_date_order(self):
        state = agg.empty_state(28, 4)
        for date in ("2026-09-03", "2026-09-01", "2026-09-02"):
            state = agg.fold_into_state(
                state, {"date": date, "samples": 8, "positions_by_route": {}},
                FEED_VERSION, 28)
        self.assertEqual(list(state["days"]), sorted(state["days"]))


class ProjectionTest(unittest.TestCase):
    def _coverage(self, days, route_list=ROUTE_LIST):
        return agg.project(state_with(days), route_list, FEED_META,
                           generated_at=GENERATED_AT)

    def test_a_route_never_seen_is_present_with_zeros(self):
        coverage = self._coverage({"2026-09-01": day_entry({"47": 10})})
        self.assertEqual(coverage["vehicle_positions"]["routes"]["L1"],
                         {"days_seen": 0, "last_seen": None, "positions": 0})

    def test_days_seen_counts_days_not_samples(self):
        coverage = self._coverage({
            "2026-09-01": day_entry({"47": 100}),
            "2026-09-02": day_entry({"47": 100}),
        })
        route = coverage["vehicle_positions"]["routes"]["47"]
        self.assertEqual(route["days_seen"], 2)
        self.assertEqual(route["positions"], 200)
        self.assertEqual(route["last_seen"], "2026-09-02")

    def test_no_vehicle_positions_follows_route_sort_order(self):
        # L1 and B1 are never seen. Alphabetically that is ["B1", "L1"];
        # route_sort_order puts L1 first, and route_list is the authority.
        coverage = self._coverage({"2026-09-01": day_entry(ALL_TRACKED)})
        self.assertEqual(
            coverage["vehicle_positions"]["no_vehicle_positions"], ["L1", "B1"])

    def test_unmatched_route_ids_are_reported_not_counted(self):
        coverage = self._coverage(
            {"2026-09-01": day_entry({"47": 5, "B1 OWL": 3})})
        self.assertEqual(coverage["unmatched_route_ids"], ["B1 OWL"])
        self.assertNotIn("B1 OWL", coverage["vehicle_positions"]["routes"])

    def test_carries_window_shape_and_feed_meta(self):
        coverage = self._coverage({
            "2026-09-01": day_entry({"47": 1}, samples=8),
            "2026-09-02": day_entry({"47": 1}, samples=6),
        })
        self.assertEqual(coverage["observed_through"], "2026-09-02")
        self.assertEqual(coverage["days_observed"], 2)
        self.assertEqual(coverage["samples"], 14)
        self.assertEqual(coverage["feed_meta"]["version"], FEED_VERSION)
        self.assertEqual(coverage["generated_at"], "2026-09-29T01:47:12Z")


class GuardTest(unittest.TestCase):
    def _guards(self, days, route_list=ROUTE_LIST, feed_meta=FEED_META,
                min_days=1, max_fraction=0.20):
        state = state_with(days)
        coverage = agg.project(state, route_list, feed_meta,
                               generated_at=GENERATED_AT)
        return agg.check_guards(coverage, state, route_list, feed_meta,
                                min_days_observed=min_days,
                                max_deny_fraction=max_fraction)

    def _full_window(self, routes, days=10, feed_version=FEED_VERSION):
        base = datetime.date(2026, 9, 1)
        return {(base + datetime.timedelta(days=n)).isoformat():
                day_entry(routes, feed_version=feed_version)
                for n in range(days)}

    def test_all_clear_when_nothing_is_wrong(self):
        self.assertEqual(
            self._guards(self._full_window(ALL_TRACKED), min_days=7), [])

    def test_window_depth_guard_trips_on_a_shallow_window(self):
        failures = self._guards(self._full_window(ALL_TRACKED, days=3),
                                min_days=7)
        self.assertEqual(len(failures), 1)
        self.assertIn("window depth", failures[0])

    def test_blast_radius_guard_trips_when_too_much_is_denied(self):
        # Only T1 seen: four of five routes would be denied, far above 20%.
        failures = self._guards(self._full_window({"T1": 1}), min_days=7)
        self.assertEqual(len(failures), 1)
        self.assertIn("blast radius", failures[0])

    def test_feed_agreement_guard_trips_when_the_window_spans_versions(self):
        days = self._full_window(ALL_TRACKED)
        days["2026-09-01"] = day_entry(ALL_TRACKED, feed_version="v202601011")
        failures = self._guards(days, min_days=7)
        self.assertEqual(len(failures), 1)
        self.assertIn("feed agreement", failures[0])


class MainTest(unittest.TestCase):
    def _run(self, tmp, extra=(), samples_dir=None, state=None):
        stdout, sys.stdout = sys.stdout, io.StringIO()
        stderr, sys.stderr = sys.stderr, io.StringIO()
        try:
            argv = [
                "--samples-dir", samples_dir or os.path.join(tmp, "samples"),
                "--septameta", write_septameta(os.path.join(tmp, "septameta.json")),
                "--output-dir", os.path.join(tmp, "out"),
                *extra,
            ]
            if state:
                argv += ["--state", state]
            code = agg.main(argv, now=lambda: GENERATED_AT)
            return code, sys.stdout.getvalue()
        finally:
            sys.stdout, sys.stderr = stdout, stderr

    def _out(self, tmp, name):
        with open(os.path.join(tmp, "out", name), encoding="utf-8") as handle:
            return json.load(handle)

    def test_writes_all_four_documents(self):
        with tempfile.TemporaryDirectory() as tmp:
            a_day(os.path.join(tmp, "samples"), count=8)
            code, _ = self._run(tmp, ["--min-days-observed", "1"])

            self.assertEqual(code, agg.EXIT_OK)
            for name in ("septacoverage_2026-09-01.json",
                         "septacoverage_state.json",
                         "septacoverage.json",
                         "realtime_overrides.proposed.json"):
                self.assertTrue(
                    os.path.exists(os.path.join(tmp, "out", name)), name)

    def test_never_writes_realtime_overrides_itself(self):
        """Proposing and applying are separate. The workflow applies."""
        with tempfile.TemporaryDirectory() as tmp:
            a_day(os.path.join(tmp, "samples"), count=8)
            self._run(tmp, ["--min-days-observed", "1"])
            self.assertFalse(
                os.path.exists(os.path.join(tmp, "out",
                                            "realtime_overrides.json")))

    def test_a_thin_day_is_not_recorded_and_exits_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            a_day(os.path.join(tmp, "samples"), count=3)
            code, _ = self._run(tmp)

            self.assertEqual(code, agg.EXIT_OK)
            self.assertFalse(os.path.exists(
                os.path.join(tmp, "out", "septacoverage_state.json")))
            # The summary is still written, so the thin day leaves a trace.
            self.assertTrue(os.path.exists(
                os.path.join(tmp, "out", "septacoverage_2026-09-01.json")))

    def test_a_tripped_guard_exits_two_but_still_publishes(self):
        with tempfile.TemporaryDirectory() as tmp:
            a_day(os.path.join(tmp, "samples"), count=8, routes={"T1": 5})
            code, _ = self._run(tmp, ["--min-days-observed", "7"])

            self.assertEqual(code, agg.EXIT_GUARD_TRIPPED)
            # The evidence is still true and still published; only acting on it
            # is suspended.
            self.assertTrue(os.path.exists(
                os.path.join(tmp, "out", "septacoverage.json")))
            self.assertTrue(os.path.exists(
                os.path.join(tmp, "out", "realtime_overrides.proposed.json")))

    def test_missing_samples_directory_is_a_hard_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, _ = self._run(tmp, samples_dir=os.path.join(tmp, "absent"))
            self.assertEqual(code, agg.EXIT_FAILED)

    def test_proposal_carries_the_window_it_was_measured_over(self):
        with tempfile.TemporaryDirectory() as tmp:
            a_day(os.path.join(tmp, "samples"), count=8)
            self._run(tmp, ["--min-days-observed", "1"])
            proposal = self._out(tmp, "realtime_overrides.proposed.json")

        self.assertEqual(proposal["source"], "observed")
        self.assertEqual(proposal["observed_through"], "2026-09-01")
        self.assertEqual(proposal["days_observed"], 1)
        self.assertEqual(proposal["no_vehicle_positions"], ["L1", "B1"])

    def test_state_carries_forward_across_two_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = os.path.join(tmp, "d1")
            a_day(first, date="2026-09-01", count=8)
            self._run(tmp, ["--min-days-observed", "1"], samples_dir=first)
            carried = os.path.join(tmp, "carried.json")
            os.replace(os.path.join(tmp, "out", "septacoverage_state.json"),
                       carried)

            second = os.path.join(tmp, "d2")
            a_day(second, date="2026-09-02", count=8)
            self._run(tmp, ["--min-days-observed", "1"],
                      samples_dir=second, state=carried)
            state = self._out(tmp, "septacoverage_state.json")
            coverage = self._out(tmp, "septacoverage.json")

        self.assertEqual(sorted(state["days"]), ["2026-09-01", "2026-09-02"])
        self.assertEqual(coverage["days_observed"], 2)
        self.assertEqual(coverage["observed_through"], "2026-09-02")

    def test_output_is_byte_stable_across_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            a_day(os.path.join(tmp, "samples"), count=8)
            self._run(tmp, ["--min-days-observed", "1"])
            first = {}
            for name in ("septacoverage.json", "septacoverage_state.json"):
                with open(os.path.join(tmp, "out", name), "rb") as handle:
                    first[name] = handle.read()

            self._run(tmp, ["--min-days-observed", "1"])
            for name, payload in first.items():
                with open(os.path.join(tmp, "out", name), "rb") as handle:
                    self.assertEqual(handle.read(), payload, name)


if __name__ == "__main__":
    unittest.main()
