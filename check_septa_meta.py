#!/usr/bin/env python3
"""Decide whether a freshly built septameta.json is safe to publish.

A published document that the app cannot parse is harmless: the app keeps the
copy it already has. The dangerous document is one that parses and offers
fewer routes. The app treats a route that is no longer offered as gone and
removes it from the rider's saved selection, and republishing a corrected
document does not put it back.

So every route the published document offers must still be offered by the
candidate, unless that exact set of removals has been approved by hand.
"Offered" is taken conservatively as route_list minus no_vehicle_positions:
both a route leaving route_list and a route joining the deny-list can take it
off a rider's screen.

Stdlib only, like the rest of the release workflow.
"""

from __future__ import annotations

import argparse
import json
import sys

EXIT_SAFE = 0
EXIT_UNSAFE = 1


class _Unparseable:
    def __init__(self, reason: str):
        self.reason = reason


def _string_list(value, what: str, *, required: bool) -> list[str]:
    """Mirror of the app's parsing: strings, trimmed, empties dropped."""
    if value is None and not required:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{what} must be a list")
    out = []
    for entry in value:
        if not isinstance(entry, str):
            raise ValueError(f"{what} entries must be strings, got {entry!r}")
        if entry.strip():
            out.append(entry.strip())
    return out


def _as_dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def offered_routes(document) -> list[str]:
    """The routes the app would offer, in order. Raises ValueError when the
    app itself would reject the document."""
    if not isinstance(document, dict):
        raise ValueError("top level must be a JSON object")
    route_list = _string_list(_as_dict(document.get("buses")).get("route_list"),
                              "buses.route_list", required=True)
    if not route_list:
        raise ValueError("buses.route_list must not be empty")
    denied = set(_string_list(
        _as_dict(_as_dict(document.get("realtime")).get("overrides"))
        .get("no_vehicle_positions"),
        "realtime.overrides.no_vehicle_positions", required=False))
    seen = set()
    offered = []
    for route_id in route_list:
        if route_id not in seen and route_id not in denied:
            seen.add(route_id)
            offered.append(route_id)
    return offered


def parse_approval(raw: str | None) -> set[str]:
    return {r.strip() for r in (raw or "").split(",") if r.strip()}


def check(candidate, published, approved: set[str]) -> tuple[bool, list[str]]:
    """(safe, messages). published is None only for a first publish."""
    messages = []
    try:
        new = offered_routes(candidate)
    except ValueError as exc:
        return False, [f"candidate would be rejected by the app: {exc}"]

    if published is None:
        messages.append(f"first publish: {len(new)} routes offered")
        return True, messages

    try:
        if isinstance(published, _Unparseable):
            raise ValueError(published.reason)
        old = offered_routes(published)
    except ValueError as exc:
        # The live copy is already unusable, so the app is running on its
        # cache. Replacing it cannot remove anything the app currently offers
        # from this document.
        messages.append(f"published document is unparseable ({exc}); "
                        f"replacing it")
        return True, messages

    new_set = set(new)
    removed = [r for r in old if r not in new_set]
    added = [r for r in new if r not in set(old)]
    if added:
        messages.append(f"routes newly offered: {', '.join(added)}")

    if not removed:
        messages.append(f"no routes removed; {len(new)} offered")
        return True, messages

    if set(removed) == approved:
        messages.append(f"removals approved: {', '.join(removed)}")
        return True, messages

    messages.append(
        f"would stop offering {len(removed)} route(s): {', '.join(removed)}. "
        f"Riders who saved these lose them permanently. If SEPTA really "
        f"retired them, rerun with approve_removals set to exactly "
        f"'{','.join(removed)}'."
    )
    if approved:
        messages.append(
            f"approval given ({','.join(sorted(approved))}) does not match "
            f"the removals exactly, so it does not apply")
    return False, messages


def _load(path: str):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", required=True)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--published",
                       help="the septameta.json currently on the release")
    group.add_argument("--first-publish", action="store_true",
                       help="the release has no septameta.json yet")
    parser.add_argument("--approve-removals", default="",
                        help="comma-separated route ids approved for removal")
    args = parser.parse_args(argv)

    try:
        candidate = _load(args.candidate)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"::error::Candidate unreadable: {exc}", file=sys.stderr)
        return EXIT_UNSAFE

    published = None
    if args.published:
        try:
            published = _load(args.published)
        except OSError as exc:
            print(f"::error::Published copy unreadable: {exc}", file=sys.stderr)
            return EXIT_UNSAFE
        except json.JSONDecodeError as exc:
            published = _Unparseable(f"not JSON: {exc}")

    safe, messages = check(candidate, published,
                           parse_approval(args.approve_removals))
    level = "notice" if safe else "error"
    for message in messages:
        print(f"::{level}::{message}", file=sys.stderr)
    return EXIT_SAFE if safe else EXIT_UNSAFE


if __name__ == "__main__":
    sys.exit(main())
