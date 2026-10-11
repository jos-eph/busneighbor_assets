#!/usr/bin/env python3
"""Snapshot SEPTA's service alerts and bus detours, one snapshot per run.

Two sources, recorded side by side because neither contains the other:

  * The GTFS-realtime alerts feed. Each alert is reduced to its id, text,
    routes, active periods and, where SEPTA sets them, effect, cause and
    severity. `description` is omitted when it repeats `header` word for word,
    which about half the feed does, and each route is listed once.
  * SEPTA's BusDetours listing, which gives each detour's direction and start
    and end locations. Records are kept verbatim except that a detour listed
    identically under several routes is recorded once with all its routes.

A failed detour fetch does not lose the alerts: the snapshot records
`detours: null` and the run still succeeds. Text is kept exactly as published,
HTML entities and stray whitespace included.

merge_service_alerts.py folds these snapshots into one file per UTC day.
"""

from __future__ import annotations

import argparse
import collections
import datetime
import json
import os
import sys
import time
import urllib.error

import fetching
import gtfs_rt

DETOURS_URL = "https://www3.septa.org/api/BusDetours/index.php"

# SEPTA tags everything "en" today. An untagged translation is the spec's way
# of saying "the default language", so it ranks alongside English.
PREFERRED_LANGUAGES = ("en", "")

DETOUR_FIELDS = (
    "route_direction",
    "reason",
    "start_location",
    "end_location",
    "start_date_time",
    "end_date_time",
    "current_message",
)


def utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def text_of(translated) -> str:
    """The English (or untagged) text of a TranslatedString, else the first."""
    translations = list(translated.translation)
    for translation in translations:
        if translation.language in PREFERRED_LANGUAGES:
            return translation.text
    return translations[0].text if translations else ""


def routes_of(alert) -> list[str]:
    """Every distinct route the alert names, directly or through a trip."""
    routes = set()
    for informed in alert.informed_entity:
        if informed.HasField("route_id"):
            routes.add(informed.route_id)
        if informed.HasField("trip") and informed.trip.HasField("route_id"):
            routes.add(informed.trip.route_id)
    routes.discard("")
    return sorted(routes)


def active_periods_of(alert) -> list[list[int | None]]:
    """[start, end] pairs in POSIX seconds; None where the bound is open."""
    return [
        [period.start if period.HasField("start") else None,
         period.end if period.HasField("end") else None]
        for period in alert.active_period
    ]


def enum_name(alert, field: str) -> str | None:
    """The enum's name, or None when unset or UNKNOWN_*, which say nothing."""
    if not alert.HasField(field):
        return None
    name = alert.DESCRIPTOR.fields_by_name[field].enum_type.values_by_number[
        getattr(alert, field)].name
    return None if name.startswith("UNKNOWN_") else name


def summarize_alert(entity) -> dict:
    alert = entity.alert
    header = text_of(alert.header_text)
    description = text_of(alert.description_text)
    summary = {
        "id": entity.id,
        "header": header,
        "routes": routes_of(alert),
        "active_periods": active_periods_of(alert),
    }
    if description and description != header:
        summary["description"] = description
    for field in ("effect", "cause", "severity_level"):
        value = enum_name(alert, field)
        if value is not None:
            summary[field] = value
    return summary


def summarize_alerts(feed) -> list[dict]:
    alerts = [
        summarize_alert(entity)
        for entity in feed.entity
        if entity.HasField("alert") and not entity.is_deleted
    ]
    alerts.sort(key=lambda alert: alert["id"])
    return alerts


def summarize_detours(listing) -> list[dict]:
    """Flatten BusDetours to one record per detour, routes grouped.

    Raises ValueError when the listing is not the shape we know, so a changed
    or broken endpoint reads as a failed fetch rather than as "no detours".
    """
    if not isinstance(listing, list):
        raise ValueError("BusDetours did not return a list")
    routes_by_detour: dict[str, set[str]] = collections.defaultdict(set)
    for route in listing:
        if not isinstance(route, dict) or not isinstance(
                route.get("route_info"), list):
            raise ValueError(f"unexpected BusDetours entry: {route!r:.200}")
        for info in route["route_info"]:
            if not isinstance(info, dict):
                raise ValueError(f"unexpected BusDetours detour: {info!r:.200}")
            record = {field: info.get(field) for field in DETOUR_FIELDS}
            key = json.dumps(record, sort_keys=True)
            routes_by_detour[key].add(str(route.get("route_id")))
    detours = []
    for key, routes in routes_by_detour.items():
        detour = json.loads(key)
        detour["routes"] = sorted(routes)
        detours.append(detour)
    detours.sort(key=lambda detour: json.dumps(detour, sort_keys=True))
    return detours


def fetch_detours(url: str, *, sleep=time.sleep) -> list[dict] | None:
    """The summarized detours, or None (with a warning) if they can't be had."""
    try:
        body = fetching.get_bytes(url, user_agent=gtfs_rt.FEED_USER_AGENT,
                                  sleep=sleep)
        return summarize_detours(json.loads(body))
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        print(f"::warning::Detours not recorded: {exc}", file=sys.stderr)
        return None


def write_document(document: dict, path: str) -> None:
    parent = os.path.dirname(os.path.abspath(path))
    os.makedirs(parent, exist_ok=True)
    payload = json.dumps(document, separators=(",", ":"), sort_keys=True,
                         ensure_ascii=False) + "\n"
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(payload)


def main(argv: list[str] | None = None, *, sleep=time.sleep) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--feed-url", default=gtfs_rt.SERVICE_ALERTS_URL)
    parser.add_argument("--detours-url", default=DETOURS_URL)
    parser.add_argument("--output", default=os.path.join("out", "alerts.json"))
    parser.add_argument(
        "--pb",
        help="parse this local .pb file instead of fetching (for debugging)",
    )
    parser.add_argument(
        "--detours-json",
        help="read detours from this local file instead of fetching",
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

    # A system this size always has some alert, so an empty feed is an outage.
    if len(feed.entity) == 0:
        print("Feed carried no entities; refusing to record a snapshot",
              file=sys.stderr)
        return 1

    if args.detours_json:
        with open(args.detours_json, encoding="utf-8") as handle:
            detours = summarize_detours(json.load(handle))
    else:
        print(f"Fetching {args.detours_url}", file=sys.stderr)
        detours = fetch_detours(args.detours_url, sleep=sleep)

    sampled_at = utc_now()
    document = {
        "sampled_at": sampled_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "feed_timestamp": feed.header.timestamp,
        "alerts": summarize_alerts(feed),
        "detours": detours,
    }
    write_document(document, args.output)

    detour_count = "no" if detours is None else len(detours)
    print(f"{len(document['alerts'])} alerts, {detour_count} detours, "
          f"feed timestamp {document['feed_timestamp']}", file=sys.stderr)
    print(f"Wrote {args.output}", file=sys.stderr)
    # stdout carries the snapshot's UTC date alone, for naming the day file.
    print(document["sampled_at"][:10])
    return 0


if __name__ == "__main__":
    sys.exit(main())
