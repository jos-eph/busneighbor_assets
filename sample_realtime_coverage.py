#!/usr/bin/env python3
"""Sample SEPTA's real-time vehicle positions and record per-route counts.

One run is one observation of which routes SEPTA is currently publishing
vehicle positions for. GTFS has no field for that fact, so we measure it: the
aggregator folds a day of these samples into a rolling window, and a route that
never appears across the window is a route the app should degrade honestly
rather than showing an empty map.

Output is sparse — only routes actually seen. Zeros come later, from
route_list, so the deny-list is always computed against the current feed rather
than against whatever the route list looked like when the window opened.
"""

from __future__ import annotations

import argparse
import collections
import datetime
import json
import os
import sys
import time

import gtfs_rt


def utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def summarize(feed, *, feed_url: str, body_bytes: int,
              sampled_at: datetime.datetime) -> dict:
    """Reduce a parsed feed to the sample document.

    An entity counts toward route R when it has a vehicle, whose trip carries a
    non-empty route_id equal to R, and whose position is one we are willing to
    count. Entities failing any of those still appear in `entities`, so the gap
    between the totals stays visible instead of being silently absorbed.
    """
    positions_by_route: collections.Counter[str] = collections.Counter()
    entities_with_valid_position = 0

    for entity in feed.entity:
        if not entity.HasField("vehicle"):
            continue
        vehicle = entity.vehicle
        if not gtfs_rt.has_valid_position(vehicle):
            continue
        entities_with_valid_position += 1
        route_id = gtfs_rt.route_id_of(vehicle)
        if route_id:
            positions_by_route[route_id] += 1

    return {
        "sampled_at": sampled_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "feed_timestamp": feed.header.timestamp,
        "feed_url": feed_url,
        "bytes": body_bytes,
        "entities": len(feed.entity),
        "entities_with_valid_position": entities_with_valid_position,
        "distinct_routes": len(positions_by_route),
        "positions_by_route": dict(sorted(positions_by_route.items())),
    }


def write_sample(document: dict, path: str) -> None:
    parent = os.path.dirname(os.path.abspath(path))
    os.makedirs(parent, exist_ok=True)
    # Sorted keys and a trailing newline: two runs over the same feed must
    # produce the same bytes, which is what lets the aggregator dedupe.
    payload = json.dumps(document, indent=2, sort_keys=True) + "\n"
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(payload)


def main(argv: list[str] | None = None, *, sleep=time.sleep) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--feed-url", default=gtfs_rt.VEHICLE_POSITION_URL)
    parser.add_argument("--output", default=os.path.join("out", "sample.json"))
    parser.add_argument(
        "--pb",
        help="parse this local .pb file instead of fetching (for debugging)",
    )
    args = parser.parse_args(argv)

    if args.pb:
        with open(args.pb, "rb") as handle:
            body = handle.read()
    else:
        print(f"Fetching {args.feed_url}", file=sys.stderr)
        body = gtfs_rt.fetch_feed_bytes(args.feed_url, sleep=sleep)

    try:
        feed = gtfs_rt.parse_feed(body)
    except gtfs_rt.DecodeError as exc:
        print(f"Feed is not parseable: {exc}", file=sys.stderr)
        return 1

    document = summarize(
        feed,
        feed_url=args.pb or args.feed_url,
        body_bytes=len(body),
        sampled_at=utc_now(),
    )

    # An empty feed is an outage, not a measurement. Recording it would let a
    # dead feed read as "no route is tracked" and drag every count down.
    if document["entities"] == 0:
        print("Feed carried no entities; refusing to record a sample",
              file=sys.stderr)
        return 1

    # A low route count is NOT a failure. At 04:00 local, "few routes" is the
    # correct answer, and a sampler that refused to record quiet hours would
    # bias every count it produces toward the deny-list.
    write_sample(document, args.output)

    print(
        f"{document['entities']} entities, "
        f"{document['entities_with_valid_position']} with a valid position, "
        f"{document['distinct_routes']} routes, "
        f"feed timestamp {document['feed_timestamp']}",
        file=sys.stderr,
    )
    print(f"Wrote {args.output}", file=sys.stderr)
    # stdout carries the sample's own UTC date alone, so the workflow can name
    # the artifact from it and a run straddling midnight files itself
    # consistently. Mirrors build_septa_meta.py printing the feed start date.
    print(document["sampled_at"][:10])
    return 0


if __name__ == "__main__":
    sys.exit(main())
