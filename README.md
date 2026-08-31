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

The build runs `python build_septa_meta.py`; `python -m unittest discover -s tests`
covers it. Both are stdlib-only.
