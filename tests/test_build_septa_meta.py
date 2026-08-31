"""Unit tests for build_septa_meta. Stdlib only, no network."""

import io
import json
import os
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import build_septa_meta  # noqa: E402


ROUTES_HEADER = "route_id,route_type,route_sort_order\n"
FEED_INFO = (
    "feed_publisher_name,feed_lang,feed_start_date,feed_end_date,feed_version\n"
    "SEPTA,en,20260823,20270220,v202608233\n"
)


def routes_csv(pairs):
    """pairs: (route_id, sort_order) — route_type is filler."""
    return ROUTES_HEADER + "".join(f"{r},3,{s}\n" for r, s in pairs)


def enough_routes():
    """A route table comfortably above MIN_ROUTES, in scrambled file order."""
    pairs = [(f"R{i}", str(10000 + i)) for i in range(build_septa_meta.MIN_ROUTES + 20)]
    return list(reversed(pairs))


def make_feed(routes=None, feed_info=FEED_INFO, extra=None):
    """A single GTFS zip (no nesting), as raw bytes."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        if routes is not None:
            zf.writestr("routes.txt", routes)
        if feed_info is not None:
            zf.writestr("feed_info.txt", feed_info)
        for name, content in (extra or {}).items():
            zf.writestr(name, content)
    return buffer.getvalue()


def make_bundle(bus_feed_bytes, path, member=build_septa_meta.BUS_FEED_MEMBER):
    """The published shape: an outer zip holding the per-mode feed zips."""
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(member, bus_feed_bytes)
        zf.writestr("google_rail.zip", make_feed(routes_csv([("AIR", "1")])))
    return path


def open_feed(feed_bytes):
    return zipfile.ZipFile(io.BytesIO(feed_bytes))


class RouteListTest(unittest.TestCase):
    def test_orders_by_sort_order_not_file_order(self):
        feed = open_feed(make_feed(routes_csv(enough_routes())))
        routes = build_septa_meta.route_list(feed)
        self.assertEqual(routes[:3], ["R0", "R1", "R2"])
        self.assertEqual(len(routes), build_septa_meta.MIN_ROUTES + 20)

    def test_sort_order_is_numeric_not_lexicographic(self):
        pairs = enough_routes() + [("BIG", "90"), ("SMALL", "9")]
        feed = open_feed(make_feed(routes_csv(pairs)))
        routes = build_septa_meta.route_list(feed)
        self.assertLess(routes.index("SMALL"), routes.index("BIG"))
        self.assertEqual(routes[:2], ["SMALL", "BIG"])

    def test_identical_rows_collapse(self):
        pairs = enough_routes() + [("DUP", "50"), ("DUP", "50")]
        routes = build_septa_meta.route_list(open_feed(make_feed(routes_csv(pairs))))
        self.assertEqual(routes.count("DUP"), 1)

    def test_same_route_under_two_sort_orders_is_an_error(self):
        pairs = enough_routes() + [("DUP", "50"), ("DUP", "51")]
        with self.assertRaisesRegex(ValueError, "duplicate route_ids"):
            build_septa_meta.route_list(open_feed(make_feed(routes_csv(pairs))))

    def test_missing_sort_order_is_an_error(self):
        pairs = enough_routes() + [("NOSORT", "")]
        with self.assertRaisesRegex(ValueError, "route_sort_order"):
            build_septa_meta.route_list(open_feed(make_feed(routes_csv(pairs))))

    def test_non_integer_sort_order_is_an_error(self):
        pairs = enough_routes() + [("BAD", "10a")]
        with self.assertRaisesRegex(ValueError, "non-integer"):
            build_septa_meta.route_list(open_feed(make_feed(routes_csv(pairs))))

    def test_short_feed_is_rejected(self):
        pairs = [("R1", "1"), ("R2", "2")]
        with self.assertRaisesRegex(ValueError, "sanity floor"):
            build_septa_meta.route_list(open_feed(make_feed(routes_csv(pairs))))

    def test_byte_order_mark_does_not_break_the_header(self):
        raw = ("﻿" + routes_csv(enough_routes())).encode("utf-8")
        feed = open_feed(make_feed(raw.decode("utf-8")))
        self.assertIn("R0", build_septa_meta.route_list(feed))


class FeedMetaTest(unittest.TestCase):
    def test_reads_the_three_fields(self):
        meta = build_septa_meta.feed_meta(open_feed(make_feed(routes_csv([]))))
        self.assertEqual(
            meta,
            {
                "start_date": "20260823",
                "end_date": "20270220",
                "version": "v202608233",
            },
        )

    def test_blank_field_is_an_error(self):
        blank = (
            "feed_start_date,feed_end_date,feed_version\n"
            "20260823,,v202608233\n"
        )
        with self.assertRaisesRegex(ValueError, "feed_end_date"):
            build_septa_meta.feed_meta(open_feed(make_feed(None, blank)))

    def test_multiple_rows_are_an_error(self):
        two = (
            "feed_start_date,feed_end_date,feed_version\n"
            "20260823,20270220,a\n"
            "20260824,20270221,b\n"
        )
        with self.assertRaisesRegex(ValueError, "exactly 1"):
            build_septa_meta.feed_meta(open_feed(make_feed(None, two)))


class BundleTest(unittest.TestCase):
    def test_reads_the_bus_feed_out_of_the_nested_bundle(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = make_bundle(make_feed(routes_csv(enough_routes())),
                               os.path.join(tmp, "bundle.zip"))
            self.assertIn("R0", build_septa_meta.route_list(
                build_septa_meta.open_bus_feed(path)))

    def test_accepts_an_unnested_feed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "feed.zip")
            with open(path, "wb") as handle:
                handle.write(make_feed(routes_csv(enough_routes())))
            self.assertIn("R0", build_septa_meta.route_list(
                build_septa_meta.open_bus_feed(path)))

    def test_bundle_without_a_bus_feed_is_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = make_bundle(make_feed(routes_csv(enough_routes())),
                               os.path.join(tmp, "bundle.zip"),
                               member="google_tram.zip")
            with self.assertRaisesRegex(ValueError, "google_bus.zip"):
                build_septa_meta.open_bus_feed(path)


class DocumentTest(unittest.TestCase):
    def _bundle(self, tmp):
        return make_bundle(make_feed(routes_csv(enough_routes())),
                           os.path.join(tmp, "bundle.zip"))

    def test_document_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            document = build_septa_meta.build(self._bundle(tmp))
        self.assertEqual(list(document), ["meta", "buses"])
        self.assertEqual(list(document["meta"]), ["start_date", "end_date", "version"])
        self.assertEqual(list(document["buses"]), ["route_list"])
        self.assertTrue(all(isinstance(r, str) for r in document["buses"]["route_list"]))

    def test_rolling_and_dated_files_are_byte_identical(self):
        with tempfile.TemporaryDirectory() as tmp:
            document = build_septa_meta.build(self._bundle(tmp))
            rolling, dated = build_septa_meta.write_outputs(document, tmp)
            self.assertEqual(os.path.basename(dated), "septameta_20260823.json")
            with open(rolling, "rb") as a, open(dated, "rb") as b:
                self.assertEqual(a.read(), b.read())
            with open(rolling, encoding="utf-8") as handle:
                self.assertEqual(json.load(handle), document)

    def test_output_is_byte_stable_across_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle = self._bundle(tmp)
            first = os.path.join(tmp, "a")
            second = os.path.join(tmp, "b")
            build_septa_meta.write_outputs(build_septa_meta.build(bundle), first)
            build_septa_meta.write_outputs(build_septa_meta.build(bundle), second)
            with open(os.path.join(first, "septameta.json"), "rb") as a, \
                 open(os.path.join(second, "septameta.json"), "rb") as b:
                self.assertEqual(a.read(), b.read())

    def test_main_prints_the_start_date(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle = self._bundle(tmp)
            stdout, sys.stdout = sys.stdout, io.StringIO()
            stderr, sys.stderr = sys.stderr, io.StringIO()
            try:
                self.assertEqual(
                    build_septa_meta.main(
                        ["--gtfs-zip", bundle, "--output-dir", tmp]), 0)
                printed = sys.stdout.getvalue()
            finally:
                sys.stdout, sys.stderr = stdout, stderr
            self.assertEqual(printed.strip(), "20260823")


class DownloadTest(unittest.TestCase):
    def test_retries_then_succeeds(self):
        attempts = []

        class Response(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        def urlopen(url, timeout=None):
            attempts.append(url)
            if len(attempts) < 3:
                raise OSError("boom")
            return Response(b"payload")

        real_urlopen = build_septa_meta.urllib.request.urlopen
        build_septa_meta.urllib.request.urlopen = urlopen
        try:
            with tempfile.TemporaryDirectory() as tmp:
                dest = os.path.join(tmp, "f.zip")
                stderr, sys.stderr = sys.stderr, io.StringIO()
                try:
                    build_septa_meta.download("http://x", dest, sleep=lambda _: None)
                finally:
                    sys.stderr = stderr
                with open(dest, "rb") as handle:
                    self.assertEqual(handle.read(), b"payload")
        finally:
            build_septa_meta.urllib.request.urlopen = real_urlopen
        self.assertEqual(len(attempts), 3)

    def test_gives_up_after_the_attempt_limit(self):
        def urlopen(url, timeout=None):
            raise OSError("boom")

        real_urlopen = build_septa_meta.urllib.request.urlopen
        build_septa_meta.urllib.request.urlopen = urlopen
        try:
            with tempfile.TemporaryDirectory() as tmp:
                stderr, sys.stderr = sys.stderr, io.StringIO()
                try:
                    with self.assertRaises(OSError):
                        build_septa_meta.download(
                            "http://x", os.path.join(tmp, "f.zip"),
                            sleep=lambda _: None)
                finally:
                    sys.stderr = stderr
        finally:
            build_septa_meta.urllib.request.urlopen = real_urlopen


if __name__ == "__main__":
    unittest.main()
