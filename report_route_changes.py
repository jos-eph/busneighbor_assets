#!/usr/bin/env python3
"""Describe the route changes in a freshly built septameta.json.

Writes a short Markdown report for the person who approves removals: which
routes were added, which would stop being offered, what each is called, and
how often the vehicle feed has carried it lately. Also writes the route names
it used, so the next report can still name a route after it leaves the feed.

The report informs; it decides nothing. Missing names or coverage show as
"unknown" and never fail the run.

Stdlib only, like the rest of the release workflow.
"""

from __future__ import annotations

import argparse
import json
import sys

import build_septa_meta
import check_septa_meta

ADDED = "Added"
REMOVED = "Removed"
HIDDEN = "Joins the no-vehicle list"
UNKNOWN = "unknown"


def names_to_keep(route_ids: list[str], new: dict[str, str],
                  previous: dict[str, str]) -> dict[str, str]:
    """Names for the listed routes; a route no longer in the feed keeps the
    name it had."""
    return {r: new.get(r) or previous[r]
            for r in route_ids if new.get(r) or previous.get(r)}


def route_changes(candidate, baselines: list) -> list[tuple[str, str]]:
    """(route_id, kind) for every change in what the app would offer."""
    offered = check_septa_meta.offered_routes(candidate)
    listed = set(candidate["buses"]["route_list"])
    old, _, _ = check_septa_meta.union_offered(baselines)
    changes = [(r, HIDDEN if r in listed else REMOVED)
               for r in old if r not in set(offered)]
    changes.extend((r, ADDED) for r in offered if r not in set(old))
    return changes


def _sightings(route_id: str, coverage: dict | None) -> str:
    try:
        days = coverage["days_observed"]
        seen = coverage["vehicle_positions"]["routes"].get(
            route_id, {}).get("days_seen", 0)
        return f"{int(seen)} of {int(days)} days"
    except (KeyError, TypeError, ValueError, AttributeError):
        return UNKNOWN


def _same_name(name: str | None, others: dict[str, str | None]) -> list[str]:
    if not name:
        return []
    return [r for r, other in others.items()
            if other and other.casefold() == name.casefold()]


def render(changes: list[tuple[str, str]], *, version: str,
           new_names: dict[str, str], previous_names: dict[str, str],
           coverage: dict | None, pending: list[str]) -> str:
    """The Markdown report; empty when nothing changed."""
    if not changes:
        return ""
    name_of = {r: (new_names.get(r) if kind == ADDED
                   else previous_names.get(r) or new_names.get(r))
               for r, kind in changes}
    added = {r: name_of[r] for r, kind in changes if kind == ADDED}
    leaving = {r: name_of[r] for r, kind in changes if kind != ADDED}

    lines = [f"### Route changes in feed {version}", ""]
    if pending:
        lines += [
            f"**Waiting for approval:** {', '.join(pending)}. The rest of "
            "this build is published, and these routes stay listed until "
            "the removal is approved. Riders who saved a removed route lose "
            "it from their selection once it is.", ""]
    lines += ["| Route | Change | Name | Seen with vehicles | Note |",
              "|---|---|---|---|---|"]
    for route_id, kind in changes:
        matches = _same_name(name_of[route_id],
                             leaving if kind == ADDED else added)
        note = (f"Same name as {', '.join(matches)}; possibly a rename"
                if matches else "")
        name = (name_of[route_id] or UNKNOWN).replace("|", "/")
        lines.append(f"| {route_id} | {kind} | {name} | "
                     f"{_sightings(route_id, coverage)} | {note} |")
    return "\n".join(lines) + "\n"


def _load_optional(path: str | None) -> dict | None:
    if not path:
        return None
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", required=True,
                        help="septameta.json exactly as built")
    parser.add_argument("--to-publish", required=True,
                        help="the septameta.json that will be published")
    parser.add_argument("--published", action="append", default=[],
                        help="an earlier septameta.json; repeat for each one")
    parser.add_argument("--gtfs-zip", required=True)
    parser.add_argument("--previous-names",
                        help="route names from the last release, if any")
    parser.add_argument("--coverage", help="septacoverage.json, if any")
    parser.add_argument("--pending", default="",
                        help="comma-separated route ids awaiting approval")
    parser.add_argument("--names-output", required=True)
    parser.add_argument("--report-output", required=True)
    args = parser.parse_args(argv)

    with open(args.candidate, encoding="utf-8") as handle:
        candidate = json.load(handle)
    with open(args.to_publish, encoding="utf-8") as handle:
        to_publish = json.load(handle)

    new_names = build_septa_meta.route_names(
        build_septa_meta.open_bus_feed(args.gtfs_zip))
    previous_names = _load_optional(args.previous_names) or {}
    names = names_to_keep(to_publish["buses"]["route_list"], new_names,
                          previous_names)
    with open(args.names_output, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(names, indent=2, ensure_ascii=False) + "\n")

    baselines = check_septa_meta.load_baselines(args.published)
    try:
        changes = route_changes(candidate, baselines)
    except ValueError:
        # check_septa_meta.py reports a candidate the app would reject.
        changes = []
    report = render(
        changes, version=candidate.get("meta", {}).get("version", UNKNOWN),
        new_names=new_names, previous_names=previous_names,
        coverage=_load_optional(args.coverage),
        pending=sorted(check_septa_meta.parse_approval(args.pending)))
    with open(args.report_output, "w", encoding="utf-8") as handle:
        handle.write(report)
    print(report or "No route changes.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
