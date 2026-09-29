"""Samanvay 10 m wind source (temporary): cell lookup, direction, staleness, nulls, outages, caching."""
from datetime import datetime, timezone

import pytest

from regimerain.live.wind_source import WindSource, WindUnavailable

GRID = {"lat0": 6.0, "lon0": 66.0, "step": 1.5, "ny": 23, "nx": 23}
NOW = datetime(2026, 9, 30, 12, tzinfo=timezone.utc)


def fake_api(init="2026-09-29T00:00Z", speed=5.0, u=0.0, v=-5.0, calls=None):
    n = GRID["ny"] * GRID["nx"]

    def fetch(url):
        if calls is not None:
            calls.append(url)
        if url.endswith("/api/runs"):
            return [{"id": "hind-2020", "kind": "hindcast", "init": "2020-07-01T00:00Z"},
                    {"id": "live-x", "kind": "live", "init": init}]
        if "/api/runs/" in url:
            return {"grid": GRID, "leads": list(range(1, 11))}
        if "/api/field" in url:
            vals = [1.0] * n
            k = round((20 - 6) / 1.5) * 23 + round((85 - 66) / 1.5)
            vals[k] = speed
            us, vs = [0.0] * n, [0.0] * n
            us[k], vs[k] = u, v
            return {"var": "wind", "lead": 1, "units": "m/s", "values": vals, "u": us, "v": vs}
        raise AssertionError(url)
    return fetch


def test_cell_lookup_direction_and_labels():
    w = WindSource(fetch=fake_api(u=0.0, v=-5.0), now=lambda: NOW).get_wind(20.1, 84.9, 2)
    assert w["speed_ms"] == 5.0 and w["from_deg"] == 0.0                   # v < 0: blowing southward, from the north
    assert (w["cell_lat"], w["cell_lon"]) == (6.0 + 9 * 1.5, 66.0 + 13 * 1.5)
    assert w["kind"] == "forecast" and w["init"] == "2026-09-29T00:00Z" and w["valid_utc"] == "2026-10-01T00:00Z"
    assert WindSource(fetch=fake_api(u=5.0, v=0.0), now=lambda: NOW).get_wind(20, 85)["from_deg"] == 270.0   # westerly


def test_stale_offgrid_null_and_down_are_unavailable():
    with pytest.raises(WindUnavailable, match="more than 2 days"):
        WindSource(fetch=fake_api(init="2026-09-27T00:00Z"), now=lambda: NOW).get_wind(20, 85)
    ok = WindSource(fetch=fake_api(), now=lambda: NOW)
    with pytest.raises(WindUnavailable, match="outside"):
        ok.get_wind(45.0, 85.0)
    with pytest.raises(WindUnavailable, match="lead day"):
        ok.get_wind(20, 85, 11)
    with pytest.raises(WindUnavailable, match="no wind value"):
        WindSource(fetch=fake_api(speed=None), now=lambda: NOW).get_wind(20, 85)

    def down(url):
        raise WindUnavailable("Samanvay API unreachable: timeout")
    with pytest.raises(WindUnavailable, match="unreachable"):
        WindSource(fetch=down, now=lambda: NOW).get_wind(20, 85)


def test_responses_are_cached():
    calls = []
    w = WindSource(fetch=fake_api(calls=calls), now=lambda: NOW)
    w.get_wind(20, 85)
    n = len(calls)
    w.get_wind(21, 86)
    assert len(calls) == n                                                  # no second round-trip within the hour
