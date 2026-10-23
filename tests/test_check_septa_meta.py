"""Tests for the septameta.json publish check. Stdlib only."""

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import check_septa_meta as checker


def document(routes, denied=()):
    return {
        "meta": {"start_date": "20260823", "end_date": "20270220",
                 "version": "v202608233"},
        "buses": {"route_list": list(routes)},
        "realtime": {"source": "manual", "observed_through": None,
                     "overrides": {"no_vehicle_positions": list(denied)}},
    }


LIVE = document(["L1", "2", "4", "17", "23"], denied=["L1"])


class OfferedRoutesTest(unittest.TestCase):
    def test_deny_list_is_subtracted_in_order(self):
        self.assertEqual(checker.offered_routes(LIVE), ["2", "4", "17", "23"])

    def test_missing_deny_list_offers_everything(self):
        doc = {"buses": {"route_list": ["2", "4"]}}
        self.assertEqual(checker.offered_routes(doc), ["2", "4"])

    def test_documents_the_app_would_reject_raise(self):
        for doc in ([], {}, {"buses": {"route_list": []}},
                    {"buses": {"route_list": "2"}},
                    {"buses": {"route_list": [2]}},
                    {"buses": {"route_list": ["  "]}},
                    {"buses": {"route_list": ["2"]},
                     "realtime": {"overrides": {"no_vehicle_positions": "4"}}}):
            with self.subTest(doc=doc):
                with self.assertRaises(ValueError):
                    checker.offered_routes(doc)


class CheckTest(unittest.TestCase):
    def test_unchanged_offer_is_safe(self):
        safe, _ = checker.check(LIVE, [("live", LIVE)], set())
        self.assertTrue(safe)

    def test_added_route_is_safe(self):
        candidate = document(["L1", "2", "4", "17", "23", "99"], ["L1"])
        safe, messages = checker.check(candidate, [("live", LIVE)], set())
        self.assertTrue(safe)
        self.assertIn("99", " ".join(messages))

    def test_route_leaving_route_list_is_refused(self):
        candidate = document(["L1", "2", "4", "23"], ["L1"])
        safe, messages = checker.check(candidate, [("live", LIVE)], set())
        self.assertFalse(safe)
        self.assertIn("17", " ".join(messages))

    def test_route_joining_the_deny_list_is_refused(self):
        candidate = document(["L1", "2", "4", "17", "23"], ["L1", "4"])
        safe, _ = checker.check(candidate, [("live", LIVE)], set())
        self.assertFalse(safe)

    def test_route_leaving_the_deny_list_is_safe(self):
        candidate = document(["L1", "2", "4", "17", "23"], [])
        safe, _ = checker.check(candidate, [("live", LIVE)], set())
        self.assertTrue(safe)

    def test_exact_approval_allows_the_removal(self):
        candidate = document(["L1", "2", "23"], ["L1"])
        safe, _ = checker.check(candidate, [("live", LIVE)], {"4", "17"})
        self.assertTrue(safe)

    def test_partial_approval_does_not_apply(self):
        candidate = document(["L1", "2", "23"], ["L1"])
        safe, _ = checker.check(candidate, [("live", LIVE)], {"4"})
        self.assertFalse(safe)

    def test_broader_approval_does_not_apply(self):
        candidate = document(["L1", "2", "4", "23"], ["L1"])
        safe, _ = checker.check(candidate, [("live", LIVE)], {"17", "23"})
        self.assertFalse(safe)

    def test_candidate_the_app_would_reject_is_refused(self):
        safe, _ = checker.check({"buses": {"route_list": []}}, [("live", LIVE)], set())
        self.assertFalse(safe)

    def test_first_publish_is_safe(self):
        safe, _ = checker.check(LIVE, None, set())
        self.assertTrue(safe)

    def test_unparseable_live_copy_alone_is_refused(self):
        # Devices still hold the last good copy; an unusable live file is not
        # permission to publish something smaller.
        safe, messages = checker.check(document(["2"]),
                                       [("live", {"buses": {}})], set())
        self.assertFalse(safe)
        self.assertIn("no readable", " ".join(messages))

    def test_unparseable_live_copy_falls_back_to_the_dated_release(self):
        candidate = document(["L1", "2", "4", "23"], ["L1"])
        safe, messages = checker.check(
            candidate, [("live", {"buses": {}}), ("dated", LIVE)], set())
        self.assertFalse(safe)
        self.assertIn("17", " ".join(messages))

    def test_missing_live_copy_still_checks_the_dated_release(self):
        candidate = document(["2"])
        safe, _ = checker.check(candidate, [("dated", LIVE)], set())
        self.assertFalse(safe)

    def test_every_baseline_must_survive(self):
        older = document(["2", "4", "17", "23", "99"])
        candidate = document(["L1", "2", "4", "17", "23"], ["L1"])
        safe, messages = checker.check(
            candidate, [("live", LIVE), ("dated", older)], set())
        self.assertFalse(safe)
        self.assertIn("99", " ".join(messages))


class ParseApprovalTest(unittest.TestCase):
    def test_comma_list_is_trimmed(self):
        self.assertEqual(checker.parse_approval(" 4, 17 ,,"), {"4", "17"})

    def test_empty_is_no_approval(self):
        self.assertEqual(checker.parse_approval(""), set())
        self.assertEqual(checker.parse_approval(None), set())


class MainTest(unittest.TestCase):
    def run_main(self, candidate, published=None, *extra, raw_published=None):
        with tempfile.TemporaryDirectory() as tmp:
            cand_path = os.path.join(tmp, "candidate.json")
            with open(cand_path, "w", encoding="utf-8") as handle:
                json.dump(candidate, handle)
            args = ["--candidate", cand_path]
            if published is None and raw_published is None:
                args.append("--first-publish")
            else:
                pub_path = os.path.join(tmp, "published.json")
                with open(pub_path, "w", encoding="utf-8") as handle:
                    if raw_published is not None:
                        handle.write(raw_published)
                    else:
                        json.dump(published, handle)
                args += ["--published", pub_path]
            with contextlib.redirect_stderr(io.StringIO()):
                return checker.main(args + list(extra))

    def test_safe_exits_zero(self):
        self.assertEqual(self.run_main(LIVE, LIVE), 0)

    def test_removal_exits_nonzero(self):
        self.assertEqual(self.run_main(document(["2"]), LIVE), 1)

    def test_approved_removal_exits_zero(self):
        candidate = document(["L1", "2", "4", "23"], ["L1"])
        self.assertEqual(
            self.run_main(candidate, LIVE, "--approve-removals", "17"), 0)

    def test_non_json_live_copy_alone_is_refused(self):
        self.assertEqual(self.run_main(LIVE, raw_published="<html>"), 1)

    def test_repeated_published_flags_are_all_checked(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = {}
            for name, doc in (("candidate", document(["L1", "2"], ["L1"])),
                              ("live", LIVE),
                              ("dated", LIVE)):
                paths[name] = os.path.join(tmp, f"{name}.json")
                with open(paths[name], "w", encoding="utf-8") as handle:
                    json.dump(doc, handle)
            missing = os.path.join(tmp, "missing.json")
            with contextlib.redirect_stderr(io.StringIO()):
                code = checker.main([
                    "--candidate", paths["candidate"],
                    "--published", paths["live"],
                    "--published", missing,
                    "--published", paths["dated"],
                    "--approve-removals", "4,17,23"])
        self.assertEqual(code, 0)

    def test_published_or_first_publish_is_required(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                checker.main(["--candidate", "x"])


if __name__ == "__main__":
    unittest.main()


class ExtraFieldsTest(unittest.TestCase):
    def with_fields(self, **fields):
        candidate = document(["L1", "2", "4", "17", "23"], ["L1"])
        candidate.update(fields)
        return candidate

    def test_a_document_without_them_is_fine(self):
        safe, _ = checker.check(LIVE, [("live", LIVE)], set())
        self.assertTrue(safe)

    def test_routes_without_words_are_a_notice_not_a_refusal(self):
        candidate = self.with_fields(
            directions={"2": {"0": "Northbound", "1": "Southbound"}},
            alternate_feed_host=None)
        safe, messages = checker.check(candidate, [("live", LIVE)], set())
        self.assertTrue(safe)
        self.assertIn("no direction words for 4 route(s)", " ".join(messages))

    def test_malformed_directions_refuse_the_publish(self):
        for words in ({"2": {"0": "northbound"}}, {"2": {"0": "Northbuond"}},
                      {"2": {"3": "Loop"}},
                      {"2": {}}, {"2": "Loop"}, ["2"]):
            with self.subTest(words=words):
                safe, _ = checker.check(self.with_fields(directions=words),
                                        [("live", LIVE)], set())
                self.assertFalse(safe)

    def test_a_bad_alternate_host_refuses_the_publish(self):
        for host in ("https://x.example", "x.example/p", 7):
            with self.subTest(host=host):
                safe, _ = checker.check(
                    self.with_fields(alternate_feed_host=host),
                    [("live", LIVE)], set())
                self.assertFalse(safe)

    def test_a_bare_alternate_host_is_fine(self):
        safe, _ = checker.check(
            self.with_fields(alternate_feed_host="backup.example"),
            [("live", LIVE)], set())
        self.assertTrue(safe)
