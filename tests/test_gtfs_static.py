"""Tests for the static GTFS name lookups. Stdlib only."""

import os
import sys
import tempfile
import unittest
import zipfile
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gtfs_static

BOM = "﻿"


def bus_feed(path, *, directions=True):
    with zipfile.ZipFile(path, "w") as feed:
        feed.writestr("routes.txt", "route_id\n42\n")
        feed.writestr("stops.txt",
                      BOM + "stop_id,stop_code,stop_name\n311,311,Pine St & 3rd St\n")
        feed.writestr("trips.txt",
                      BOM + "route_id,trip_id,trip_headsign\n42,879705,Wycombe\n")
        if directions:
            feed.writestr("directions.txt",
                          BOM + "route_id,direction_id,direction\n42,1,Westbound\n")


class LoadTest(unittest.TestCase):
    def test_reads_all_three_lookups_past_the_bom(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "bus.zip")
            bus_feed(path)
            names = gtfs_static.load(path)

        self.assertEqual(names.stop("311"), "Pine St & 3rd St")
        self.assertEqual(names.headsign("879705"), "Wycombe")
        self.assertEqual(names.direction("42", 1), "Westbound")

    def test_reads_the_bus_feed_inside_the_public_bundle(self):
        with tempfile.TemporaryDirectory() as tmp:
            inner = os.path.join(tmp, "google_bus.zip")
            bus_feed(inner)
            outer = os.path.join(tmp, "gtfs_public.zip")
            with zipfile.ZipFile(outer, "w") as bundle:
                bundle.write(inner, "google_bus.zip")
            names = gtfs_static.load(outer)

        self.assertEqual(names.stop("311"), "Pine St & 3rd St")

    def test_no_directions_file_means_no_directions(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "bus.zip")
            bus_feed(path, directions=False)
            names = gtfs_static.load(path)

        self.assertIsNone(names.direction("42", 1))

    def test_unknown_or_missing_ids_have_no_name(self):
        names = gtfs_static.Names(stops={"311": "x"})

        self.assertIsNone(names.stop("999"))
        self.assertIsNone(names.stop(None))
        self.assertIsNone(names.headsign(None))
        self.assertIsNone(names.direction(None, 1))
        self.assertIsNone(names.direction("42", None))


class DownloadTest(unittest.TestCase):
    def test_a_failed_download_leaves_nothing_at_the_destination(self):
        def fail(url, dest):
            with open(dest, "wb") as handle:
                handle.write(b"half a zip")
            raise OSError("connection reset")

        with tempfile.TemporaryDirectory() as tmp:
            dest = os.path.join(tmp, "gtfs", "gtfs_public.zip")
            with mock.patch.object(gtfs_static.build_septa_meta, "download",
                                   side_effect=fail):
                with self.assertRaises(OSError):
                    gtfs_static.download(dest)

            self.assertFalse(os.path.exists(dest))

    def test_a_whole_download_lands_at_the_destination(self):
        def succeed(url, dest):
            with open(dest, "wb") as handle:
                handle.write(b"zip")

        with tempfile.TemporaryDirectory() as tmp:
            dest = os.path.join(tmp, "gtfs", "gtfs_public.zip")
            with mock.patch.object(gtfs_static.build_septa_meta, "download",
                                   side_effect=succeed):
                gtfs_static.download(dest)

            with open(dest, "rb") as handle:
                self.assertEqual(handle.read(), b"zip")


if __name__ == "__main__":
    unittest.main()
