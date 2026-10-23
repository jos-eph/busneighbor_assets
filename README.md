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

A build is not published if it would stop offering a route that the published
document offers, either by dropping it from `route_list` or by adding it to
`no_vehicle_positions`. The run fails instead, and a maintainer reruns it with
`approve_removals` set to exactly the routes it lists. The build is compared
against both the live copy and the newest dated release, and is refused
outright when neither can be read. `check_septa_meta.py` makes that decision.

Only the weekly workflow writes the `current` release, and only from `main`:
its job runs in the `septameta-release` environment, which holds the
`RELEASE_SEPTA_META_ENABLED` kill switch and deploys from `main` alone.

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

`directions` names each route's directions as riders see them, keyed by GTFS
`direction_id`, in `route_list` order:

```json
"directions": {
  "64": { "0": "Westbound", "1": "Eastbound" },
  "310": { "0": "Loop" }
}
```

The words come from the bundle's `directions.txt`, with
`direction_overrides.json` on top for corrections. Only Northbound,
Southbound, Eastbound, Westbound, Loop, Inbound, and Outbound are carried. A route with no usable word is left out and
listed in the build log, and the build still publishes: consumers fall back
to their own names.

`alternate_feed_host` is a bare hostname, or `null`, set by hand in
`remote_control.json`. It names a live-feed host for the app to try only when
every host built into it fails, so moving hosts doesn't have to wait for an
app release.

Both fields are newer than the first app release that reads this document,
and older releases ignore them. Consumers should read only the keys they
know. `check_septa_meta.py` refuses a build with malformed direction words or
an `alternate_feed_host` that isn't a bare hostname.

The build runs `python build_septa_meta.py`; `python -m unittest discover -s tests`
covers it.

## septashapes.json

The regular line of every bus route, per direction, built by the same weekly
workflow from the same bundle and published to the same `current` release:

```
https://github.com/jos-eph/busneighbor_assets/releases/download/current/septashapes.json
```

```json
{
  "v": 1,
  "gtfs_version": "v202609271",
  "generated": "2026-10-18T06:00:00Z",
  "routes": {
    "64": [
      {
        "dir": 0,
        "name": "Eastbound",
        "primary": "<encoded polyline>",
        "variants": ["<encoded polyline>"],
        "stops": ["1234", "..."]
      }
    ]
  }
}
```

`primary` is the shape most trips in that direction use; `variants` are the
other shapes trips use, such as branches and short turns. Both are Google
encoded polylines at precision 5, simplified with Douglas-Peucker at 5 m.
`dir` is the GTFS `direction_id`, `name` comes from `directions.txt` (empty
when absent), and `stops` follows `route_stops.txt` order. Routes are in
`route_sort_order`; a route with no trips is left out.

The schema is a contract: any change bumps `v`, and readers reject a `v` they
don't know. A build is published only when it differs from the live copy
apart from `generated`. There is no dated release.

`python build_septa_shapes.py --gtfs-zip <bundle>` builds it locally. The
`Build check` workflow builds both documents for a pull request that touches
the builders and keeps them as an artifact, without publishing.

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
rather than asserted. Published daily to its own rolling release:

```
https://github.com/jos-eph/busneighbor_assets/releases/download/coverage/septacoverage.json
```

A day whose aggregation trips any guard (fewer than 7 days observed, too many
routes proposed for the deny-list, or a window that hasn't caught up with a
feed change) records its state but does not publish this document. The last
one that passed stays up.

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
taken from the same fetch, in one CSV file per UTC day on the
`vehicle-positions` release. Files older than 50 days are deleted.

```
https://github.com/jos-eph/busneighbor_assets/releases/download/vehicle-positions/septapositions_<YYYY-MM-DD>.csv
```

Each row is one vehicle in one sample, so a day with eight samples of about
900 vehicles is about 7,000 rows:

```csv
sampled_at,feed_time,route_id,direction_id,direction,vehicle_id,trip_id,trip_headsign,lat,lon,bearing_deg,speed_mps,reported_at,report_age_s,stop_id,stop_name,stop_sequence,status
2026-10-13T14:21:16Z,2026-10-13T14:20:51Z,1,0,Northbound,3187,868479,Parx Casino via Decatur-Drummond,40.0383,-75.060493,40.2,13.54,2026-10-13T14:20:46Z,30,22486,Roosevelt Blvd & Longshore Av,61,IN_TRANSIT_TO
```

| Column | Meaning |
| --- | --- |
| `sampled_at` | When the sampler fetched the feed (UTC) |
| `feed_time` | The time the feed itself reported (UTC) |
| `route_id` | Route, such as `42`, `T1` or `D1` |
| `direction_id` | `0` or `1`, as in GTFS |
| `direction` | What that direction is called on that route, such as `Northbound` |
| `vehicle_id` | The bus or trolley number |
| `trip_id` | The scheduled trip the vehicle is running |
| `trip_headsign` | Where that trip is going, as on the bus's sign |
| `lat`, `lon` | Position in degrees, to 6 decimal places (about 0.1 m) |
| `bearing_deg` | Heading in degrees clockwise from north |
| `speed_mps` | Speed in meters per second |
| `reported_at` | When the vehicle last reported its position (UTC) |
| `report_age_s` | Seconds between `reported_at` and `sampled_at`: how stale the position was |
| `stop_id` | The stop the vehicle is at or heading to |
| `stop_name` | That stop's name |
| `stop_sequence` | That stop's place in the trip, counting from 1 |
| `status` | `STOPPED_AT`, `IN_TRANSIT_TO` or `INCOMING_AT` the stop |

Times are UTC, written `YYYY-MM-DDTHH:MM:SSZ`. **A blank cell means the feed
didn't say.** Expect many blanks: around 40% of vehicles report a position
with no trip, which leaves every trip, stop and direction column empty for
them, and `bearing_deg` is often missing. The three name columns come from the
static GTFS bundle, which the sampler downloads once per UTC day; they are
blank for a sample taken while it was unavailable. Only vehicles with a valid
position are kept.

Rows are in time order by sample, then by route, with numbered routes in
numeric order before lettered ones, then by direction and vehicle number.
Vehicles with no trip come last in each sample.

To look at a day:

- **In a spreadsheet:** open the `.csv` in Numbers, Excel or Google Sheets.
- **In a terminal:** `vd septapositions_2026-10-13.csv` with
  [VisiData](https://www.visidata.org/).
- **Across many days:** with [DuckDB](https://duckdb.org/),
  `SELECT route_id, count(*) FROM 'septapositions_*.csv' GROUP BY 1`.

This is an internal archive, not a consumer API.

## Dependencies

Everything except the samplers is **stdlib-only**, including
`merge_service_alerts.py`, `merge_vehicle_positions.py` and `gtfs_static.py`. Only `sample_realtime_coverage.py` and
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
this repository's stdlib code, `publish_day_file.sh` and
`migrate_legacy_positions.sh`. Before 2026-10-13 the position archive was one
JSON file per day; `migrate_legacy_positions.sh` converts any such file still
on the release to CSV on the next run, deletes the JSON once its rows are all
in the CSV, and does nothing once none are left.
