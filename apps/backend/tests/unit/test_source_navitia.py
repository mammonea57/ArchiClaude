"""Unit tests for core.sources.navitia — Navitia/IDFM frequency client.

HTTP calls are intercepted at transport level by pytest-httpx.
"""

from __future__ import annotations

import re

import pytest
from pytest_httpx import HTTPXMock

from core.sources.navitia import LineFrequency, fetch_line_frequency

_NAVITIA_URL_RE = re.compile(
    r"https://prim\.iledefrance-mobilites\.fr/marketplace/v2/navitia.*"
)

_DEPARTURES_RESPONSE = {
    "departures": [
        {"stop_point": {"name": "Nogent - Le Perreux"}, "stop_date_time": {"departure_date_time": "20240417T080000"}},
        {"stop_point": {"name": "Nogent - Le Perreux"}, "stop_date_time": {"departure_date_time": "20240417T080800"}},
        {"stop_point": {"name": "Nogent - Le Perreux"}, "stop_date_time": {"departure_date_time": "20240417T081600"}},
        {"stop_point": {"name": "Nogent - Le Perreux"}, "stop_date_time": {"departure_date_time": "20240417T082400"}},
    ]
}

_EMPTY_DEPARTURES = {"departures": []}


async def test_frequency_calculated(
    httpx_mock: HTTPXMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Returns LineFrequency with avg_interval_minutes computed from departures."""
    monkeypatch.setenv("NAVITIA_API_KEY", "navitia_key_xyz")
    httpx_mock.add_response(url=_NAVITIA_URL_RE, json=_DEPARTURES_RESPONSE)

    result = await fetch_line_frequency(
        stop_name="Nogent - Le Perreux", line_code="A"
    )

    assert result is not None
    assert isinstance(result, LineFrequency)
    assert result.stop_name == "Nogent - Le Perreux"
    assert result.line_code == "A"
    # 4 departures, intervals: 8, 8, 8 minutes → avg = 8 min
    assert result.avg_interval_minutes == pytest.approx(8.0, abs=0.5)
    assert result.is_frequent is True  # ≤ 15 min


async def test_no_api_key(
    httpx_mock: HTTPXMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Returns None without making any HTTP call when API key is absent."""
    monkeypatch.delenv("NAVITIA_API_KEY", raising=False)

    result = await fetch_line_frequency(stop_name="Nogent - Le Perreux", line_code="A")

    assert result is None
    assert len(httpx_mock.get_requests()) == 0


async def test_no_departures_returns_none(
    httpx_mock: HTTPXMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Returns None when no departure data is available."""
    monkeypatch.setenv("NAVITIA_API_KEY", "navitia_key_xyz")
    httpx_mock.add_response(url=_NAVITIA_URL_RE, json=_EMPTY_DEPARTURES)

    result = await fetch_line_frequency(stop_name="Nogent - Le Perreux", line_code="A")

    assert result is None
