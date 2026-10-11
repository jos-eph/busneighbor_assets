#!/usr/bin/env python3
"""Decide whether a freshly built septameta.json is safe to publish.

A published document that the app cannot parse is harmless: the app keeps the
copy it already has. The dangerous document is one that parses and offers
fewer routes. The app treats a route that is no longer offered as gone and
removes it from the rider's saved selection, and republishing a corrected
document does not put it back.

So every route an earlier document offers must still be offered by the
candidate, unless that exact set of removals has been approved by hand. The
earlier documents are the live copy on 'current' and the newest dated
release, because a device may be holding either; one that is missing or
unreadable is skipped, and having none readable at all refuses the publish.
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


def check(candidate, baselines: list | None,
          approved: set[str]) -> tuple[bool, list[str]]:
    """(safe, messages).

    baselines is every earlier document we could find: the live copy and the
    newest dated release. None means a genuine first publish, with no release
    of any kind yet. A candidate may not stop offering a route that ANY
    readable baseline offers. Devices may be holding either, so the union is
    what has to survive.
    """
    messages = []
    try:
        new = offered_routes(candidate)
    except ValueError as exc:
        return False, [f"candidate would be rejected by the app: {exc}"]

    if baselines is None:
        messages.append(f"first publish: {len(new)} routes offered")
        return True, messages

    old: list[str] = []
    readable = 0
    for name, baseline in baselines:
        try:
            if isinstance(baseline, _Unparseable):
                raise ValueError(baseline.reason)
            offered = offered_routes(baseline)
        except ValueError as exc:
            messages.append(f"baseline {name} is unusable ({exc}); ignoring it")
            continue
        readable += 1
        old.extend(r for r in offered if r not in old)

    # Devices still hold whatever they last parsed, so "nothing readable to
    # compare against" is not permission to publish anything at all.
    if readable == 0:
        messages.append(
            "no readable earlier septameta.json to compare against; refusing "
            "to publish without one")
        return False, messages

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
    group.add_argument("--published", action="append",
                       help="an earlier septameta.json; repeat for each one")
    group.add_argument("--first-publish", action="store_true",
                       help="no release of any kind exists yet")
    parser.add_argument("--approve-removals", default="",
                        help="comma-separated route ids approved for removal")
    args = parser.parse_args(argv)

    try:
        candidate = _load(args.candidate)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"::error::Candidate unreadable: {exc}", file=sys.stderr)
        return EXIT_UNSAFE

    baselines = None
    if args.published:
        baselines = []
        for path in args.published:
            try:
                baselines.append((path, _load(path)))
            except OSError as exc:
                baselines.append((path, _Unparseable(f"unreadable: {exc}")))
            except json.JSONDecodeError as exc:
                baselines.append((path, _Unparseable(f"not JSON: {exc}")))

    safe, messages = check(candidate, baselines,
                           parse_approval(args.approve_removals))
    level = "notice" if safe else "error"
    for message in messages:
        print(f"::{level}::{message}", file=sys.stderr)
    return EXIT_SAFE if safe else EXIT_UNSAFE


if __name__ == "__main__":
    sys.exit(main())
