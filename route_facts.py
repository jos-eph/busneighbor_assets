"""Facts about a route, derived from the feed, for its web page.

Pure functions over two published documents: septashapes.json (each direction's
stop ids, in order) and route_stops.json (each stop's name and position).
Nothing here is written by hand; a fact the data doesn't support is left out.
"""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict

# Two routes connect when a stop of one is this close to a stop of the other.
# Crossing routes stop on different corners, so shared stop ids miss most of them.
CONNECTION_RADIUS_M = 100

# A station counts as on the route when it is this close to one of its stops.
STATION_RADIUS_M = 250

# A street is a main street when this many of one direction's stops are on it.
MIN_MAIN_STREET_STOPS = 4
MAX_MAIN_STREETS = 5

# Meters per degree of latitude, and of longitude at the equator. The
# equirectangular approximation is well under a meter off at these distances.
METERS_PER_DEGREE_LAT = 110_540.0
METERS_PER_DEGREE_LON = 111_320.0

# The feed's position notes, which mean nothing to a rider: far side, near
# side, mid-block, a numbered boarding spot, and similar.
_POSITION_SUFFIX = re.compile(
    r"\s*-\s*(?:\d+\s*)?(?:FS|NS|MBFS|MBNS|MB)?(?:\s*\d+)?\s*$"
    r"|\s*-\s*(?:onsite|on street)\s*$",
    re.IGNORECASE,
)

# Whole-word abbreviations, expanded only after another word, so "St Joseph's"
# keeps its "St". People search for the full words.
_ABBREVIATIONS = {
    "St": "Street",
    "Av": "Avenue",
    "Ave": "Avenue",
    "Blvd": "Boulevard",
    "Rd": "Road",
    "Pk": "Pike",
    "Dr": "Drive",
    "Ln": "Lane",
    "Sq": "Square",
}
_ABBREVIATION = re.compile(r"(?<=[\w.] )(" + "|".join(_ABBREVIATIONS) + r")\b(?!')")

_STATION_NAME = re.compile(r"\b(?:Station|Transit Center|Transportation Center)\b")


def clean_stop_name(name: str) -> str:
    """A stop name as a rider would say it: "8th St & Walnut St - FS" -> "8th Street & Walnut Street"."""
    name = " ".join(name.split())
    previous = None
    while previous != name:
        previous = name
        name = _POSITION_SUFFIX.sub("", name).strip()
    return _ABBREVIATION.sub(lambda m: _ABBREVIATIONS[m.group(1)], name)


def distance_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    lon_scale = math.cos(math.radians((a[0] + b[0]) / 2))
    return math.hypot((a[0] - b[0]) * METERS_PER_DEGREE_LAT,
                      (a[1] - b[1]) * METERS_PER_DEGREE_LON * lon_scale)


def _known(direction: dict, stops: dict) -> list[str]:
    """The direction's stop ids that the stop table has, in order."""
    return [stop_id for stop_id in direction.get("stops", []) if stop_id in stops]


def _positions(directions: list[dict], stops: dict) -> list[tuple[float, float]]:
    return [(stops[s][1], stops[s][2]) for d in directions for s in _known(d, stops)]


def stop_lists(directions: list[dict], stops: dict) -> list[dict]:
    """Per direction: its name, and its stops' clean names, a repeat in a row dropped."""
    lists = []
    for direction in directions:
        names = []
        for stop_id in _known(direction, stops):
            name = clean_stop_name(stops[stop_id][0])
            if not names or names[-1] != name:
                names.append(name)
        if names:
            lists.append({"name": direction.get("name", ""), "stops": names})
    return lists


def end_points(directions: list[dict], stops: dict) -> tuple[str, str] | None:
    """The first and last stop of the first direction, by clean name."""
    lists = stop_lists(directions, stops)
    if not lists:
        return None
    return lists[0]["stops"][0], lists[0]["stops"][-1]


def main_streets(directions: list[dict], stops: dict) -> list[str]:
    """Streets the route runs along, in route order.

    A stop named "8th Street & Market Street" is on 8th Street: the feed puts
    the street the vehicle travels first. Each direction is counted on its own,
    since a route can run one way on one street and back on another.
    """
    order: list[str] = []
    for direction in stop_lists(directions, stops):
        counts = Counter(name.split(" & ")[0] for name in direction["stops"] if " & " in name)
        for name in direction["stops"]:
            street = name.split(" & ")[0]
            if " & " in name and counts[street] >= MIN_MAIN_STREET_STOPS and street not in order:
                order.append(street)
    return order[:MAX_MAIN_STREETS]


class _Grid:
    """Points bucketed into square cells, for finding the ones near a point."""

    def __init__(self, cell_m: float):
        self.cell_deg = cell_m / METERS_PER_DEGREE_LAT
        self.cells: dict[tuple[int, int], list] = defaultdict(list)

    def _cell(self, lat: float, lon: float) -> tuple[int, int]:
        return (math.floor(lat / self.cell_deg), math.floor(lon / self.cell_deg))

    def add(self, point: tuple[float, float], value) -> None:
        self.cells[self._cell(*point)].append((point, value))

    def near(self, point: tuple[float, float], radius_m: float):
        """Values within radius_m. The cell must be at least radius_m wide in longitude."""
        row, col = self._cell(*point)
        for d_row in (-1, 0, 1):
            for d_col in (-1, 0, 1):
                for other, value in self.cells.get((row + d_row, col + d_col), []):
                    if distance_m(point, other) <= radius_m:
                        yield value


def _cell_size(radius_m: float) -> float:
    # A degree of longitude is shorter than one of latitude, so widen the cell
    # until it covers the radius east and west too (this far north, by about 1.4).
    return radius_m * 1.5


def connections(route_id: str, routes: list[str], shapes: dict, stops: dict) -> list[str]:
    """Other routes, from `routes` and in its order, with a stop near one of this route's."""
    grid = _Grid(_cell_size(CONNECTION_RADIUS_M))
    for other in routes:
        if other != route_id:
            for point in _positions(shapes.get(other, []), stops):
                grid.add(point, other)
    found = set()
    for point in _positions(shapes.get(route_id, []), stops):
        found.update(grid.near(point, CONNECTION_RADIUS_M))
    return [other for other in routes if other in found]


def stations(directions: list[dict], stops: dict, rail_stations: list[list]) -> dict:
    """Transit centers the route stops at, and Regional Rail stations near its stops."""
    centers: list[str] = []
    for direction in stop_lists(directions, stops):
        for name in direction["stops"]:
            if _STATION_NAME.search(name) and name not in centers:
                centers.append(name)
    positions = _positions(directions, stops)
    rail = sorted({clean_stop_name(name) for name, lat, lon in rail_stations
                   if any(distance_m((lat, lon), p) <= STATION_RADIUS_M for p in positions)})
    return {"centers": centers, "rail": rail}
