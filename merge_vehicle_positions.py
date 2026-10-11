#!/usr/bin/env python3
"""Fold one vehicle positions snapshot into its UTC day's archive file.

The coverage sampler already fetches the vehicle feed every run; with
--positions-output it also writes every vehicle's position from that same
fetch. This appends that snapshot to the day file, so a day is one download
rather than eight.

Unlike alerts, positions change every sample, so there is nothing to
deduplicate: the day file is the snapshots in time order, under one shared
`fields` header. Folding is idempotent: a snapshot whose `sampled_at` is
already present is a no-op, so a rerun of the publishing job cannot
double-count.

Stdlib only; the publishing job installs nothing.
"""

from __future__ import annotations

import argparse
import json
import os
import sys


def merge(day: dict | None, snapshot: dict) -> dict:
    sampled_at = snapshot["sampled_at"]
    date = sampled_at[:10]
    fields = snapshot["fields"]
    if day is None:
        day = {"date": date, "fields": fields, "samples": []}
    if day["date"] != date:
        raise ValueError(
            f"snapshot from {date} cannot go into the file for {day['date']}")
    if day["fields"] != fields:
        raise ValueError(
            f"snapshot fields {fields} differ from the day's {day['fields']}")
    if any(s["sampled_at"] == sampled_at for s in day["samples"]):
        return day

    sample = {
        "sampled_at": sampled_at,
        "feed_timestamp": snapshot["feed_timestamp"],
        "vehicles": snapshot["vehicles"],
    }
    return {
        "date": date,
        "fields": fields,
        "samples": sorted(day["samples"] + [sample],
                          key=lambda s: s["sampled_at"]),
    }


def _read(path: str) -> dict:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--day", help="the day's existing file, if any")
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)

    snapshot = _read(args.snapshot)
    day = _read(args.day) if args.day else None
    try:
        merged = merge(day, snapshot)
    except (KeyError, ValueError) as exc:
        print(f"::error::Cannot merge snapshot: {exc}", file=sys.stderr)
        return 1

    parent = os.path.dirname(os.path.abspath(args.output))
    os.makedirs(parent, exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(merged, separators=(",", ":")) + "\n")
    vehicles = sum(len(s["vehicles"]) for s in merged["samples"])
    print(f"{merged['date']}: {len(merged['samples'])} samples, "
          f"{vehicles} positions", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
