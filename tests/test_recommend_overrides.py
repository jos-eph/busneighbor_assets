"""Tests for the deny-list recommendation generator.

The property that matters most is negative: this tool must never change what
users see. It writes advice next to the live list, never over it.
"""

import io
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import recommend_overrides as rec

COMMITTED = ["L1", "B1", "B2", "B3"]


def coverage(routes=None, days_observed=28, samples=214):
    routes = routes or {
        "L1": {"days_seen": 0, "last_seen": None, "positions": 0},
        "B1": {"days_seen": 0, "last_seen": None, "positions": 0},
        "B2": {"days_seen": 3, "last_seen": "2026-09-27", "positions": 41},
        "B3": {"days_seen": 0, "last_seen": None, "positions": 0},
        "MFL_SHUTTLE": {"days_seen": 0, "last_seen": None, "positions": 0},
    }
    return {
        "observed_through": "2026-09-28",
        "days_observed": days_observed,
        "samples": samples,
        "feed_meta": {"start_date": "20260823", "version": "v202608233"},
        "vehicle_positions": {"routes": routes,
                              "no_vehicle_positions": list(COMMITTED)},
    }


def proposal(routes):
    return {"source": "observed", "observed_through": "2026-09-28",
            "window_days": 28, "days_observed": 28,
            "updated_at": "2026-09-29T01:47:12Z",
            "no_vehicle_positions": list(routes)}


def committed(routes=COMMITTED):
    return {"source": "manual", "no_vehicle_positions": list(routes)}


class RecommendTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.json_path = os.path.join(self.tmp.name, "recommended.json")
        self.doc_path = os.path.join(self.tmp.name, "docs", "rec.md")

    def run_it(self, proposed, current=COMMITTED):
        return rec.recommend(
            proposal(proposed),
            committed(current) if current is not None else None,
            coverage(),
            json_path=self.json_path, doc_path=self.doc_path)

    def test_agreement_writes_nothing(self):
        changed, reason = self.run_it(COMMITTED)
        self.assertFalse(changed)
        self.assertFalse(os.path.exists(self.json_path))
        self.assertFalse(os.path.exists(self.doc_path))
        self.assertIn("agrees", reason)

    def test_disagreement_writes_both_files(self):
        changed, _ = self.run_it(["L1", "B1", "B3", "MFL_SHUTTLE"])
        self.assertTrue(changed)
        self.assertTrue(os.path.exists(self.json_path))
        self.assertTrue(os.path.exists(self.doc_path))

    def test_the_recommended_json_is_a_drop_in_replacement(self):
        """It must have the same shape as realtime_overrides.json, so applying
        it really is a copy rather than an edit."""
        self.run_it(["L1", "B1", "B3", "MFL_SHUTTLE"])
        with open(self.json_path, encoding="utf-8") as handle:
            written = json.load(handle)
        for key in ("source", "observed_through", "window_days",
                    "days_observed", "updated_at", "no_vehicle_positions"):
            self.assertIn(key, written)
        self.assertEqual(written["source"], "observed")

    def test_the_document_names_additions_and_removals_with_evidence(self):
        self.run_it(["L1", "B1", "B3", "MFL_SHUTTLE"])
        with open(self.doc_path, encoding="utf-8") as handle:
            doc = handle.read()
        self.assertIn("MFL_SHUTTLE", doc)
        self.assertIn("no vehicle positions on any of 28 days", doc)
        self.assertIn("B2", doc)
        self.assertIn("seen on 3 of 28 days, last 2026-09-27", doc)
        self.assertIn("Nothing has changed for users", doc)

    def test_repeating_the_same_recommendation_is_not_a_change(self):
        """Otherwise a stable disagreement would commit every single day."""
        self.assertTrue(self.run_it(["L1", "B1", "B3", "MFL_SHUTTLE"])[0])
        changed, reason = self.run_it(["L1", "B1", "B3", "MFL_SHUTTLE"])
        self.assertFalse(changed)
        self.assertIn("already delivered", reason)

    def test_a_new_recommendation_replaces_the_old_one(self):
        self.run_it(["L1", "B1", "B3", "MFL_SHUTTLE"])
        changed, _ = self.run_it(["L1", "B1", "B3"])
        self.assertTrue(changed)
        with open(self.json_path, encoding="utf-8") as handle:
            self.assertEqual(json.load(handle)["no_vehicle_positions"],
                             ["L1", "B1", "B3"])

    def test_returning_to_agreement_clears_a_stale_recommendation(self):
        """A recommendation left lying around would read as current advice."""
        self.assertTrue(self.run_it(["L1", "B1", "B3", "MFL_SHUTTLE"])[0])
        changed, reason = self.run_it(COMMITTED)
        self.assertTrue(changed)
        self.assertFalse(os.path.exists(self.json_path))
        self.assertFalse(os.path.exists(self.doc_path))
        self.assertIn("clearing", reason)

    def test_no_committed_list_means_no_recommendation(self):
        changed, reason = self.run_it(["L1"], current=None)
        self.assertFalse(changed)
        self.assertFalse(os.path.exists(self.json_path))
        self.assertIn("no committed", reason)


class NeverTouchesTheLiveListTest(unittest.TestCase):
    """The whole point: advice is written beside the live list, never over it."""

    def test_the_live_file_is_untouched_even_when_recommending(self):
        with tempfile.TemporaryDirectory() as tmp:
            live = os.path.join(tmp, "realtime_overrides.json")
            original = json.dumps(committed(), indent=2)
            with open(live, "w", encoding="utf-8") as handle:
                handle.write(original)

            stdout, sys.stdout = sys.stdout, io.StringIO()
            stderr, sys.stderr = sys.stderr, io.StringIO()
            try:
                for path, document in (
                    ("proposal.json", proposal(["L1", "B1", "MFL_SHUTTLE"])),
                    ("coverage.json", coverage()),
                ):
                    with open(os.path.join(tmp, path), "w", encoding="utf-8") as h:
                        json.dump(document, h)
                code = rec.main([
                    "--proposal", os.path.join(tmp, "proposal.json"),
                    "--coverage", os.path.join(tmp, "coverage.json"),
                    "--committed", live,
                    "--out-json", os.path.join(tmp, "recommended.json"),
                    "--out-doc", os.path.join(tmp, "rec.md"),
                ])
                printed = sys.stdout.getvalue()
            finally:
                sys.stdout, sys.stderr = stdout, stderr

            self.assertEqual(code, 0)
            self.assertEqual(printed.strip(), "true")
            with open(live, encoding="utf-8") as handle:
                self.assertEqual(handle.read(), original)

    def test_the_output_paths_are_not_the_live_path(self):
        self.assertNotEqual(rec.DEFAULT_RECOMMENDED_JSON,
                            "realtime_overrides.json")
        self.assertTrue(
            rec.DEFAULT_RECOMMENDED_JSON.endswith(".recommended.json"))


if __name__ == "__main__":
    unittest.main()
