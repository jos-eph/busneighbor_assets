#!/usr/bin/env python3
"""Build septameta.json — SEPTA bus/Metro route list plus feed metadata.

Reads the SEPTA public GTFS bundle (an outer zip containing google_bus.zip and
google_rail.zip), takes routes.txt and feed_info.txt from the bus feed, and
writes:

    septameta.json                    rolling name
    septameta_<feed_start_date>.json  dated name (identical bytes)

Stdlib only, so CI needs no dependency install.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import sys
import time
import urllib.error
import urllib.request
import zipfile

DEFAULT_SOURCE_URL = "https://www3.septa.org/developer/gtfs_public.zip"

# SEPTA ships two feeds inside the public bundle. The bus feed carries every
# surface + Metro route and is the only one with route_sort_order; the rail
# feed is Regional Rail and has neither that column nor the same end date.
BUS_FEED_MEMBER = "google_bus.zip"

# A truncated or half-published upstream feed should fail the build rather than
# ship a short route list. The real feed has ~175 routes.
MIN_ROUTES = 100

# Route colour categories. SEPTA's palette names; the value is the key that
# appears in septameta.json.
BLUE_LINE_BLUE = "blue_line_blue"
BLVD_DIRECT_TEAL = "blvd_direct_teal"
DELCO_PINK = "delco_pink"
FREQUENT_BUS_RED = "frequent_bus_red"
GIRARD_GOLD = "girard_gold"
LUCY_EMERALD = "lucy_emerald"
LUCY_YELLOW = "lucy_yellow"
NORRISTOWN_VIOLET = "norristown_violet"
ORANGE_LINE_ORANGE = "orange_line_orange"
STANDARD_BUS_BLACK = "standard_bus_black"
TEMPORARY_SHUTTLE_BLUE = "temporary_shuttle_blue"
TROLLEY_GREEN = "trolley_green"

# GTFS route_color (uppercase hex, no '#') -> category.
CATEGORY_BY_COLOR = {
    "0097D6": BLUE_LINE_BLUE,
    "003E53": BLVD_DIRECT_TEAL,
    "DC2E6B": DELCO_PINK,
    "EF3340": FREQUENT_BUS_RED,
    "FFD700": GIRARD_GOLD,
    "00A239": LUCY_EMERALD,
    "ECAF3B": LUCY_YELLOW,
    "5F249F": NORRISTOWN_VIOLET,
    "F26100": ORANGE_LINE_ORANGE,
    "1A1818": STANDARD_BUS_BLACK,
    "4F758B": TEMPORARY_SHUTTLE_BLUE,
    "5A960A": TROLLEY_GREEN,
}

_DOWNLOAD_ATTEMPTS = 3
_DOWNLOAD_INITIAL_DELAY_S = 30


def download(url: str, dest: str, *, sleep=time.sleep) -> None:
    """Fetch url to dest, retrying with exponential backoff."""
    delay = _DOWNLOAD_INITIAL_DELAY_S
    for attempt in range(1, _DOWNLOAD_ATTEMPTS + 1):
        try:
            with urllib.request.urlopen(url, timeout=300) as response:
                with open(dest, "wb") as handle:
                    while chunk := response.read(1 << 20):
                        handle.write(chunk)
            return
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            print(f"Download attempt {attempt}/{_DOWNLOAD_ATTEMPTS} failed: {exc}",
                  file=sys.stderr)
            if attempt == _DOWNLOAD_ATTEMPTS:
                raise
            sleep(delay)
            delay *= 4


def open_bus_feed(bundle_path: str) -> zipfile.ZipFile:
    """Return the bus GTFS feed from the SEPTA bundle.

    Accepts either the published bundle (nested zips) or an already-extracted
    single GTFS zip, so the script can be pointed at a local feed for testing.
    """
    outer = zipfile.ZipFile(bundle_path)
    if BUS_FEED_MEMBER in outer.namelist():
        return zipfile.ZipFile(io.BytesIO(outer.read(BUS_FEED_MEMBER)))
    if "routes.txt" in outer.namelist():
        return outer
    raise ValueError(
        f"{bundle_path} contains neither {BUS_FEED_MEMBER} nor routes.txt "
        f"(members: {sorted(outer.namelist())[:10]})"
    )


def _read_csv(feed: zipfile.ZipFile, name: str) -> list[dict[str, str]]:
    # utf-8-sig: SEPTA's GTFS text files carry a BOM, which would otherwise end
    # up glued to the first column name.
    text = feed.read(name).decode("utf-8-sig")
    return list(csv.DictReader(io.StringIO(text)))


def route_list(feed: zipfile.ZipFile) -> list[str]:
    """Route ids from routes.txt, ordered by route_sort_order and deduplicated."""
    rows = _read_csv(feed, "routes.txt")
    if not rows:
        raise ValueError("routes.txt is empty")

    pairs = set()
    for row in rows:
        route_id = (row.get("route_id") or "").strip()
        sort_order = (row.get("route_sort_order") or "").strip()
        if not route_id:
            raise ValueError(f"routes.txt row is missing route_id: {row}")
        if not sort_order:
            raise ValueError(f"routes.txt row {route_id} is missing route_sort_order")
        try:
            pairs.add((int(sort_order), route_id))
        except ValueError as exc:
            raise ValueError(
                f"routes.txt row {route_id} has non-integer "
                f"route_sort_order {sort_order!r}"
            ) from exc

    routes = [route_id for _, route_id in sorted(pairs)]

    # Two rows sharing a route_id under different sort orders would survive the
    # tuple set and silently duplicate the route in the output.
    if len(routes) != len(set(routes)):
        duplicates = sorted({r for r in routes if routes.count(r) > 1})
        raise ValueError(f"duplicate route_ids after sorting: {duplicates}")
    if len(routes) < MIN_ROUTES:
        raise ValueError(
            f"only {len(routes)} routes, below the {MIN_ROUTES} sanity floor; "
            "refusing to publish a possibly truncated feed"
        )
    return routes


def feed_meta(feed: zipfile.ZipFile) -> dict[str, str]:
    """feed_start_date, feed_end_date and feed_version from feed_info.txt."""
    rows = _read_csv(feed, "feed_info.txt")
    if len(rows) != 1:
        raise ValueError(f"expected exactly 1 feed_info.txt row, found {len(rows)}")
    row = rows[0]

    meta = {}
    for key, column in (
        ("start_date", "feed_start_date"),
        ("end_date", "feed_end_date"),
        ("version", "feed_version"),
    ):
        value = (row.get(column) or "").strip()
        if not value:
            raise ValueError(f"feed_info.txt is missing {column}")
        meta[key] = value
    return meta


def build(bundle_path: str) -> dict:
    feed = open_bus_feed(bundle_path)
    return {"meta": feed_meta(feed), "buses": {"route_list": route_list(feed)}}


def write_outputs(document: dict, output_dir: str) -> tuple[str, str]:
    """Write the rolling and dated JSON files; return their paths."""
    os.makedirs(output_dir, exist_ok=True)
    payload = json.dumps(document, indent=2) + "\n"

    rolling = os.path.join(output_dir, "septameta.json")
    dated = os.path.join(
        output_dir, f"septameta_{document['meta']['start_date']}.json"
    )
    for path in (rolling, dated):
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(payload)
    return rolling, dated


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default="out")
    parser.add_argument(
        "--source-url",
        default=DEFAULT_SOURCE_URL,
        help="SEPTA GTFS bundle URL (ignored when --gtfs-zip is given)",
    )
    parser.add_argument(
        "--gtfs-zip",
        help="use this local bundle instead of downloading",
    )
    args = parser.parse_args(argv)

    bundle = args.gtfs_zip
    if bundle is None:
        os.makedirs(args.output_dir, exist_ok=True)
        bundle = os.path.join(args.output_dir, "gtfs_public.zip")
        print(f"Downloading {args.source_url}", file=sys.stderr)
        download(args.source_url, bundle)

    document = build(bundle)
    rolling, dated = write_outputs(document, args.output_dir)

    meta = document["meta"]
    print(
        f"{len(document['buses']['route_list'])} routes, "
        f"feed {meta['version']} ({meta['start_date']}–{meta['end_date']})",
        file=sys.stderr,
    )
    print(f"Wrote {rolling} and {dated}", file=sys.stderr)
    # stdout carries the start date alone, so CI can capture it directly.
    print(meta["start_date"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
