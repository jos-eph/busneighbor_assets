#!/usr/bin/env python3
"""Fold one vehicle positions snapshot into its UTC day's CSV file.

The coverage sampler already fetches the vehicle feed every run; with
--positions-output it also writes every vehicle's position from that same
fetch. This appends that snapshot to the day file, so a day is one download
rather than eight.

The day file is a plain CSV a person can open in a spreadsheet: one row per
vehicle per sample, under a header of named columns. Against the snapshot it
changes three things, each for a reader rather than a parser:

  * Epoch seconds become UTC ISO times (feed_time, reported_at).
  * direction, trip_headsign and stop_name sit beside the ids they name,
    when the sampler had the static GTFS bundle to look them up.
  * report_age_s, sampled_at minus reported_at, makes a stale vehicle obvious
    without arithmetic.
  * Rows run route by route (numbers in numeric order, then letters), so a
    route's buses sit together. Vehicles without a trip go last.

A blank cell means the feed did not say. Folding is idempotent: a snapshot
whose sampled_at is already present is a no-op, so a rerun of the publishing
job cannot double-count.

Stdlib only; the publishing job installs nothing.
"""

from __future__ import annotations

import argparse
import csv
import datetime
import io
import json
import os
import sys

COLUMNS = (
    "sampled_at",
    "feed_time",
    "route_id",
    "direction_id",
    "direction",
    "vehicle_id",
    "trip_id",
    "trip_headsign",
    "lat",
    "lon",
    "bearing_deg",
    "speed_mps",
    "reported_at",
    "report_age_s",
    "stop_id",
    "stop_name",
    "stop_sequence",
    "status",
)

# Day-file column <- snapshot field, for the columns copied as they are.
COPIED = {
    "route_id": "route_id",
    "direction_id": "direction_id",
    "vehicle_id": "vehicle_id",
    "trip_id": "trip_id",
    "lat": "lat",
    "lon": "lon",
    "bearing_deg": "bearing",
    "speed_mps": "speed",
    "stop_id": "stop_id",
    "stop_sequence": "current_stop_sequence",
    "status": "current_status",
}
REQUIRED_FIELDS = frozenset(COPIED.values()) | {"timestamp"}

# Names the sampler adds from the static GTFS bundle. Blank when a snapshot
# was taken without one, or predates them.
NAMES = {
    "direction": "direction",
    "trip_headsign": "trip_headsign",
    "stop_name": "stop_name",
}

_ISO = "%Y-%m-%dT%H:%M:%SZ"


def _iso(epoch: int | None) -> str:
    if epoch is None:
        return ""
    return datetime.datetime.fromtimestamp(
        epoch, datetime.timezone.utc).strftime(_ISO)


def _epoch(iso: str) -> int:
    return int(datetime.datetime.strptime(iso, _ISO).replace(
        tzinfo=datetime.timezone.utc).timestamp())


def _cell(value) -> str:
    return "" if value is None else str(value)


def _number_first(value: str) -> tuple:
    """Sort key: numbers in numeric order, then text, then blanks."""
    if not value:
        return (2, 0, "")
    if value.isdigit():
        return (0, int(value), value)
    return (1, 0, value)


def _row_order(row: dict) -> tuple:
    return (row["sampled_at"], _number_first(row["route_id"]),
            row["direction_id"], _number_first(row["vehicle_id"]))


def snapshot_rows(snapshot: dict) -> list[dict]:
    """The snapshot as day-file rows, every value a string."""
    fields = snapshot["fields"]
    missing = REQUIRED_FIELDS - set(fields)
    if missing:
        raise ValueError(f"snapshot fields lack {sorted(missing)}")
    sampled_at = snapshot["sampled_at"]
    sampled_epoch = _epoch(sampled_at)
    feed_time = _iso(snapshot["feed_timestamp"])
    rows = []
    for vehicle in snapshot["vehicles"]:
        named = dict(zip(fields, vehicle))
        reported = named["timestamp"]
        values = {column: _cell(named[field]) for column, field in COPIED.items()}
        values.update({column: _cell(named.get(field))
                       for column, field in NAMES.items()})
        values.update(
            sampled_at=sampled_at,
            feed_time=feed_time,
            reported_at=_iso(reported),
            report_age_s="" if reported is None else str(sampled_epoch - reported),
        )
        rows.append({column: values[column] for column in COLUMNS})
    return rows


def parse_day(text: str) -> list[dict]:
    reader = csv.DictReader(io.StringIO(text))
    if tuple(reader.fieldnames or ()) != COLUMNS:
        raise ValueError(
            f"day file columns {reader.fieldnames} are not {list(COLUMNS)}")
    return list(reader)


def merge(day_rows: list[dict] | None, snapshot: dict) -> list[dict]:
    """day_rows with the snapshot folded in, in row order."""
    sampled_at = snapshot["sampled_at"]
    day_rows = day_rows or []
    if day_rows and day_rows[0]["sampled_at"][:10] != sampled_at[:10]:
        raise ValueError(
            f"snapshot from {sampled_at[:10]} cannot go into the file for "
            f"{day_rows[0]['sampled_at'][:10]}")
    if any(row["sampled_at"] == sampled_at for row in day_rows):
        return day_rows
    return sorted(day_rows + snapshot_rows(snapshot), key=_row_order)


def render(rows: list[dict]) -> str:
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=COLUMNS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return out.getvalue()


def _read(path: str) -> str:
    with open(path, encoding="utf-8", newline="") as handle:
        return handle.read()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--day", help="the day's existing file, if any")
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)

    snapshot = json.loads(_read(args.snapshot))
    try:
        day = parse_day(_read(args.day)) if args.day else None
        merged = merge(day, snapshot)
    except (KeyError, ValueError) as exc:
        print(f"::error::Cannot merge snapshot: {exc}", file=sys.stderr)
        return 1

    parent = os.path.dirname(os.path.abspath(args.output))
    os.makedirs(parent, exist_ok=True)
    with open(args.output, "w", encoding="utf-8", newline="") as handle:
        handle.write(render(merged))
    samples = len({row["sampled_at"] for row in merged})
    print(f"{snapshot['sampled_at'][:10]}: {samples} samples, "
          f"{len(merged)} positions", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
