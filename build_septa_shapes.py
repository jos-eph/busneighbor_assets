#!/usr/bin/env python3
"""Build septashapes.json — the regular line of every bus route, per direction.

Reads the bus feed from the SEPTA public GTFS bundle and writes, for each
route and direction:

    primary   the shape most trips use, as a Google encoded polyline
    variants  every other shape a trip uses (branches, short turns)
    stops     stop ids in route order, from route_stops.txt
    name      the direction's name from directions.txt, e.g. "Northbound"

The app draws `primary` and checks bus positions against every shape, so a bus
on a branch trip is not mistaken for one off its route.

Shapes are simplified with Douglas-Peucker at 5 m before encoding. The app's
off-route check works at 50 m, so the simplification is invisible to it.

The schema is a contract with its readers: a change bumps SCHEMA_VERSION.

Stdlib only, so CI needs no dependency install.
"""

from __future__ import annotations

import argparse
import collections
import csv
import gzip
import io
import json
import math
import os
import sys
import zipfile
from datetime import datetime, timezone

import build_septa_meta

SCHEMA_VERSION = 1
SIMPLIFY_METERS = 5.0
POLYLINE_PRECISION = 5

OUTPUT_NAME = "septashapes.json"

# Meters per degree of latitude, and of longitude at the equator. The
# equirectangular approximation is well under a meter off across one route.
METERS_PER_DEGREE_LAT = 110_540.0
METERS_PER_DEGREE_LON = 111_320.0


def _rows(feed: zipfile.ZipFile, name: str):
    # utf-8-sig: SEPTA's GTFS text files carry a BOM, which would otherwise end
    # up glued to the first column name.
    with feed.open(name) as raw:
        yield from csv.DictReader(io.TextIOWrapper(raw, encoding="utf-8-sig"))


def shape_usage(feed: zipfile.ZipFile) -> dict[tuple[str, int], collections.Counter]:
    """Trip counts per shape, keyed by (route_id, direction_id)."""
    usage: dict[tuple[str, int], collections.Counter] = collections.defaultdict(
        collections.Counter
    )
    for row in _rows(feed, "trips.txt"):
        route_id = (row.get("route_id") or "").strip()
        direction = (row.get("direction_id") or "").strip()
        shape_id = (row.get("shape_id") or "").strip()
        if route_id and direction and shape_id:
            usage[(route_id, int(direction))][shape_id] += 1
    return usage


def ranked_shapes(counts: collections.Counter) -> list[str]:
    """Most-used first; ties broken by shape id so the output is stable."""
    return [shape for shape, _ in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))]


def shape_points(
    feed: zipfile.ZipFile, wanted: set[str]
) -> dict[str, list[tuple[float, float]]]:
    """(lat, lon) points for each wanted shape, in shape_pt_sequence order."""
    sequenced: dict[str, list[tuple[int, float, float]]] = collections.defaultdict(list)
    for row in _rows(feed, "shapes.txt"):
        shape_id = row["shape_id"]
        if shape_id in wanted:
            sequenced[shape_id].append((
                int(row["shape_pt_sequence"]),
                float(row["shape_pt_lat"]),
                float(row["shape_pt_lon"]),
            ))
    missing = sorted(wanted - sequenced.keys())
    if missing:
        raise ValueError(f"trips.txt uses shapes absent from shapes.txt: {missing[:10]}")
    return {
        shape_id: [(lat, lon) for _, lat, lon in sorted(points)]
        for shape_id, points in sequenced.items()
    }


def _offset_meters(point, origin, lon_scale) -> tuple[float, float]:
    return (
        (point[1] - origin[1]) * lon_scale,
        (point[0] - origin[0]) * METERS_PER_DEGREE_LAT,
    )


def _farthest_from_chord(points, first, last, lon_scale) -> tuple[int, float]:
    """Index and distance in meters of the point farthest from first→last."""
    dx, dy = _offset_meters(points[last], points[first], lon_scale)
    length = math.hypot(dx, dy)
    index, farthest = first, 0.0
    for i in range(first + 1, last):
        px, py = _offset_meters(points[i], points[first], lon_scale)
        if length == 0:
            distance = math.hypot(px, py)
        else:
            distance = abs(dy * px - dx * py) / length
        if distance > farthest:
            index, farthest = i, distance
    return index, farthest


def simplify(points: list[tuple[float, float]], tolerance_m: float) -> list[tuple[float, float]]:
    """Douglas-Peucker, iterative so a long shape can't exhaust the stack."""
    if len(points) < 3:
        return list(points)
    lon_scale = math.cos(math.radians(points[0][0])) * METERS_PER_DEGREE_LON
    keep = {0, len(points) - 1}
    stack = [(0, len(points) - 1)]
    while stack:
        first, last = stack.pop()
        if last - first < 2:
            continue
        index, distance = _farthest_from_chord(points, first, last, lon_scale)
        if distance > tolerance_m:
            keep.add(index)
            stack.append((first, index))
            stack.append((index, last))
    return [points[i] for i in sorted(keep)]


def _encode_value(delta: int) -> str:
    value = ~(delta << 1) if delta < 0 else delta << 1
    chunks = []
    while value >= 0x20:
        chunks.append(chr((0x20 | (value & 0x1F)) + 63))
        value >>= 5
    chunks.append(chr(value + 63))
    return "".join(chunks)


def encode_polyline(points: list[tuple[float, float]], precision: int = POLYLINE_PRECISION) -> str:
    """Google's encoded polyline algorithm format."""
    factor = 10 ** precision
    out = []
    previous_lat = previous_lon = 0
    for lat, lon in points:
        scaled_lat, scaled_lon = round(lat * factor), round(lon * factor)
        out.append(_encode_value(scaled_lat - previous_lat))
        out.append(_encode_value(scaled_lon - previous_lon))
        previous_lat, previous_lon = scaled_lat, scaled_lon
    return "".join(out)


def stops_by_direction(feed: zipfile.ZipFile) -> dict[tuple[str, int], list[str]]:
    """Stop ids per (route_id, direction_id), in route_stop_sort_order."""
    ordered: dict[tuple[str, int], list[tuple[int, str]]] = collections.defaultdict(list)
    for row in _rows(feed, "route_stops.txt"):
        key = (row["route_id"], int(row["direction_id"]))
        ordered[key].append((int(row["route_stop_sort_order"]), row["stop_id"]))
    return {key: [stop for _, stop in sorted(rows)] for key, rows in ordered.items()}


# One reader for directions.txt, shared with septameta.json's direction words.
direction_names = build_septa_meta.direction_names


def _direction_entry(key, counts, points, stops, names) -> dict:
    primary, *variants = ranked_shapes(counts)

    def encoded(shape_id: str) -> str:
        return encode_polyline(simplify(points[shape_id], SIMPLIFY_METERS))

    lines = [encoded(primary)]
    for shape_id in variants:
        # Distinct shapes can encode identically once simplified and rounded.
        line = encoded(shape_id)
        if line not in lines:
            lines.append(line)
    return {
        "dir": key[1],
        "name": names.get(key, ""),
        "primary": lines[0],
        "variants": lines[1:],
        "stops": stops.get(key, []),
    }


def build(bundle_path: str, generated: datetime) -> dict:
    feed = build_septa_meta.open_bus_feed(bundle_path)
    route_order = build_septa_meta.route_list(feed)
    usage = shape_usage(feed)
    wanted = {shape for counts in usage.values() for shape in counts}
    points = shape_points(feed, wanted)
    stops = stops_by_direction(feed)
    names = direction_names(feed)

    routes = {}
    for route_id in route_order:
        keys = sorted(key for key in usage if key[0] == route_id)
        if keys:
            routes[route_id] = [
                _direction_entry(key, usage[key], points, stops, names) for key in keys
            ]

    if len(routes) < build_septa_meta.MIN_ROUTES:
        raise ValueError(
            f"only {len(routes)} routes have shapes, below the "
            f"{build_septa_meta.MIN_ROUTES} sanity floor; refusing to publish "
            "a possibly truncated feed"
        )

    return {
        "v": SCHEMA_VERSION,
        "gtfs_version": build_septa_meta.feed_meta(feed)["version"],
        "generated": generated.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "routes": routes,
    }


def serialize(document: dict) -> bytes:
    # Compact: readers parse the raw file, so whitespace is pure cost.
    return (json.dumps(document, separators=(",", ":")) + "\n").encode("utf-8")


def same_content(a: dict, b: dict) -> bool:
    """Equal apart from `generated`, which differs on every build."""
    def strip(document: dict) -> dict:
        return {k: v for k, v in document.items() if k != "generated"}

    return strip(a) == strip(b)


def _load(path: str) -> dict:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default="out")
    parser.add_argument(
        "--source-url",
        default=build_septa_meta.DEFAULT_SOURCE_URL,
        help="SEPTA GTFS bundle URL (ignored when --gtfs-zip is given)",
    )
    parser.add_argument("--gtfs-zip", help="use this local bundle instead of downloading")
    parser.add_argument(
        "--compare",
        nargs=2,
        metavar=("A", "B"),
        help="exit 0 if two septashapes.json files match apart from `generated`, else 1",
    )
    args = parser.parse_args(argv)

    if args.compare:
        return 0 if same_content(*(_load(path) for path in args.compare)) else 1

    bundle = args.gtfs_zip
    if bundle is None:
        os.makedirs(args.output_dir, exist_ok=True)
        bundle = os.path.join(args.output_dir, "gtfs_public.zip")
        print(f"Downloading {args.source_url}", file=sys.stderr)
        build_septa_meta.download(args.source_url, bundle)

    document = build(bundle, datetime.now(timezone.utc))
    payload = serialize(document)
    os.makedirs(args.output_dir, exist_ok=True)
    path = os.path.join(args.output_dir, OUTPUT_NAME)
    with open(path, "wb") as handle:
        handle.write(payload)

    directions = sum(len(entries) for entries in document["routes"].values())
    variants = sum(
        len(entry["variants"]) for entries in document["routes"].values() for entry in entries
    )
    print(
        f"{len(document['routes'])} routes, {directions} directions, {variants} variants, "
        f"feed {document['gtfs_version']}: {len(payload) // 1024} KB raw, "
        f"{len(gzip.compress(payload)) // 1024} KB gzipped",
        file=sys.stderr,
    )
    print(f"Wrote {path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
