"""Write one web page per offered route, for the Pages build.

Reads septameta.json (which routes), septashapes.json (each route's line and
stops), route_names.json (each route's name), route_stops.json (stop names and
positions), and route_places.json (areas and landmarks), and writes
<output-dir>/<route>.html from route_page.html. Offered means the app's rule:
buses.route_list, minus realtime.overrides.no_vehicle_positions, in catalog
order. Shuttle ids get no page.
"""

import argparse
import html
import json
import math
import re
import string
import sys
from dataclasses import dataclass
from pathlib import Path

import build_site
import route_facts as facts_lib

SITE = "https://bus.dydx.org"
TEMPLATE = Path(__file__).with_name("route_page.html")
PLACES = Path(__file__).with_name("route_places.json")
NEIGHBORHOODS_LICENSE = "https://creativecommons.org/licenses/by/4.0/"
NEIGHBORHOODS_SOURCE = ("https://github.com/opendataphilly/open-geo-data/tree/master/"
                        "philadelphia-neighborhoods")
OSM_COPYRIGHT = "https://www.openstreetmap.org/copyright"
SCHEDULE_URL = "https://www.septa.org/schedules/{route}"
STORE_URLS = (
    "https://apps.apple.com/app/busneighbor/id6812131455",
    "https://play.google.com/store/apps/details?id=org.dydx.busneighbor_flutter",
)

# Search results show about this many characters of a description.
MAX_DESCRIPTION = 155

# Replacement buses for rail lines. They stay in the app's picker but get no
# page and never appear as a connection.
SHUTTLES = frozenset({"MANN", "T_BUS", "D1_BUS", "D2_BUS", "M1_BUS", "FOX_BUS", "NOR_BUS",
                      "WTR_BUS"})

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


def join_list(items: list[str]) -> str:
    """Items as a phrase with the serial comma: "A, B, and C"."""
    if len(items) <= 2:
        return " and ".join(items)
    return f"{', '.join(items[:-1])}, and {items[-1]}"


def plural(vehicle: str) -> str:
    return "buses" if vehicle == "bus" else f"{vehicle}s"


def area_label(areas: list[dict]) -> str:
    in_city = [a["in_philadelphia"] for a in areas]
    if all(in_city):
        return "Neighborhoods"
    if not any(in_city):
        return "Towns"
    return "Neighborhoods and towns"


@dataclass(frozen=True)
class Sources:
    """Everything a page is built from, shared by every route."""
    shapes: dict                   # septashapes.json "routes"
    stops: dict                    # route_stops.json "stops"
    rail_stations: list            # route_stops.json "rail_stations"
    places: dict                   # route_places.json "routes"
    offered: list[str]             # offered routes, in catalog order
    built: frozenset[str] = frozenset()  # routes that get a page in this build


@dataclass(frozen=True)
class Facts:
    ends: tuple[str, str] | None
    streets: list[str]
    centers: list[str]
    rail: list[str]
    connections: list[str]
    stop_lists: list[dict]


def derive_facts(route_id: str, src: Sources) -> Facts:
    directions = src.shapes.get(route_id, [])
    stations = facts_lib.stations(directions, src.stops, src.rail_stations)
    linkable = [r for r in src.offered if r not in SHUTTLES]
    return Facts(
        ends=facts_lib.end_points(directions, src.stops),
        streets=facts_lib.main_streets(directions, src.stops),
        centers=stations["centers"],
        rail=stations["rail"],
        connections=facts_lib.connections(route_id, linkable, src.shapes, src.stops),
        stop_lists=facts_lib.stop_lists(directions, src.stops),
    )


def _section(section_id: str, heading: str, lines: list[str]) -> str:
    body = "\n          ".join(lines)
    return (f'<section aria-labelledby="{section_id}">\n'
            f'          <h2 id="{section_id}">{heading}</h2>\n'
            f'          {body}\n'
            f'        </section>')


def summary_sentence(route_id: str, vehicle: str, facts: Facts) -> str:
    if not facts.ends:
        return ""
    first, last = (html.escape(end) for end in facts.ends)
    subject = f"The Route {route_id} trolley line" if vehicle == "trolley" else f"Route {route_id}"
    if first == last:
        sentence = f"{subject} loops from <strong>{first}</strong>"
    else:
        sentence = f"{subject} runs between <strong>{first}</strong> and <strong>{last}</strong>"
    if facts.streets:
        sentence += f", mostly along {join_list([html.escape(s) for s in facts.streets])}"
    return f"<p>{sentence}.</p>"


def credits_line(areas: list[dict], landmarks: list[str]) -> str:
    credits = []
    if any(a["in_philadelphia"] for a in areas):
        credits.append(f'Neighborhoods: <a href="{NEIGHBORHOODS_SOURCE}">Philadelphia '
                       f'Neighborhoods</a> by Abaca Labs, via OpenDataPhilly, '
                       f'<a href="{NEIGHBORHOODS_LICENSE}" rel="license">CC BY 4.0</a>.')
    if any(not a["in_philadelphia"] for a in areas):
        credits.append("Towns: U.S. Census Bureau.")
    if landmarks:
        credits.append(f'Landmarks: © <a href="{OSM_COPYRIGHT}">OpenStreetMap contributors</a>.')
    return f'<p class="source-note">{" ".join(credits)}</p>' if credits else ""


def goes_section(route_id: str, vehicle: str, facts: Facts, places: dict) -> str:
    """Where the route runs: ends and streets, areas, landmarks, and stations."""
    areas = places.get("areas", [])
    landmarks = places.get("landmarks", [])
    lines = [summary_sentence(route_id, vehicle, facts)]
    if areas:
        names = join_list([html.escape(a["name"]) for a in areas])
        lines.append(f"<p><strong>{area_label(areas)} it stops in:</strong> {names}.</p>")
    if landmarks:
        names = join_list([html.escape(n) for n in landmarks])
        lines.append(f"<p><strong>Near its stops:</strong> {names}.</p>")
    if facts.centers:
        names = join_list([html.escape(n) for n in facts.centers])
        lines.append(f"<p><strong>Transit centers it stops at:</strong> {names}.</p>")
    if facts.rail:
        names = join_list([html.escape(n) for n in facts.rail])
        lines.append(f"<p><strong>Regional Rail stations near its stops:</strong> {names}.</p>")
    lines.append(credits_line(areas, landmarks))
    lines = [line for line in lines if line]
    return _section("goes", f"Where Route {route_id} goes", lines) if lines else ""


def connections_section(route_id: str, facts: Facts, built: frozenset[str]) -> str:
    if not facts.connections:
        return ""
    items = []
    for other in facts.connections:
        label = html.escape(other)
        if other in built:
            items.append(f'<li><a class="route-tag" href="/route/{other}">{label}</a></li>')
        else:
            items.append(f'<li><span class="route-tag">{label}</span></li>')
    count = len(facts.connections)
    return _section("connections", "Connecting routes", [
        f"<p>{count} other {'route stops' if count == 1 else 'routes stop'} within "
        f"{facts_lib.CONNECTION_RADIUS_M} meters of a Route {route_id} stop.</p>",
        f'<ul class="route-tags">{"".join(items)}</ul>',
    ])


def stops_section(facts: Facts) -> str:
    if not facts.stop_lists:
        return ""
    lines = []
    for direction in facts.stop_lists:
        stops = direction["stops"]
        heading = f"{direction['name']} to {stops[-1]}" if direction["name"] else f"To {stops[-1]}"
        items = "".join(f"<li>{html.escape(name)}</li>" for name in stops)
        lines.append(f"<details><summary>{html.escape(heading)} ({len(stops)} stops)</summary>"
                     f'<ol class="stop-list">{items}</ol></details>')
    return _section("stops", "All stops", lines)


def description_text(route_id: str, vehicle: str, facts: Facts) -> str:
    between = f" between {facts.ends[0]} and {facts.ends[1]}" if facts.ends and \
        facts.ends[0] != facts.ends[1] else ""
    text = (f"Track SEPTA Route {route_id} {plural(vehicle)}{between} on a live map, with "
            "detours. Every stop and connection. Free, independent app.")
    if len(text) <= MAX_DESCRIPTION:
        return text
    cut = text[:MAX_DESCRIPTION - 1].rsplit(" ", 1)[0].rstrip(",.")
    return f"{cut}…"


def structured_data(route_id: str, url: str) -> str:
    """JSON-LD: where the page sits on the site, and the app it's about."""
    document = {
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "BreadcrumbList",
                "itemListElement": [
                    {"@type": "ListItem", "position": 1, "name": "BusNeighbor", "item": f"{SITE}/"},
                    {"@type": "ListItem", "position": 2, "name": f"Route {route_id}", "item": url},
                ],
            },
            {
                "@type": "MobileApplication",
                "name": "BusNeighbor",
                "url": f"{SITE}/",
                "applicationCategory": "TravelApplication",
                "operatingSystem": "iOS, Android",
                "isAccessibleForFree": True,
                "offers": {"@type": "Offer", "price": "0", "priceCurrency": "USD"},
                "sameAs": list(STORE_URLS),
            },
        ],
    }
    # "</" can't end the script element early once it's escaped.
    return json.dumps(document, indent=2).replace("</", "<\\/")


def render_page(template: string.Template, route_id: str, name: str, src: Sources) -> str:
    vehicle = vehicle_noun(route_id)
    shapes = src.shapes.get(route_id, [])
    directions = [d["name"] for d in shapes if d.get("name")]
    svg, caption = shape_svg(route_id, shapes)
    facts = derive_facts(route_id, src)
    named = f": {name}" if name else ""
    title = f"SEPTA Route {route_id} {vehicle.title()} Tracker{named} | BusNeighbor"
    url = f"{SITE}/route/{route_id}"
    return template.substitute(
        title=html.escape(title),
        description=html.escape(description_text(route_id, vehicle, facts)),
        url=url,
        go_url=f"{SITE}/go?routes={route_id}",
        schedule_url=SCHEDULE_URL.format(route=route_id),
        route_id=route_id,
        name_html=keep_together(name or f"Route {route_id}"),
        vehicle=vehicle,
        directions=html.escape(" and ".join(directions) if directions else "both ways"),
        shape_svg=svg,
        caption=html.escape(caption),
        goes_section=goes_section(route_id, vehicle, facts, src.places.get(route_id, {})),
        connections_section=connections_section(route_id, facts, src.built),
        stops_section=stops_section(facts),
        structured_data=structured_data(route_id, url),
    )


def build(meta: dict, shapes: dict, names: dict, output_dir: Path, only: list[str] | None,
          places: dict, stops: dict) -> list[str]:
    offered = offered_routes(meta)
    routes = [r for r in offered if r not in SHUTTLES]
    if only:
        unknown = [r for r in only if r not in routes]
        if unknown:
            raise ValueError(f"not offered: {', '.join(unknown)}")
        routes = [r for r in routes if r in only]
    src = Sources(
        shapes=shapes.get("routes", {}),
        stops=stops.get("stops", {}),
        rail_stations=stops.get("rail_stations", []),
        places=places.get("routes", {}),
        offered=offered,
        built=frozenset(routes),
    )
    # Shared pieces (footer, store badges) first, then the per-route values.
    source = build_site.expand_includes(TEMPLATE.read_text(encoding="utf-8"))
    template = string.Template(source)
    output_dir.mkdir(parents=True, exist_ok=True)
    for route_id in routes:
        page = render_page(template, route_id, names.get(route_id, ""), src)
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
    parser.add_argument("--stops", required=True, help="route_stops.json")
    parser.add_argument("--places", default=str(PLACES))
    parser.add_argument("--routes", help="comma-separated subset to build")
    args = parser.parse_args(argv)
    only = [r.strip() for r in args.routes.split(",")] if args.routes else None
    written = build(_load(args.meta), _load(args.shapes), _load(args.names),
                    Path(args.output_dir), only, _load(args.places), _load(args.stops))
    print(f"wrote {len(written)} route pages")
    return 0


if __name__ == "__main__":
    sys.exit(main())
