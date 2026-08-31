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


ROUTES_HEADER = "route_id,route_type,route_sort_order,route_color\n"
FEED_INFO = (
    "feed_publisher_name,feed_lang,feed_start_date,feed_end_date,feed_version\n"
    "SEPTA,en,20260823,20270220,v202608233\n"
)

# STANDARD_BUS_BLACK, so existing (route_id, sort_order) fixtures keep
# classifying without every test needing to care about colour.
DEFAULT_COLOR = next(
    color for color, category in build_septa_meta.CATEGORY_BY_COLOR.items()
    if category == build_septa_meta.STANDARD_BUS_BLACK
)


def routes_csv(pairs, color=None):
    """pairs: (route_id, sort_order) or (route_id, sort_order, route_color).

    route_type is filler; a route_color left out of a triple falls back to
    `color` (default DEFAULT_COLOR).
    """
    default = color if color is not None else DEFAULT_COLOR
    lines = []
    for pair in pairs:
        route_id, sort_order, *rest = pair
        row_color = rest[0] if rest else default
        lines.append(f"{route_id},3,{sort_order},{row_color}\n")
    return ROUTES_HEADER + "".join(lines)


def enough_routes():
    """A route table comfortably above MIN_ROUTES, in scrambled file order."""
    pairs = [(f"R{i}", str(10000 + i)) for i in range(build_septa_meta.MIN_ROUTES + 20)]
    return list(reversed(pairs))


def multi_color_routes():
    """enough_routes, but cycling through every category instead of one."""
    colors = list(build_septa_meta.CATEGORY_BY_COLOR)
    pairs = [
        (f"R{i}", str(10000 + i), colors[i % len(colors)])
        for i in range(build_septa_meta.MIN_ROUTES + 20)
    ]
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
        buses = document["buses"]
        self.assertEqual(list(buses), ["route_list", "route_category", "category_routes"])
        self.assertTrue(all(isinstance(r, str) for r in buses["route_list"]))
        self.assertEqual(set(buses["route_category"]), set(buses["route_list"]))
        self.assertEqual(
            sorted(buses["category_routes"]),
            sorted(build_septa_meta.CATEGORY_BY_COLOR.values()),
        )
        self.assertEqual(list(buses["category_routes"]), sorted(buses["category_routes"]))

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
            bundle = make_bundle(make_feed(routes_csv(multi_color_routes())),
                                  os.path.join(tmp, "bundle.zip"))
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


class RouteCategoriesTest(unittest.TestCase):
    def test_route_lands_in_the_category_its_colour_names(self):
        pairs = enough_routes() + [("T1", "99999", "5A960A")]
        feed = open_feed(make_feed(routes_csv(pairs)))
        route_category, category_routes = build_septa_meta.route_categories(feed)
        self.assertEqual(route_category["T1"], "trolley_green")
        self.assertIn("T1", category_routes["trolley_green"])

    def test_category_routes_values_follow_sort_order_not_file_order(self):
        pairs = enough_routes() + [
            ("Z", "1", "5A960A"),
            ("A", "2", "5A960A"),
            ("M", "0", "5A960A"),
        ]
        feed = open_feed(make_feed(routes_csv(pairs)))
        _, category_routes = build_septa_meta.route_categories(feed)
        self.assertEqual(category_routes["trolley_green"], ["M", "Z", "A"])

    def test_all_twelve_categories_appear_even_with_one_colour_in_the_feed(self):
        feed = open_feed(make_feed(routes_csv(enough_routes())))
        _, category_routes = build_septa_meta.route_categories(feed)
        self.assertEqual(
            sorted(category_routes), sorted(build_septa_meta.CATEGORY_BY_COLOR.values()))
        self.assertEqual(list(category_routes), sorted(category_routes))
        self.assertEqual(category_routes["trolley_green"], [])

    def test_route_category_covers_exactly_route_list(self):
        feed = open_feed(make_feed(routes_csv(multi_color_routes())))
        routes = build_septa_meta.route_list(feed)
        route_category, category_routes = build_septa_meta.route_categories(feed)
        self.assertEqual(set(route_category), set(routes))
        self.assertEqual(sum(len(v) for v in category_routes.values()), len(routes))

    def test_unrecognised_colour_is_an_error(self):
        pairs = enough_routes() + [("BAD", "99999", "ABCDEF")]
        feed = open_feed(make_feed(routes_csv(pairs)))
        with self.assertRaisesRegex(ValueError, "ABCDEF"):
            build_septa_meta.route_categories(feed)

    def test_blank_colour_is_an_error(self):
        pairs = enough_routes() + [("NOCOLOR", "99999", "")]
        feed = open_feed(make_feed(routes_csv(pairs)))
        with self.assertRaisesRegex(ValueError, "NOCOLOR"):
            build_septa_meta.route_categories(feed)

    def test_lowercase_hex_still_classifies(self):
        pairs = enough_routes() + [("T1", "99999", "5a960a")]
        feed = open_feed(make_feed(routes_csv(pairs)))
        route_category, _ = build_septa_meta.route_categories(feed)
        self.assertEqual(route_category["T1"], "trolley_green")


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
