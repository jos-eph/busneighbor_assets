#!/usr/bin/env python3
"""Shared access to SEPTA's GTFS-realtime feeds.

Every protobuf parse in this repository goes through gtfs-realtime-bindings,
Google's official bindings — no hand-rolled wire-format readers. Anything that
grows a second `.pb` consumer (service alerts, say) imports this module rather
than opening its own parser.

Two rules this module exists to enforce:

  * Presence is checked with HasField, never inferred from a zero value.
    proto2's unset string is "", not None, so `trip.route_id == ""` cannot
    distinguish "no route" from "empty route" on its own.
  * Requests carry an explicit User-Agent. SEPTA's mirror answers 403 to the
    default `Python-urllib/*`.
"""

from __future__ import annotations

import math
import time

from google.protobuf.message import DecodeError
from google.transit import gtfs_realtime_pb2

import fetching

VEHICLE_POSITION_URL = (
    "https://septa-gtfs-mirror.mirrorkey.workers.dev/septa/rtVehiclePosition.pb"
)

# The mirror 403s `Python-urllib/*`, so this is load-bearing, not politeness.
FEED_USER_AGENT = (
    "busneighbor-assets/1.0 (+https://github.com/jos-eph/busneighbor_assets)"
)


def fetch_feed_bytes(url: str, *, sleep=time.sleep) -> bytes:
    return fetching.get_bytes(url, user_agent=FEED_USER_AGENT, sleep=sleep)


def parse_feed(body: bytes) -> gtfs_realtime_pb2.FeedMessage:
    """Parse a GTFS-realtime feed.

    Raises DecodeError on a truncated or corrupt body. Callers must let that
    surface rather than folding it into a generic failure: a corrupt body and
    an empty feed are different diagnoses, and the aggregator's guards depend
    on telling them apart.
    """
    feed = gtfs_realtime_pb2.FeedMessage()
    feed.ParseFromString(body)
    return feed


def route_id_of(vehicle) -> str:
    """The vehicle's route id, or "" when it carries none."""
    if not vehicle.HasField("trip"):
        return ""
    return vehicle.trip.route_id


def has_valid_position(vehicle) -> bool:
    """Whether the vehicle reports a position we are willing to count.

    proto2 marks latitude and longitude required within Position, so their
    presence follows from the HasField check. What remains is policy: a
    non-finite coordinate is a bad reading, and (0, 0) is null island rather
    than Philadelphia. Both occur rarely enough to be worth one line each and
    often enough to matter — two of 757 entities failed this on 2026-09-01.
    """
    if not vehicle.HasField("position"):
        return False
    position = vehicle.position
    if not (math.isfinite(position.latitude) and math.isfinite(position.longitude)):
        return False
    return not (position.latitude == 0.0 and position.longitude == 0.0)


__all__ = [
    "DecodeError",
    "FEED_USER_AGENT",
    "VEHICLE_POSITION_URL",
    "fetch_feed_bytes",
    "gtfs_realtime_pb2",
    "has_valid_position",
    "parse_feed",
    "route_id_of",
]
