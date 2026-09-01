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

import fetching

DEFAULT_SOURCE_URL = "https://www3.septa.org/developer/gtfs_public.zip"

# SEPTA ships two feeds inside the public bundle. The bus feed carries every
# surface + Metro route and is the only one with route_sort_order; the rail
# feed is Regional Rail and has neither that column nor the same end date.
BUS_FEED_MEMBER = "google_bus.zip"

# A truncated or half-published upstream feed should fail the build rather than
# ship a short route list. The real feed has ~175 routes.
MIN_ROUTES = 100

# Routes SEPTA publishes no vehicle positions for. Read from a committed file
# rather than a constant so the coverage pipeline can move the list without a
# code change, and so every move is a reviewable commit.
DEFAULT_OVERRIDES_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "realtime_overrides.json"
)
OVERRIDE_SOURCES = ("manual", "observed")

# Route color categories. SEPTA's palette names; the value is the key that
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

def download(url: str, dest: str, *, sleep=time.sleep) -> None:
    """Fetch url to dest, retrying with exponential backoff.

    The bundle is large, so it streams to disk rather than into memory; the
    retry policy itself lives in fetching, shared with the real-time sampler.
    """
    def once() -> None:
        with urllib.request.urlopen(url, timeout=300) as response:
            with open(dest, "wb") as handle:
                while chunk := response.read(1 << 20):
                    handle.write(chunk)

    fetching.with_retries(once, f"Download {url}", sleep=sleep)


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


def route_categories(
    feed: zipfile.ZipFile,
) -> tuple[dict[str, str], dict[str, list[str]]]:
    """Route id -> color category, and color category -> route ids.

    Ordering reuses route_list rather than re-deriving it, so route_list,
    route_category and category_routes always agree on route order.
    """
    routes = route_list(feed)

    color_by_route: dict[str, str] = {}
    for row in _read_csv(feed, "routes.txt"):
        route_id = (row.get("route_id") or "").strip()
        color_by_route[route_id] = (row.get("route_color") or "").strip().upper()

    route_category: dict[str, str] = {}
    category_routes: dict[str, list[str]] = {
        category: [] for category in sorted(set(CATEGORY_BY_COLOR.values()))
    }
    for route_id in routes:
        color = color_by_route[route_id]
        if not color:
            raise ValueError(f"route {route_id} has a blank route_color")
        if color not in CATEGORY_BY_COLOR:
            raise ValueError(
                f"route {route_id} has route_color {color!r}, which is not in "
                "CATEGORY_BY_COLOR; add it to septaclrs.csv"
            )
        category = CATEGORY_BY_COLOR[color]
        route_category[route_id] = category
        category_routes[category].append(route_id)

    assert set(route_category) == set(routes)
    assert sum(len(v) for v in category_routes.values()) == len(routes)

    return route_category, category_routes


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


def realtime_overrides(path: str) -> dict:
    """Read and validate realtime_overrides.json.

    Fails closed. This is the one place in the document where a wrong string
    silently changes app behavior, and the list is short and hand-maintained
    rather than an open set from upstream, so an unknown id is a bug and not a
    feed quirk. Route ids are checked against route_list by apply_overrides.
    """
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError as exc:
        raise ValueError(f"overrides file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"overrides file {path} is not valid JSON: {exc}") from exc

    if not isinstance(data, dict):
        raise ValueError(f"overrides file {path} must contain a JSON object")

    source = data.get("source")
    if source not in OVERRIDE_SOURCES:
        raise ValueError(
            f"overrides file {path} has source {source!r}; "
            f"expected one of {', '.join(OVERRIDE_SOURCES)}"
        )

    routes = data.get("no_vehicle_positions")
    if not isinstance(routes, list):
        raise ValueError(
            f"overrides file {path} has a non-list no_vehicle_positions"
        )
    for route_id in routes:
        if not isinstance(route_id, str):
            raise ValueError(
                f"overrides file {path} has a non-string route id: {route_id!r}"
            )

    return data


def apply_overrides(overrides: dict, routes: list[str], path: str) -> dict:
    """Build the realtime block, ordered to match route_list.

    Emitting in route_sort_order rather than file order keeps the output
    byte-stable however the file happens to be written on disk.
    """
    listed = set(overrides["no_vehicle_positions"])
    unknown = sorted(listed - set(routes))
    if unknown:
        raise ValueError(
            f"overrides file {path} names route ids absent from route_list: "
            f"{', '.join(unknown)}"
        )

    return {
        "source": overrides["source"],
        "observed_through": overrides.get("observed_through"),
        "overrides": {
            "no_vehicle_positions": [r for r in routes if r in listed],
        },
    }


def build(bundle_path: str, overrides_path: str = DEFAULT_OVERRIDES_PATH) -> dict:
    feed = open_bus_feed(bundle_path)
    route_category, category_routes = route_categories(feed)
    routes = route_list(feed)
    overrides = realtime_overrides(overrides_path)

    # realtime is a sibling of buses, not a child: it is a claim about SEPTA's
    # infrastructure, not about the GTFS feed, and it does not travel with the
    # feed's service window.
    return {
        "meta": feed_meta(feed),
        "buses": {
            "route_list": routes,
            "route_category": route_category,
            "category_routes": category_routes,
        },
        "realtime": apply_overrides(overrides, routes, overrides_path),
    }


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
    parser.add_argument(
        "--overrides",
        default=DEFAULT_OVERRIDES_PATH,
        help="realtime_overrides.json to read the deny-list from",
    )
    args = parser.parse_args(argv)

    bundle = args.gtfs_zip
    if bundle is None:
        os.makedirs(args.output_dir, exist_ok=True)
        bundle = os.path.join(args.output_dir, "gtfs_public.zip")
        print(f"Downloading {args.source_url}", file=sys.stderr)
        download(args.source_url, bundle)

    document = build(bundle, args.overrides)
    rolling, dated = write_outputs(document, args.output_dir)

    meta = document["meta"]
    buses = document["buses"]
    realtime = document["realtime"]
    denied = realtime["overrides"]["no_vehicle_positions"]
    print(
        f"{len(buses['route_list'])} routes in "
        f"{len(buses['category_routes'])} categories, "
        f"feed {meta['version']} ({meta['start_date']}–{meta['end_date']}), "
        f"{len(denied)} routes without vehicle positions ({realtime['source']})",
        file=sys.stderr,
    )
    print(f"Wrote {rolling} and {dated}", file=sys.stderr)
    # stdout carries the start date alone, so CI can capture it directly.
    print(meta["start_date"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
