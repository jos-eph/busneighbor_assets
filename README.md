# busneighbor_assets

Assets for BusNeighbor.

## septameta.json

The SEPTA route list and feed window BusNeighbor reads at runtime, rebuilt
weekly by [`.github/workflows/release-septa-meta.yml`](.github/workflows/release-septa-meta.yml)
from SEPTA's [public GTFS bundle](https://www3.septa.org/developer/gtfs_public.zip).

Latest:

```
https://github.com/jos-eph/busneighbor_assets/releases/download/current/septameta.json
```

Dated releases (`septameta-<feed_start_date>`) carry the same document under
`septameta_<feed_start_date>.json` for consumers that want to pin. Every asset
ships a `.sha256` sidecar in `sha256sum -c` format.

```json
{
  "meta": {
    "start_date": "20260823",
    "end_date": "20270220",
    "version": "v202608233"
  },
  "buses": {
    "route_list": ["L1", "B1", "B2", "..."]
  }
}
```

`meta` is `feed_info.txt` verbatim. `route_list` is every `route_id` in the
bundle's bus feed — surface routes plus Metro — ordered by `route_sort_order`.
Regional Rail lives in a separate feed and is not included.

`realtime` is a claim about SEPTA's infrastructure rather than about the GTFS
feed, which is why it sits beside `buses` rather than inside it.
`overrides.no_vehicle_positions` lists routes SEPTA publishes no live vehicle
positions for, ordered to match `route_list`:

```json
"realtime": {
  "source": "manual",
  "observed_through": null,
  "overrides": { "no_vehicle_positions": ["L1", "B1", "B2", "B3"] }
}
```

**This is a deny-list, and consumers must fail open.** A route absent from it is
shown normally, and a failure to fetch this document must mean *show
everything*. Treating it as an allow-list, or hiding routes when the fetch
fails, turns a pipeline outage into an app outage.

The list is currently hand-maintained in `realtime_overrides.json` and
`source` reads `"manual"`. A sampler that measures coverage from the real-time
feed is the intended replacement; when it lands, `source` becomes `"observed"`
and `observed_through` carries the last measured date, without the document's
shape changing.

The build runs `python build_septa_meta.py`; `python -m unittest discover -s tests`
covers it.

## Real-time coverage sampling

`sample_realtime_coverage.py` records which routes SEPTA is currently
publishing vehicle positions for, one observation per run:

```bash
python sample_realtime_coverage.py --output out/sample.json
python sample_realtime_coverage.py --pb local.pb --output out/sample.json
```

Samples are sparse — only routes actually seen. Zeros are filled in later
against `route_list`, so coverage is always computed against the current feed.
A quiet hour with few routes is a valid sample, not a failure; an empty or
unparseable feed exits non-zero and writes nothing.

## septacoverage.json

Which routes SEPTA actually publishes live vehicle positions for, measured
rather than asserted. Published daily to the same rolling release:

```
https://github.com/jos-eph/busneighbor_assets/releases/download/current/septacoverage.json
```

```json
{
  "generated_at": "2026-09-29T01:47:12Z",
  "observed_through": "2026-09-28",
  "window_days": 28,
  "days_observed": 27,
  "samples": 214,
  "feed_meta": { "start_date": "20260823", "version": "v202608233" },
  "vehicle_positions": {
    "no_vehicle_positions": ["L1", "B1", "B2", "B3"],
    "routes": {
      "L1": { "days_seen": 0,  "last_seen": null,         "positions": 0 },
      "T1": { "days_seen": 27, "last_seen": "2026-09-28", "positions": 41203 }
    }
  },
  "unmatched_route_ids": []
}
```

`days_seen` counts distinct **days**, not samples, so a route does not score
higher merely for running frequently. `days_observed` is how many days the
window actually holds, so a consumer can tell a thin window from a full one.
`no_vehicle_positions` holds exactly the routes with `days_seen == 0`, ordered
to match `route_list`. `unmatched_route_ids` should be empty; it is the
tripwire for route ids drifting between the real-time and static feeds.

**This is a deny-list, and consumers must fail open.** A route absent from it
is shown normally, and a failure to fetch this document must mean *show
everything*. An allow-list, or a fetch failure that means *show nothing*, turns
a pipeline outage into an app outage.

`septacoverage.json` is evidence, published on its own daily clock.
`septameta.json` changes only when SEPTA does, which is why the two live in
separate files.

## Service alert archive

Every sampler run also snapshots SEPTA's service alerts (GTFS-realtime) and its
[BusDetours](https://www3.septa.org/api/BusDetours/index.php) listing, and
folds them into one file per UTC day on the `service-alerts` release. Files
older than 50 days are deleted.

```
https://github.com/jos-eph/busneighbor_assets/releases/download/service-alerts/septaalerts_<YYYY-MM-DD>.json
```

```json
{
  "date": "2026-10-11",
  "samples": [
    { "sampled_at": "2026-10-11T02:17:40Z", "feed_timestamp": 1791685060 },
    { "sampled_at": "2026-10-11T05:17:12Z", "feed_timestamp": 1791695832, "detours": false }
  ],
  "alerts": [
    {
      "id": "D17048",
      "header": "Sink Hole",
      "description": "24/7 until 10/29/26, SB via 17th St, Left on Diamond St, ...",
      "routes": ["2"],
      "active_periods": [[1790680740, 1793304000]],
      "effect": "DETOUR",
      "cause": "CONSTRUCTION",
      "severity_level": "WARNING",
      "first_seen": "2026-10-11T02:17:40Z",
      "last_seen": "2026-10-11T05:17:12Z"
    }
  ],
  "detours": [
    {
      "routes": ["2"],
      "route_direction": "SB",
      "reason": "Sink Hole ",
      "start_location": "17th & Diamond Sts",
      "end_location": "17th St btwn Jefferson & Master Sts ",
      "start_date_time": "9/29/2026   7:19 AM",
      "end_date_time": "10/29/2026   4:00 PM",
      "current_message": " 24/7 until 10/29/26 SB via 17th St L  - Diamond St R - ...",
      "first_seen": "2026-10-11T02:17:40Z",
      "last_seen": "2026-10-11T02:17:40Z"
    }
  ]
}
```

Each distinct alert or detour appears once per day, with the first and last
snapshot that saw it; one revised during the day appears once per version.
`samples` lists every snapshot folded in, and `"detours": false` marks one
whose detour fetch failed, as distinct from SEPTA listing none.

Alerts: `description` is omitted when it repeats `header`; `routes` lists each
route once, and is empty for alerts scoped only to a trip or stop;
`active_periods` are `[start, end]` in POSIX seconds, `null` where open;
`effect`, `cause` and `severity_level` are omitted when unset or `UNKNOWN_*`.
Detours are SEPTA's records verbatim, except that one listed identically under
several routes is stored once. All text is kept as published, HTML entities
and whitespace included. This is an internal archive, not a consumer API.

## Vehicle position archive

Every coverage sample also keeps the vehicle positions it was computed from,
taken from the same fetch, in one file per UTC day on the
`vehicle-positions` release. Files older than 50 days are deleted.

```
https://github.com/jos-eph/busneighbor_assets/releases/download/vehicle-positions/septapositions_<YYYY-MM-DD>.json
```

```json
{
  "date": "2026-10-11",
  "fields": ["vehicle_id", "route_id", "trip_id", "direction_id", "lat", "lon",
             "bearing", "speed", "timestamp", "stop_id",
             "current_stop_sequence", "current_status"],
  "samples": [
    {
      "sampled_at": "2026-10-11T19:43:58Z",
      "feed_timestamp": 1791746102,
      "vehicles": [
        ["3641", "42", "879622", 0, 39.950264, -75.199646, 196.8, 8.12,
         1791746100, "21435", 26, "IN_TRANSIT_TO"]
      ]
    }
  ]
}
```

Each vehicle is a row in `fields` order, with `null` where the feed is silent,
and only vehicles with a valid position are kept. `timestamp` is the
vehicle's own report time, which can lag `sampled_at`. This is an internal
archive, not a consumer API.

## Dependencies

Everything except the samplers is **stdlib-only**, including
`merge_service_alerts.py` and `merge_vehicle_positions.py`. Only `sample_realtime_coverage.py` and
`sample_service_alerts.py` have dependencies, pinned with hashes in
`requirements.txt`:

```bash
pip install --require-hashes -r requirements.txt
```

Protobuf parsing goes through
[`gtfs-realtime-bindings`](https://pypi.org/project/gtfs-realtime-bindings/)
rather than a hand-rolled wire-format reader, and anything that grows a second
`.pb` consumer imports `gtfs_rt.py` rather than opening its own parser.

## How it runs

| Workflow | Cadence | Permissions | Dependencies |
| --- | --- | --- | --- |
| `release-septa-meta` | weekly | `contents: write` | none |
| `sample-realtime-coverage` | 8× daily | `contents: read`; `publish-*` jobs `contents: write` | `requirements.txt`, except `publish-*` |
| `aggregate-realtime-coverage` | daily | `contents: write` | none |

Only the sampler workflow installs a third-party package. Its jobs that can
write, `publish-alerts` and `publish-positions`, install nothing and run only
this repository's stdlib code and `publish_day_file.sh`.
