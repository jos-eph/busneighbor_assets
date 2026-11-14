#!/usr/bin/env python3
"""Keep routes that are waiting for approval in the document being published.

A build that stops offering a route needs a person to approve it, because the
app drops that route from a rider's saved selection for good. That decision
should not hold back the rest of the build. So when removals are pending, the
document published is the candidate with those routes put back, and the
candidate itself is set aside for the approval step to publish unchanged.

Writes the candidate to --pure-dir, rewrites the files in --output-dir when
routes had to be kept, and prints `key=value` lines for the workflow:
pending (comma-separated route ids, possibly empty) and candidate_sha256.

Stdlib only, like the rest of the release workflow.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import shutil
import sys

import build_septa_meta
import check_septa_meta

EXIT_OK = 0
EXIT_FAILED = 1


def pending_removals(candidate, baselines: list | None,
                     approved: set[str]) -> list[str]:
    """Routes the candidate stops offering that nobody has approved yet.

    Empty when there is nothing to compare against or the candidate is one
    the app would reject: check_septa_meta.py refuses those on its own.
    An approval counts only when it matches the removals exactly.
    """
    if not baselines:
        return []
    try:
        offered = set(check_septa_meta.offered_routes(candidate))
    except ValueError:
        return []
    old, readable, _ = check_septa_meta.union_offered(baselines)
    if readable == 0:
        return []
    removed = [r for r in old if r not in offered]
    if removed and set(removed) == approved:
        return []
    return removed


def _insert_position(route_id: str, baseline_routes: list[str],
                     routes: list[str]) -> int:
    """Just after the nearest earlier neighbor that is still listed, so a
    kept route sits where riders last saw it; first when none is."""
    for neighbor in reversed(baseline_routes[:baseline_routes.index(route_id)]):
        if neighbor in routes:
            return routes.index(neighbor) + 1
    return 0


def carry_over(candidate: dict, baselines: list) -> dict:
    """The candidate, still offering every route a readable baseline offers.

    A route that left route_list goes back in, with its direction words. A
    route that joined the deny-list comes back off it. Everything else is the
    candidate's. Given the same inputs the result is the same bytes, so a
    week with nothing new compares equal to what is already published.
    """
    document = copy.deepcopy(candidate)
    routes = document["buses"]["route_list"]
    offered = set(check_septa_meta.offered_routes(candidate))
    reoffered = set()
    words = document.get("directions")

    for _, baseline in baselines:
        try:
            baseline_offered = check_septa_meta.offered_routes(baseline)
        except ValueError:
            continue
        baseline_routes = [r.strip() for r in baseline["buses"]["route_list"]]
        baseline_words = baseline.get("directions")
        for route_id in baseline_offered:
            if route_id in offered:
                continue
            offered.add(route_id)
            if route_id in routes:
                reoffered.add(route_id)
                continue
            routes.insert(_insert_position(route_id, baseline_routes, routes),
                          route_id)
            if (isinstance(words, dict) and isinstance(baseline_words, dict)
                    and route_id in baseline_words):
                words[route_id] = baseline_words[route_id]

    if reoffered:
        overrides = document["realtime"]["overrides"]
        overrides["no_vehicle_positions"] = [
            r for r in overrides["no_vehicle_positions"]
            if r.strip() not in reoffered]
    if isinstance(words, dict):
        order = {route_id: i for i, route_id in enumerate(routes)}
        document["directions"] = dict(sorted(
            words.items(), key=lambda item: order.get(item[0], len(order))))
    return document


def sha256_of(path: str) -> str:
    with open(path, "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True,
                        help="where build_septa_meta.py wrote its files")
    parser.add_argument("--pure-dir", required=True,
                        help="where to keep the candidate exactly as built")
    parser.add_argument("--published", action="append", default=[],
                        help="an earlier septameta.json; repeat for each one")
    parser.add_argument("--approve-removals", default="",
                        help="comma-separated route ids approved for removal")
    args = parser.parse_args(argv)

    rolling = os.path.join(args.output_dir, "septameta.json")
    try:
        with open(rolling, encoding="utf-8") as handle:
            candidate = json.load(handle)
        start_date = candidate["meta"]["start_date"]
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        print(f"::error::Candidate unreadable: {exc}", file=sys.stderr)
        return EXIT_FAILED

    os.makedirs(args.pure_dir, exist_ok=True)
    for name in ("septameta.json", f"septameta_{start_date}.json"):
        shutil.copyfile(os.path.join(args.output_dir, name),
                        os.path.join(args.pure_dir, name))

    baselines = check_septa_meta.load_baselines(args.published)
    approved = check_septa_meta.parse_approval(args.approve_removals)
    pending = pending_removals(candidate, baselines, approved)

    if pending:
        kept = carry_over(candidate, baselines)
        safe, messages = check_septa_meta.check(kept, baselines, set())
        if not safe:
            for message in messages:
                print(f"::error::{message}", file=sys.stderr)
            print("::error::Could not keep the pending routes in the "
                  "document; publishing nothing.", file=sys.stderr)
            return EXIT_FAILED
        build_septa_meta.write_outputs(kept, args.output_dir)
        print(f"::warning::Waiting for approval to stop offering "
              f"{', '.join(pending)}. Those routes stay in the published "
              f"document until then.", file=sys.stderr)
        if approved:
            print(f"::warning::approve_removals "
                  f"({','.join(sorted(approved))}) does not match the "
                  f"removals exactly, so it does not apply.", file=sys.stderr)

    print(f"pending={','.join(pending)}")
    print("candidate_sha256="
          f"{sha256_of(os.path.join(args.pure_dir, 'septameta.json'))}")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
