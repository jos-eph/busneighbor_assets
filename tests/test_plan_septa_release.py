"""Tests for keeping pending removals in the published document."""

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import build_septa_meta
import check_septa_meta as checker
import plan_septa_release as plan

WORDS = {"0": "Northbound", "1": "Southbound"}


def document(routes, denied=(), directions=None, version="v1"):
    doc = {
        "meta": {"start_date": "20261101", "end_date": "20270220",
                 "version": version},
        "buses": {"route_list": list(routes)},
        "realtime": {"source": "manual", "observed_through": None,
                     "overrides": {"no_vehicle_positions": list(denied)}},
    }
    if directions is not None:
        doc["directions"] = dict(directions)
    return doc


LIVE = document(["L1", "2", "4", "17", "23"], denied=["L1"],
                directions={r: WORDS for r in ["L1", "2", "4", "17", "23"]})


def live(doc=LIVE):
    return [("live", doc)]


class PendingRemovalsTest(unittest.TestCase):
    def test_nothing_removed(self):
        candidate = document(["L1", "2", "4", "17", "23", "99"], ["L1"])
        self.assertEqual(plan.pending_removals(candidate, live(), set()), [])

    def test_route_leaving_the_list_is_pending(self):
        candidate = document(["L1", "2", "4", "23"], ["L1"])
        self.assertEqual(plan.pending_removals(candidate, live(), set()), ["17"])

    def test_route_joining_the_deny_list_is_pending(self):
        candidate = document(["L1", "2", "4", "17", "23"], ["L1", "4"])
        self.assertEqual(plan.pending_removals(candidate, live(), set()), ["4"])

    def test_exact_approval_clears_it(self):
        candidate = document(["L1", "2", "23"], ["L1"])
        self.assertEqual(
            plan.pending_removals(candidate, live(), {"4", "17"}), [])

    def test_partial_or_broader_approval_does_not(self):
        candidate = document(["L1", "2", "23"], ["L1"])
        for approved in ({"4"}, {"4", "17", "23"}):
            with self.subTest(approved=approved):
                self.assertEqual(
                    plan.pending_removals(candidate, live(), approved),
                    ["4", "17"])

    def test_union_of_baselines_counts(self):
        dated = document(["L1", "2", "4", "17", "23", "40"], ["L1"])
        candidate = document(["L1", "2", "4", "17", "23"], ["L1"])
        self.assertEqual(
            plan.pending_removals(candidate, live() + [("dated", dated)], set()),
            ["40"])

    def test_nothing_to_compare_against_leaves_it_to_the_check(self):
        candidate = document(["2"])
        unreadable = [("live", checker._Unparseable("not JSON"))]
        for baselines in (None, [], unreadable):
            with self.subTest(baselines=baselines):
                self.assertEqual(
                    plan.pending_removals(candidate, baselines, set()), [])

    def test_candidate_the_app_would_reject_is_left_to_the_check(self):
        self.assertEqual(
            plan.pending_removals({"buses": {"route_list": []}}, live(), set()),
            [])


class CarryOverTest(unittest.TestCase):
    def test_removed_route_returns_to_its_place_with_its_words(self):
        candidate = document(["L1", "2", "4", "23", "99"], ["L1"],
                             {r: WORDS for r in ["L1", "2", "4", "23", "99"]})
        kept = plan.carry_over(candidate, live())
        self.assertEqual(kept["buses"]["route_list"],
                         ["L1", "2", "4", "17", "23", "99"])
        self.assertEqual(list(kept["directions"]),
                         ["L1", "2", "4", "17", "23", "99"])
        self.assertEqual(kept["meta"], candidate["meta"])

    def test_neighbors_removed_together_keep_their_order(self):
        candidate = document(["L1", "2", "23"], ["L1"])
        kept = plan.carry_over(candidate, live())
        self.assertEqual(kept["buses"]["route_list"],
                         ["L1", "2", "4", "17", "23"])

    def test_first_route_goes_back_first(self):
        base = document(["2", "4", "17"])
        kept = plan.carry_over(document(["4", "17"]), [("live", base)])
        self.assertEqual(kept["buses"]["route_list"], ["2", "4", "17"])

    def test_route_joining_the_deny_list_comes_back_off_it(self):
        candidate = document(["L1", "2", "4", "17", "23"], ["L1", "4"])
        kept = plan.carry_over(candidate, live())
        self.assertEqual(
            kept["realtime"]["overrides"]["no_vehicle_positions"], ["L1"])
        self.assertEqual(kept["buses"]["route_list"],
                         candidate["buses"]["route_list"])

    def test_candidate_is_not_modified(self):
        candidate = document(["L1", "2", "4", "23"], ["L1"])
        before = json.dumps(candidate)
        plan.carry_over(candidate, live())
        self.assertEqual(json.dumps(candidate), before)

    def test_result_offers_everything_every_baseline_offers(self):
        dated = document(["L1", "2", "4", "17", "23", "40"], ["L1"])
        baselines = live() + [("dated", dated)]
        kept = plan.carry_over(document(["L1", "2", "99"], ["L1"]), baselines)
        safe, _ = checker.check(kept, baselines, set())
        self.assertTrue(safe)
        self.assertEqual(kept["buses"]["route_list"],
                         ["L1", "2", "4", "17", "23", "40", "99"])

    def test_unreadable_baseline_is_skipped(self):
        baselines = [("dated", checker._Unparseable("not JSON"))] + live()
        kept = plan.carry_over(document(["L1", "2", "4", "23"], ["L1"]),
                               baselines)
        self.assertIn("17", kept["buses"]["route_list"])

    def test_a_second_run_reproduces_the_published_document(self):
        # The week after: the kept document is now the published one.
        candidate = document(["L1", "2", "4", "23", "99"], ["L1"],
                             {r: WORDS for r in ["L1", "2", "4", "23", "99"]})
        first = plan.carry_over(candidate, live())
        second = plan.carry_over(candidate, [("live", first)])
        self.assertEqual(json.dumps(second, indent=2),
                         json.dumps(first, indent=2))


class MainTest(unittest.TestCase):
    def _run(self, tmp, candidate, published, approve=""):
        out = os.path.join(tmp, "out")
        pure = os.path.join(out, "pure")
        build_septa_meta.write_outputs(candidate, out)
        argv = ["--output-dir", out, "--pure-dir", pure,
                "--approve-removals", approve]
        for i, doc in enumerate(published):
            path = os.path.join(tmp, f"published{i}.json")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(doc, handle)
            argv += ["--published", path]
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout), \
                contextlib.redirect_stderr(io.StringIO()):
            code = plan.main(argv)
        outputs = dict(line.split("=", 1)
                       for line in stdout.getvalue().splitlines())

        def read(directory, name="septameta.json"):
            with open(os.path.join(directory, name), encoding="utf-8") as handle:
                return json.load(handle)
        return code, outputs, read(out), read(pure), read

    def test_pending_removal_is_kept_and_the_candidate_set_aside(self):
        candidate = document(["L1", "2", "4", "23"], ["L1"])
        with tempfile.TemporaryDirectory() as tmp:
            code, outputs, published, pure, read = self._run(
                tmp, candidate, [LIVE])
            self.assertEqual(code, plan.EXIT_OK)
            self.assertEqual(outputs["pending"], "17")
            self.assertIn("17", published["buses"]["route_list"])
            self.assertEqual(pure, candidate)
            out = os.path.join(tmp, "out")
            self.assertEqual(read(out, "septameta_20261101.json"), published)
            self.assertEqual(
                read(os.path.join(out, "pure"), "septameta_20261101.json"),
                candidate)
            self.assertEqual(
                outputs["candidate_sha256"],
                plan.sha256_of(os.path.join(out, "pure", "septameta.json")))

    def test_approved_removal_publishes_the_candidate(self):
        candidate = document(["L1", "2", "4", "23"], ["L1"])
        with tempfile.TemporaryDirectory() as tmp:
            code, outputs, published, _, _ = self._run(
                tmp, candidate, [LIVE], approve="17")
            self.assertEqual(code, plan.EXIT_OK)
            self.assertEqual(outputs["pending"], "")
            self.assertEqual(published, candidate)

    def test_no_removal_leaves_the_build_alone(self):
        candidate = document(["L1", "2", "4", "17", "23", "99"], ["L1"])
        with tempfile.TemporaryDirectory() as tmp:
            _, outputs, published, pure, _ = self._run(tmp, candidate, [LIVE])
            self.assertEqual(outputs["pending"], "")
            self.assertEqual(published, candidate)
            self.assertEqual(pure, candidate)

    def test_first_publish_has_nothing_pending(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, outputs, published, _, _ = self._run(
                tmp, document(["2", "4"]), [])
            self.assertEqual(code, plan.EXIT_OK)
            self.assertEqual(outputs["pending"], "")
            self.assertEqual(published, document(["2", "4"]))

    def test_unreadable_candidate_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            with contextlib.redirect_stderr(io.StringIO()):
                code = plan.main(["--output-dir", tmp,
                                  "--pure-dir", os.path.join(tmp, "pure")])
            self.assertEqual(code, plan.EXIT_FAILED)


if __name__ == "__main__":
    unittest.main()
