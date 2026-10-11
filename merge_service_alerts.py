#!/usr/bin/env python3
"""Fold one service alert snapshot into its UTC day's archive file.

The sampler writes a snapshot every run. Eight full copies a day would repeat
nearly every alert eight times, so the day file holds each distinct alert and
detour once, with the first and last snapshot that saw it. An alert whose text
or periods change during the day appears once per version, under the same id.

`samples` lists every snapshot folded in. A detour-less entry
(`"detours": false`) means that snapshot's detour fetch failed, which is
different from SEPTA listing no detours.

Folding is idempotent: a snapshot already listed in `samples` is a no-op, so a
rerun of the publishing job cannot double-count.

Stdlib only; the publishing job installs nothing.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

SEEN_KEYS = ("first_seen", "last_seen")


def empty_day(date: str) -> dict:
    return {"date": date, "samples": [], "alerts": [], "detours": []}


def _content_key(entry: dict) -> str:
    return json.dumps({k: v for k, v in entry.items() if k not in SEEN_KEYS},
                      sort_keys=True, ensure_ascii=False)


def _fold(entries: list[dict], observed: list[dict], sampled_at: str) -> list[dict]:
    by_key = {_content_key(entry): dict(entry) for entry in entries}
    for item in observed:
        key = _content_key(item)
        entry = by_key.get(key)
        if entry is None:
            by_key[key] = {**item, "first_seen": sampled_at,
                           "last_seen": sampled_at}
        else:
            entry["first_seen"] = min(entry["first_seen"], sampled_at)
            entry["last_seen"] = max(entry["last_seen"], sampled_at)
    return sorted(by_key.values(), key=_content_key)


def merge(day: dict | None, snapshot: dict) -> dict:
    sampled_at = snapshot["sampled_at"]
    date = sampled_at[:10]
    day = empty_day(date) if day is None else day
    if day["date"] != date:
        raise ValueError(
            f"snapshot from {date} cannot go into the file for {day['date']}")
    if any(sample["sampled_at"] == sampled_at for sample in day["samples"]):
        return day

    detours = snapshot.get("detours")
    sample = {"sampled_at": sampled_at,
              "feed_timestamp": snapshot["feed_timestamp"]}
    if detours is None:
        sample["detours"] = False

    return {
        "date": date,
        "samples": sorted(day["samples"] + [sample],
                          key=lambda s: s["sampled_at"]),
        "alerts": _fold(day["alerts"], snapshot["alerts"], sampled_at),
        "detours": _fold(day["detours"], detours or [], sampled_at),
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
        handle.write(json.dumps(merged, separators=(",", ":"), sort_keys=True,
                                ensure_ascii=False) + "\n")
    print(f"{merged['date']}: {len(merged['samples'])} samples, "
          f"{len(merged['alerts'])} alert versions, "
          f"{len(merged['detours'])} detour versions", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
