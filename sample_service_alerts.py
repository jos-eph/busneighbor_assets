#!/usr/bin/env python3
"""Archive the text of SEPTA's service alerts, one snapshot per run.

Each alert is reduced to its id, its text and the routes it names. Everything
else in the feed (active periods, cause, effect, the same URL on every alert)
is left out. The document is meant to be read back by a later job, not by the
app.

Two rules keep the snapshot small without losing anything:

  * `description` is omitted when it repeats `header` word for word, which
    about half the feed does (every trip cancellation, for a start).
  * `routes` lists each route once, however many informed entities name it.

Alerts scoped only to a trip or a stop carry no route of their own, so their
`routes` is empty. Text is kept exactly as published, HTML entities included.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
import time

import gtfs_rt

# SEPTA tags everything "en" today. An untagged translation is the spec's way
# of saying "the default language", so it ranks alongside English.
PREFERRED_LANGUAGES = ("en", "")


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


def summarize_alert(entity) -> dict:
    alert = entity.alert
    header = text_of(alert.header_text)
    description = text_of(alert.description_text)
    summary = {"id": entity.id, "header": header, "routes": routes_of(alert)}
    if description and description != header:
        summary["description"] = description
    return summary


def summarize(feed, *, sampled_at: datetime.datetime) -> dict:
    alerts = [
        summarize_alert(entity)
        for entity in feed.entity
        if entity.HasField("alert") and not entity.is_deleted
    ]
    alerts.sort(key=lambda alert: alert["id"])
    return {
        "sampled_at": sampled_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "feed_timestamp": feed.header.timestamp,
        "alerts": alerts,
    }


def write_document(document: dict, path: str) -> None:
    parent = os.path.dirname(os.path.abspath(path))
    os.makedirs(parent, exist_ok=True)
    # Compact: this is an archive read by machines, and indentation alone
    # would add a third to its size.
    payload = json.dumps(document, separators=(",", ":"), sort_keys=True,
                         ensure_ascii=False) + "\n"
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(payload)


def main(argv: list[str] | None = None, *, sleep=time.sleep) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--feed-url", default=gtfs_rt.SERVICE_ALERTS_URL)
    parser.add_argument("--output", default=os.path.join("out", "alerts.json"))
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

    # A day with no alerts is possible but implausible for a system this size,
    # and an archive entry claiming one would be wrong far more often than not.
    if len(feed.entity) == 0:
        print("Feed carried no entities; refusing to record a snapshot",
              file=sys.stderr)
        return 1

    document = summarize(feed, sampled_at=utc_now())
    write_document(document, args.output)

    print(f"{len(document['alerts'])} alerts, "
          f"feed timestamp {document['feed_timestamp']}", file=sys.stderr)
    print(f"Wrote {args.output}", file=sys.stderr)
    # stdout carries the snapshot's UTC date alone, for naming the asset.
    print(document["sampled_at"][:10])
    return 0


if __name__ == "__main__":
    sys.exit(main())
