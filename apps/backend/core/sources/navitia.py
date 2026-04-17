"""Navitia / IDFM frequency client.

Queries the Île-de-France Mobilités (IDFM) Navitia marketplace API for
departure schedules at a given stop and line, then computes average headway.

Requires NAVITIA_API_KEY environment variable.
Returns None gracefully when key is absent or the request fails.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime

from core.http_client import fetch_json

_NAVITIA_BASE = "https://prim.iledefrance-mobilites.fr/marketplace/v2/navitia"

_logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LineFrequency:
    """Computed headway for a line at a given stop."""

    stop_name: str
    line_code: str
    avg_interval_minutes: float
    is_frequent: bool  # True when average interval ≤ 15 minutes


def _parse_navitia_dt(raw: str) -> datetime | None:
    """Parse a Navitia datetime string (YYYYMMDDTHHmmss) into a :class:`datetime`."""
    try:
        return datetime.strptime(raw, "%Y%m%dT%H%M%S")
    except (ValueError, TypeError):
        return None


async def fetch_line_frequency(
    *, stop_name: str, line_code: str
) -> LineFrequency | None:
    """Fetch scheduled departures and compute average headway for a line at a stop.

    Args:
        stop_name: Human-readable stop name (used as a query filter).
        line_code: Line identifier (e.g. "A", "B", "13").

    Returns:
        A :class:`LineFrequency` with computed average interval, or ``None``
        when the API key is absent, no departures are found, or an error occurs.
    """
    api_key = os.environ.get("NAVITIA_API_KEY")
    if not api_key:
        return None

    # Build the departures URL — query by stop name and line code
    url = f"{_NAVITIA_BASE}/coverage/fr-idf/departures"
    params: dict[str, str | int | float] = {
        "filter": f"stop_point.name={stop_name} and line.code={line_code}",
        "count": 20,
        "apikey": api_key,
    }

    try:
        data = await fetch_json(url, params=params)
    except Exception:
        _logger.warning("Navitia departures request failed — returning None", exc_info=True)
        return None

    departures = data.get("departures", [])
    if not departures:
        return None

    # Extract departure times and compute intervals
    times: list[datetime] = []
    for dep in departures:
        sdt = dep.get("stop_date_time", {})
        raw_dt = sdt.get("departure_date_time")
        dt = _parse_navitia_dt(raw_dt) if raw_dt else None
        if dt:
            times.append(dt)

    if len(times) < 2:
        return None

    times.sort()
    intervals_s = [
        (times[i + 1] - times[i]).total_seconds() for i in range(len(times) - 1)
    ]
    avg_interval_s = sum(intervals_s) / len(intervals_s)
    avg_interval_min = avg_interval_s / 60.0

    return LineFrequency(
        stop_name=stop_name,
        line_code=line_code,
        avg_interval_minutes=round(avg_interval_min, 2),
        is_frequent=avg_interval_min <= 15.0,
    )
