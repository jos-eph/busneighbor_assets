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
    "route_list": ["L1", "B1", "B2", "..."],
    "route_category": { "L1": "blue_line_blue", "T1": "trolley_green" },
    "category_routes": { "blue_line_blue": ["L1", "L1_OWL"] }
  }
}
```

`meta` is `feed_info.txt` verbatim. `route_list` is every `route_id` in the
bundle's bus feed — surface routes plus Metro — ordered by `route_sort_order`.
Regional Rail lives in a separate feed and is not included.

`route_category` and `category_routes` classify each route by SEPTA's
palette, derived from `routes.txt`'s `route_color` via `septaclrs.csv`. The
category names are palette buckets, not vehicle types — routes of different
`route_type` can share a color and land in the same category.

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

## Dependencies

`build_septa_meta.py` and the release workflow are **stdlib-only**. Only the
real-time sampler has dependencies, pinned with hashes in `requirements.txt`:

```bash
pip install --require-hashes -r requirements.txt
```

Protobuf parsing goes through
[`gtfs-realtime-bindings`](https://pypi.org/project/gtfs-realtime-bindings/)
rather than a hand-rolled wire-format reader, and anything that grows a second
`.pb` consumer imports `gtfs_rt.py` rather than opening its own parser.

The split is deliberate: **the workflow that can write to this repository runs
no third-party code.** The sampler holds `contents: read` and publishes only a
build artifact; the release workflow keeps `contents: write` and installs
nothing.
