#!/usr/bin/env python3
"""Build route_stops.json: the name and position of every stop the routes use.

septashapes.json lists each direction's stops by id only. The route pages need
names and positions too: for stop lists, end points, main streets, and which
routes connect. This reads them from the same bundle, so both files describe one
GTFS version.

    stops          stop_id -> [name, lat, lon], for every stop that a route's
                   route_stops.txt lists and stops.txt defines. Names exactly
                   as the feed writes them. The feed lists a few stops it
                   doesn't define; those are left out.
    rail_stations  [name, lat, lon] for each Regional Rail station, from the
                   rail feed in the same bundle. Metro stations are already
                   stops in the bus feed.

The output has no build time, so an unchanged feed gives identical bytes.

Stdlib only, so CI needs no dependency install.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import sys
import zipfile

import build_septa_meta
import build_septa_shapes

SCHEMA_VERSION = 1
OUTPUT_NAME = "route_stops.json"
RAIL_FEED_MEMBER = "google_rail.zip"

# Five decimal places is about a meter: finer than any use the pages make.
COORDINATE_DECIMALS = 5

# A few undefined stops are normal for this feed. Many means a broken bundle.
MAX_MISSING_FRACTION = 0.01

# GTFS location_type 1 is a station that groups platforms.
STATION_LOCATION_TYPE = "1"


def _position(row: dict) -> tuple[float, float]:
    return (round(float(row["stop_lat"]), COORDINATE_DECIMALS),
            round(float(row["stop_lon"]), COORDINATE_DECIMALS))


def route_stops(feed: zipfile.ZipFile) -> dict[str, list]:
    """[name, lat, lon] for each stop a route uses, keyed by stop id."""
    used = {stop for stops in build_septa_shapes.stops_by_direction(feed).values()
            for stop in stops}
    found = {}
    for row in build_septa_shapes._rows(feed, "stops.txt"):
        stop_id = row["stop_id"].strip()
        if stop_id in used:
            found[stop_id] = [row["stop_name"].strip(), *_position(row)]
    missing = sorted(used - found.keys())
    if len(missing) > MAX_MISSING_FRACTION * len(used):
        raise ValueError(f"{len(missing)} of {len(used)} stops in route_stops.txt are missing "
                         f"from stops.txt: {missing[:10]}")
    if missing:
        print(f"skipped {len(missing)} stops that stops.txt doesn't define: {missing[:10]}",
              file=sys.stderr)
    return dict(sorted(found.items()))


def rail_stations(bundle: zipfile.ZipFile) -> list[list]:
    """[name, lat, lon] per Regional Rail station, sorted by name.

    Uses the station rows when the feed has them, otherwise every stop: a
    feed without stations lists each station once as a plain stop.
    """
    if RAIL_FEED_MEMBER not in bundle.namelist():
        raise ValueError(f"bundle has no {RAIL_FEED_MEMBER}")
    rail = zipfile.ZipFile(io.BytesIO(bundle.read(RAIL_FEED_MEMBER)))
    rows = list(build_septa_shapes._rows(rail, "stops.txt"))
    stations = [r for r in rows if (r.get("location_type") or "").strip() == STATION_LOCATION_TYPE]
    chosen = stations or rows
    unique = {(r["stop_name"].strip(), *_position(r)) for r in chosen}
    return [list(station) for station in sorted(unique)]


def build(bundle_path: str) -> dict:
    feed = build_septa_meta.open_bus_feed(bundle_path)
    return {
        "v": SCHEMA_VERSION,
        "gtfs_version": build_septa_meta.feed_meta(feed)["version"],
        "stops": route_stops(feed),
        "rail_stations": rail_stations(zipfile.ZipFile(bundle_path)),
    }


def serialize(document: dict) -> bytes:
    return (json.dumps(document, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gtfs-zip", required=True, help="the SEPTA public bundle")
    parser.add_argument("--output-dir", default="out")
    args = parser.parse_args(argv)

    document = build(args.gtfs_zip)
    os.makedirs(args.output_dir, exist_ok=True)
    path = os.path.join(args.output_dir, OUTPUT_NAME)
    with open(path, "wb") as handle:
        handle.write(serialize(document))
    print(f"{len(document['stops'])} stops, {len(document['rail_stations'])} rail stations, "
          f"feed {document['gtfs_version']}", file=sys.stderr)
    print(f"Wrote {path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
