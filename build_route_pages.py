"""Write one web page per offered route, for the Pages build.

Reads septameta.json (which routes), septashapes.json (each route's line), and
route_names.json (each route's name), and writes <output-dir>/<route>.html from
route_page.html. Offered means the app's rule: buses.route_list, minus
realtime.overrides.no_vehicle_positions, in catalog order.
"""

import argparse
import html
import json
import math
import re
import string
import sys
from pathlib import Path

import build_site

SITE = "https://bus.dydx.org"
TEMPLATE = Path(__file__).with_name("route_page.html")

# Same pattern as routelink.js and the app's link parser.
ROUTE_ID = re.compile(r"^[A-Za-z0-9_-]{1,16}$")

TROLLEYS = frozenset({"T1", "T2", "T3", "T4", "T5", "G1", "D1", "D2"})

POLYLINE_PRECISION = 5  # build_septa_shapes.POLYLINE_PRECISION

# The drawing's longer side, in SVG user units, and the margin inside it.
SHAPE_EXTENT = 320
SHAPE_MARGIN = 16


def offered_routes(meta: dict) -> list[str]:
    hidden = set(meta.get("realtime", {}).get("overrides", {}).get("no_vehicle_positions", []))
    routes = []
    for entry in meta["buses"]["route_list"]:
        route_id = entry.strip() if isinstance(entry, str) else ""
        if ROUTE_ID.match(route_id) and route_id not in hidden and route_id not in routes:
            routes.append(route_id)
    if not routes:
        raise ValueError("no offered routes")
    return routes


def decode_polyline(encoded: str, precision: int = POLYLINE_PRECISION) -> list[tuple[float, float]]:
    """Google's encoded polyline format, to (lat, lon) pairs."""
    factor = 10 ** precision
    points, index, lat, lon = [], 0, 0, 0
    while index < len(encoded):
        deltas = []
        for _ in range(2):
            shift = result = 0
            while True:
                byte = ord(encoded[index]) - 63
                index += 1
                result |= (byte & 0x1F) << shift
                shift += 5
                if byte < 0x20:
                    break
            deltas.append(~(result >> 1) if result & 1 else result >> 1)
        lat += deltas[0]
        lon += deltas[1]
        points.append((lat / factor, lon / factor))
    return points


def vehicle_noun(route_id: str) -> str:
    return "trolley" if route_id in TROLLEYS else "bus"


def shape_svg(route_id: str, directions: list[dict]) -> tuple[str, str]:
    """An SVG of the route's line, north up, and a sentence describing it."""
    lines = [decode_polyline(d["primary"]) for d in directions if d.get("primary")]
    lines = [line for line in lines if len(line) >= 2]
    if not lines:
        return "", ""
    lats = [lat for line in lines for lat, _ in line]
    lons = [lon for line in lines for _, lon in line]
    # Equirectangular around the middle latitude: true enough at city scale.
    lon_scale = math.cos(math.radians((min(lats) + max(lats)) / 2))
    width_deg = (max(lons) - min(lons)) * lon_scale
    height_deg = max(lats) - min(lats)
    span = max(width_deg, height_deg) or 1e-9
    usable = SHAPE_EXTENT - 2 * SHAPE_MARGIN
    width = round(width_deg / span * usable + 2 * SHAPE_MARGIN)
    height = round(height_deg / span * usable + 2 * SHAPE_MARGIN)

    def xy(lat, lon):
        x = SHAPE_MARGIN + (lon - min(lons)) * lon_scale / span * usable
        y = SHAPE_MARGIN + (max(lats) - lat) / span * usable
        return f"{x:.1f},{y:.1f}"

    paths = []
    for line in lines:
        coords = []
        for lat, lon in line:
            point = xy(lat, lon)
            if not coords or coords[-1] != point:
                coords.append(point)
        paths.append(f'<polyline points="{" ".join(coords)}"/>')
    ends = {xy(*lines[0][0]), xy(*lines[0][-1])}
    dots = "".join(
        f'<circle cx="{p.split(",")[0]}" cy="{p.split(",")[1]}" r="5"/>' for p in sorted(ends)
    )

    if height_deg > 1.5 * width_deg:
        heading = "mostly north and south"
    elif width_deg > 1.5 * height_deg:
        heading = "mostly east and west"
    else:
        heading = "across the map diagonally or in a loop"
    label = f"The line Route {route_id} follows, north at the top. It runs {heading}."
    svg = (
        f'<svg class="shape" viewBox="0 0 {width} {height}" width="{width}" height="{height}" '
        f'role="img" aria-label="{html.escape(label)}">'
        f'<g class="shape-line">{"".join(paths)}</g>'
        f'<g class="shape-ends">{dots}</g></svg>'
    )
    return svg, "North is at the top. Dots mark the ends of the line."


def keep_together(text: str) -> str:
    """Escaped text in which a hyphenated word like 5th-Godfrey never breaks at the hyphen."""
    words = html.escape(text).split(" ")
    return " ".join(f'<span class="nowrap">{w}</span>' if "-" in w else w for w in words)


def render_page(template: string.Template, route_id: str, name: str, shapes: list[dict]) -> str:
    vehicle = vehicle_noun(route_id)
    directions = [d["name"] for d in shapes if d.get("name")]
    svg, caption = shape_svg(route_id, shapes)
    title = f"SEPTA Route {route_id} Live {vehicle.title()} Tracker — BusNeighbor"
    named = f" ({name})" if name else ""
    description = (
        f"See where every SEPTA Route {route_id} {vehicle}{named} is right now, with detours. "
        "A free live map built for blind and low-vision riders. No ads."
    )
    return template.substitute(
        title=html.escape(title),
        description=html.escape(description),
        url=f"{SITE}/route/{route_id}",
        go_url=f"{SITE}/go?routes={route_id}",
        route_id=route_id,
        name_html=keep_together(name or f"Route {route_id}"),
        vehicle=vehicle,
        directions=html.escape(" and ".join(directions) if directions else "both ways"),
        shape_svg=svg,
        caption=html.escape(caption),
    )


def build(meta: dict, shapes: dict, names: dict, output_dir: Path, only: list[str] | None) -> list[str]:
    routes = offered_routes(meta)
    if only:
        unknown = [r for r in only if r not in routes]
        if unknown:
            raise ValueError(f"not offered: {', '.join(unknown)}")
        routes = [r for r in routes if r in only]
    # Shared pieces (footer, store badges) first, then the per-route values.
    source = build_site.expand_includes(TEMPLATE.read_text(encoding="utf-8"))
    template = string.Template(source)
    output_dir.mkdir(parents=True, exist_ok=True)
    for route_id in routes:
        page = render_page(template, route_id, names.get(route_id, ""),
                           shapes.get("routes", {}).get(route_id, []))
        (output_dir / f"{route_id}.html").write_text(page, encoding="utf-8")
    return routes


def _load(path: str) -> dict:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--meta", required=True)
    parser.add_argument("--shapes", required=True)
    parser.add_argument("--names", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--routes", help="comma-separated subset to build")
    args = parser.parse_args(argv)
    only = [r.strip() for r in args.routes.split(",")] if args.routes else None
    written = build(_load(args.meta), _load(args.shapes), _load(args.names),
                    Path(args.output_dir), only)
    print(f"wrote {len(written)} route pages")
    return 0


if __name__ == "__main__":
    sys.exit(main())
