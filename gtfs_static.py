#!/usr/bin/env python3
"""Readable names for the ids in the vehicle feed, from SEPTA's static GTFS.

The real-time feed says route 42, direction 1, trip 879705, stop 311; the
static bundle says "Westbound", "Wycombe" and "Pine St & 3rd St". The
positions archive carries both, so a person reading it never needs a second
file open.

Three lookups, all from the bus feed inside the public bundle:

  * stops.txt       stop_id -> stop_name
  * trips.txt       trip_id -> trip_headsign
  * directions.txt  (route_id, direction_id) -> direction, e.g. "Northbound".
                    Not part of core GTFS; SEPTA publishes it. Absent means
                    no directions, not an error.

Names are a convenience. The sampler treats any failure here as a warning and
records positions without them.

Stdlib only.
"""

from __future__ import annotations

import argparse
import csv
import io
import os
import sys
import zipfile
from dataclasses import dataclass, field

import build_septa_meta


@dataclass(frozen=True)
class Names:
    stops: dict[str, str] = field(default_factory=dict)
    headsigns: dict[str, str] = field(default_factory=dict)
    directions: dict[tuple[str, str], str] = field(default_factory=dict)

    def stop(self, stop_id: str | None) -> str | None:
        return self.stops.get(stop_id) if stop_id else None

    def headsign(self, trip_id: str | None) -> str | None:
        return self.headsigns.get(trip_id) if trip_id else None

    def direction(self, route_id: str | None,
                  direction_id: int | None) -> str | None:
        if not route_id or direction_id is None:
            return None
        return self.directions.get((route_id, str(direction_id)))


def _rows(feed: zipfile.ZipFile, name: str):
    # utf-8-sig: SEPTA's GTFS files start with a BOM, which would otherwise
    # glue itself to the first column name.
    with feed.open(name) as raw:
        yield from csv.DictReader(io.TextIOWrapper(raw, encoding="utf-8-sig"))


def _lookup(feed: zipfile.ZipFile, name: str, key: str, value: str) -> dict:
    return {row[key]: row[value] for row in _rows(feed, name)
            if row.get(key) and row.get(value)}


def load(bundle_path: str) -> Names:
    """The three lookups from a public bundle or a single bus GTFS zip."""
    feed = build_septa_meta.open_bus_feed(bundle_path)
    directions = {}
    if "directions.txt" in feed.namelist():
        directions = {
            (row["route_id"], row["direction_id"]): row["direction"]
            for row in _rows(feed, "directions.txt")
            if row.get("route_id") and row.get("direction_id")
            and row.get("direction")
        }
    return Names(
        stops=_lookup(feed, "stops.txt", "stop_id", "stop_name"),
        headsigns=_lookup(feed, "trips.txt", "trip_id", "trip_headsign"),
        directions=directions,
    )


def download(dest: str, url: str = build_septa_meta.DEFAULT_SOURCE_URL) -> None:
    """Fetch the bundle to dest, which appears only once the fetch is whole.

    The workflow caches whatever sits at dest, so a download cut off halfway
    must never leave a truncated zip there for the rest of the day's runs.
    """
    parent = os.path.dirname(os.path.abspath(dest))
    os.makedirs(parent, exist_ok=True)
    partial = dest + ".part"
    build_septa_meta.download(url, partial)
    os.replace(partial, dest)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--download", metavar="PATH", required=True,
                        help="fetch the public GTFS bundle to PATH")
    args = parser.parse_args(argv)
    download(args.download)
    print(f"Wrote {args.download}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
