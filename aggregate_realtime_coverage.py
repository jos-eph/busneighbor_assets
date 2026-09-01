#!/usr/bin/env python3
"""Fold a day of coverage samples into a rolling window and publish the result.

Pure functions over local files: this script does no network I/O, so it is
fully testable offline. The workflow around it does the fetching and uploading.

Four steps, in order:

  1. Reduce a directory of samples into one daily summary.
  2. Fold that summary into the rolling state, evicting days that fell out of
     the window.
  3. Project the window onto the current route_list to get the consumer
     document, so a route that never appears is present with zeros rather than
     missing.
  4. Propose a deny-list, behind guards. Proposing and applying are separate:
     this script never writes realtime_overrides.json.

Stdlib only. The samples are JSON by the time they reach here, so nothing in
this file needs protobuf.
"""

from __future__ import annotations

import argparse
import collections
import datetime
import json
import os
import sys

WINDOW_DAYS = 28
MIN_SAMPLES_PER_DAY = 4
MIN_DAYS_OBSERVED = 7
MAX_DENY_FRACTION = 0.20

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_GUARD_TRIPPED = 2


def utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def _stamp(moment: datetime.datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _write_json(document: dict, path: str) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    payload = json.dumps(document, indent=2, sort_keys=True) + "\n"
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(payload)


# --------------------------------------------------------------------------
# Step 1 — samples to a daily summary
# --------------------------------------------------------------------------

def load_samples(samples_dir: str) -> list[dict]:
    """Read every *.json in samples_dir, oldest sample first."""
    if not os.path.isdir(samples_dir):
        raise ValueError(f"samples directory not found: {samples_dir}")

    samples = []
    for name in sorted(os.listdir(samples_dir)):
        if not name.endswith(".json"):
            continue
        path = os.path.join(samples_dir, name)
        try:
            with open(path, encoding="utf-8") as handle:
                sample = json.load(handle)
        except json.JSONDecodeError as exc:
            raise ValueError(f"sample {path} is not valid JSON: {exc}") from exc
        for key in ("sampled_at", "feed_timestamp", "positions_by_route"):
            if key not in sample:
                raise ValueError(f"sample {path} is missing {key}")
        samples.append(sample)

    return sorted(samples, key=lambda s: s["sampled_at"])


def daily_summary(samples: list[dict], date: str | None = None) -> tuple[dict, int]:
    """Sum a day's samples into one summary; return it and the drop count.

    Two samples carrying the same feed header timestamp saw the same frozen
    feed. Counting both would inflate the day's totals and, worse, hide a SEPTA
    outage behind healthy-looking numbers, so the first wins and the rest are
    dropped.
    """
    if not samples:
        raise ValueError("no samples to summarize")

    dates = {s["sampled_at"][:10] for s in samples}
    if date is None:
        if len(dates) > 1:
            raise ValueError(
                f"samples span more than one UTC day ({', '.join(sorted(dates))}); "
                "pass --date to choose one"
            )
        date = dates.pop()
    else:
        samples = [s for s in samples if s["sampled_at"][:10] == date]
        if not samples:
            raise ValueError(f"no samples for {date}")

    seen_feeds: set[int] = set()
    kept: list[dict] = []
    dropped = 0
    for sample in samples:
        timestamp = sample["feed_timestamp"]
        if timestamp in seen_feeds:
            dropped += 1
            continue
        seen_feeds.add(timestamp)
        kept.append(sample)

    totals: collections.Counter[str] = collections.Counter()
    for sample in kept:
        totals.update(sample["positions_by_route"])

    return {
        "date": date,
        "samples": len(kept),
        "samples_dropped_duplicate_feed": dropped,
        "first_sampled_at": kept[0]["sampled_at"],
        "last_sampled_at": kept[-1]["sampled_at"],
        "distinct_routes": len(totals),
        "positions_by_route": dict(sorted(totals.items())),
    }, dropped


# --------------------------------------------------------------------------
# Step 2 — fold into the rolling state
# --------------------------------------------------------------------------

def empty_state(window_days: int, min_samples_per_day: int) -> dict:
    return {
        "window_days": window_days,
        "min_samples_per_day": min_samples_per_day,
        "days": {},
    }


def load_state(path: str, window_days: int, min_samples_per_day: int) -> dict:
    if not path or not os.path.exists(path):
        return empty_state(window_days, min_samples_per_day)
    with open(path, encoding="utf-8") as handle:
        state = json.load(handle)
    if not isinstance(state.get("days"), dict):
        raise ValueError(f"state file {path} has no days map")
    state["window_days"] = window_days
    state["min_samples_per_day"] = min_samples_per_day
    return state


def fold_into_state(state: dict, summary: dict, feed_version: str,
                    window_days: int) -> dict:
    """Insert the day, then evict everything outside the window.

    Re-running the same date REPLACES that date's entry rather than adding to
    it, which is what makes a rerun safe.
    """
    days = dict(state["days"])
    days[summary["date"]] = {
        "samples": summary["samples"],
        "feed_version": feed_version,
        "positions_by_route": dict(summary["positions_by_route"]),
    }

    newest = max(days)
    cutoff = (datetime.date.fromisoformat(newest)
              - datetime.timedelta(days=window_days - 1)).isoformat()
    days = {d: v for d, v in days.items() if d >= cutoff}

    return {
        "window_days": window_days,
        "min_samples_per_day": state["min_samples_per_day"],
        "days": dict(sorted(days.items())),
    }


# --------------------------------------------------------------------------
# Step 3 — project to the consumer document
# --------------------------------------------------------------------------

def project(state: dict, route_list: list[str], feed_meta: dict,
            *, generated_at: datetime.datetime) -> dict:
    """Densify the window against route_list.

    days_seen counts distinct DAYS, not samples: a route must not score higher
    merely for running frequently.
    """
    days = state["days"]
    known = set(route_list)

    totals: collections.Counter[str] = collections.Counter()
    days_seen: collections.Counter[str] = collections.Counter()
    last_seen: dict[str, str] = {}
    unmatched: set[str] = set()

    for date in sorted(days):
        for route_id, count in days[date]["positions_by_route"].items():
            if route_id not in known:
                unmatched.add(route_id)
                continue
            totals[route_id] += count
            if count > 0:
                days_seen[route_id] += 1
                last_seen[route_id] = date

    routes = {
        route_id: {
            "days_seen": days_seen.get(route_id, 0),
            "last_seen": last_seen.get(route_id),
            "positions": totals.get(route_id, 0),
        }
        for route_id in route_list
    }

    # route_list arrives in route_sort_order, so filtering it preserves that
    # order — deliberately not alphabetical, to match route_list itself.
    no_positions = [r for r in route_list if routes[r]["days_seen"] == 0]

    return {
        "generated_at": _stamp(generated_at),
        "observed_through": max(days) if days else None,
        "window_days": state["window_days"],
        "days_observed": len(days),
        "samples": sum(d["samples"] for d in days.values()),
        "feed_meta": {
            "start_date": feed_meta.get("start_date"),
            "version": feed_meta.get("version"),
        },
        "vehicle_positions": {
            "no_vehicle_positions": no_positions,
            "routes": routes,
        },
        "unmatched_route_ids": sorted(unmatched),
    }


# --------------------------------------------------------------------------
# Step 4 — propose a deny-list, behind guards
# --------------------------------------------------------------------------

def proposal_from(coverage: dict, *, generated_at: datetime.datetime) -> dict:
    return {
        "source": "observed",
        "observed_through": coverage["observed_through"],
        "window_days": coverage["window_days"],
        "days_observed": coverage["days_observed"],
        "updated_at": _stamp(generated_at),
        "no_vehicle_positions": list(
            coverage["vehicle_positions"]["no_vehicle_positions"]),
    }


def check_guards(coverage: dict, state: dict, route_list: list[str],
                 feed_meta: dict, *, min_days_observed: int,
                 max_deny_fraction: float) -> list[str]:
    """Reasons the proposal must not be applied. Empty means all clear."""
    failures = []

    if coverage["days_observed"] < min_days_observed:
        failures.append(
            f"window depth: {coverage['days_observed']} days observed, "
            f"below the {min_days_observed}-day floor"
        )

    denied = len(coverage["vehicle_positions"]["no_vehicle_positions"])
    limit = max_deny_fraction * len(route_list)
    if denied > limit:
        failures.append(
            f"blast radius: {denied} of {len(route_list)} routes proposed for "
            f"the deny-list, above the {max_deny_fraction:.0%} cap "
            f"({limit:.1f}); a sampler that died quietly reports zero for "
            f"everything"
        )

    current = feed_meta.get("version")
    versions = {d.get("feed_version") for d in state["days"].values()}
    if versions and versions != {current}:
        failures.append(
            f"feed agreement: window spans feed versions "
            f"{sorted(str(v) for v in versions)} but septameta.json reports "
            f"{current!r}; a deny-list derived across a feed change can name "
            f"retired routes"
        )

    return failures


# --------------------------------------------------------------------------

def main(argv: list[str] | None = None, *, now=utc_now) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples-dir", required=True)
    parser.add_argument("--septameta", required=True)
    parser.add_argument("--output-dir", default="out")
    parser.add_argument("--state", default=None,
                        help="previous septacoverage_state.json (absent on first run)")
    parser.add_argument("--date", default=None,
                        help="UTC date to aggregate; inferred from the samples if omitted")
    parser.add_argument("--window-days", type=int, default=WINDOW_DAYS)
    parser.add_argument("--min-samples-per-day", type=int, default=MIN_SAMPLES_PER_DAY)
    parser.add_argument("--min-days-observed", type=int, default=MIN_DAYS_OBSERVED)
    parser.add_argument("--max-deny-fraction", type=float, default=MAX_DENY_FRACTION)
    args = parser.parse_args(argv)

    generated_at = now()

    try:
        with open(args.septameta, encoding="utf-8") as handle:
            septameta = json.load(handle)
        route_list = septameta["buses"]["route_list"]
        feed_meta = septameta["meta"]
    except (OSError, KeyError, json.JSONDecodeError) as exc:
        print(f"::error::Cannot read septameta.json: {exc}", file=sys.stderr)
        return EXIT_FAILED

    try:
        samples = load_samples(args.samples_dir)
        summary, dropped = daily_summary(samples, args.date)
    except ValueError as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return EXIT_FAILED

    if dropped:
        print(f"::warning::Dropped {dropped} sample(s) carrying a duplicate "
              f"feed_timestamp; two runs saw the same frozen feed.")

    state = load_state(args.state, args.window_days, args.min_samples_per_day)

    # A thin day can only ever fail to show a route, so it biases every count
    # toward the deny-list. A missing day is a smaller harm than a skewed one.
    if summary["samples"] < args.min_samples_per_day:
        print(f"::warning::{summary['date']} has only {summary['samples']} "
              f"usable sample(s), below the {args.min_samples_per_day} minimum; "
              f"not recording it.")
        _write_json(summary,
                    os.path.join(args.output_dir,
                                 f"septacoverage_{summary['date']}.json"))
        return EXIT_OK

    state = fold_into_state(state, summary, feed_meta.get("version"),
                            args.window_days)
    coverage = project(state, route_list, feed_meta, generated_at=generated_at)
    proposal = proposal_from(coverage, generated_at=generated_at)

    _write_json(summary, os.path.join(args.output_dir,
                                      f"septacoverage_{summary['date']}.json"))
    _write_json(state, os.path.join(args.output_dir, "septacoverage_state.json"))
    _write_json(coverage, os.path.join(args.output_dir, "septacoverage.json"))
    _write_json(proposal, os.path.join(args.output_dir,
                                       "realtime_overrides.proposed.json"))

    if coverage["unmatched_route_ids"]:
        # The tripwire for join-key drift — the same class of bug as
        # rtServiceAlerts.pb spelling the Owl routes "B1 OWL" while routes.txt
        # spells them "B1_OWL". An extra id upstream must not stop the publish.
        print(f"::warning::Route ids seen in the real-time feed but absent from "
              f"route_list: {', '.join(coverage['unmatched_route_ids'])}")

    print(
        f"{summary['date']}: {summary['samples']} samples, "
        f"{coverage['days_observed']} of {args.window_days} days observed, "
        f"{len(coverage['vehicle_positions']['no_vehicle_positions'])} routes "
        f"without vehicle positions",
        file=sys.stderr,
    )

    failures = check_guards(
        coverage, state, route_list, feed_meta,
        min_days_observed=args.min_days_observed,
        max_deny_fraction=args.max_deny_fraction,
    )
    if failures:
        # Loud on purpose. Silence here is exactly the failure mode that hides
        # the network: the coverage document is still published, because the
        # evidence is still true; only acting on it is suspended.
        for failure in failures:
            print(f"::error::Guard tripped — {failure}")
        return EXIT_GUARD_TRIPPED

    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
