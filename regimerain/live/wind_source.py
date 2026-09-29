"""Temporary 10 m wind source: the Samanvay forecast API (sister project).

Every call to Samanvay goes through this module, so the source can be swapped later without touching
anything else. The public surface is `get_wind(lat, lon, lead_day)` and `WindUnavailable`.

What it is: a *forecast* (a learned blend of ECMWF IFS, ECMWF AIFS and NOAA GFS), 10 m wind, on a 1.5 deg
grid (about 167 km) over 6-39 N, 66-99 E. `lead = d` is an instant, valid at 00 UTC d days after the run's init,
not a daily mean. It is not the 850 hPa wind the regime classifier uses (that comes from HRES/GFS through
`features`), and it must never be fed to a model.

Rules kept here (from the Samanvay handover):
  - server-side only (the API sends no CORS headers); 30 s timeout and 1 retry (cold start ~10 s)
  - at most one refresh per hour (new runs appear once a day)
  - newest live run older than 2 days = stale -> WindUnavailable, never old data passed off as current
  - API down, point off the grid, or a null cell -> WindUnavailable; values are never invented
  - every result carries the run init and the valid time, labelled "forecast"
"""
from __future__ import annotations

import json
import math
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Callable

BASE = "https://shreyashsri79--samanvay-web.modal.run"
TIMEOUT_S = 30
CACHE_S = 3600
STALE_AFTER = timedelta(days=2)


class WindUnavailable(RuntimeError):
    """Show "wind data unavailable"; the message says why."""


def _http_json(url: str) -> object:
    last = None
    for attempt in range(2):                                  # 1 retry: the first call can hit a cold start
        try:
            with urllib.request.urlopen(url, timeout=TIMEOUT_S) as r:
                return json.load(r)
        except (urllib.error.URLError, TimeoutError, ValueError, OSError) as e:
            last = e
            if attempt == 0:
                time.sleep(1)
    raise WindUnavailable(f"Samanvay API unreachable: {last}")


class WindSource:
    def __init__(self, base: str = BASE, fetch: Callable[[str], object] = _http_json,
                 now: Callable[[], datetime] = lambda: datetime.now(timezone.utc), cache_s: float = CACHE_S):
        self.base, self.fetch, self.now, self.cache_s = base.rstrip("/"), fetch, now, cache_s
        self._cache: dict[str, tuple[float, object]] = {}
        self._lock = threading.Lock()

    def _get(self, path: str, **params) -> object:
        url = f"{self.base}{path}" + (f"?{urllib.parse.urlencode(params)}" if params else "")
        with self._lock:
            hit = self._cache.get(url)
            if hit and time.monotonic() - hit[0] < self.cache_s:
                return hit[1]
        data = self.fetch(url)
        with self._lock:
            self._cache[url] = (time.monotonic(), data)
        return data

    # ---- raw access, shared by get_wind and the interim run producer (runs/interim.py)
    def runs(self) -> list[dict]:
        runs = self._get("/api/runs")
        if not isinstance(runs, list):
            raise WindUnavailable("Samanvay /api/runs is not a list")
        return runs

    def meta(self, run_id: str) -> dict:
        return self._get(f"/api/runs/{urllib.parse.quote(run_id)}")

    def field(self, run_id: str, var: str, lead: int, model: str | None = None) -> dict:
        """One variable at one lead: {values, u, v, units}; `model` picks a member (e.g. hres), else the blend."""
        params = {"run": run_id, "var": var, "lead": int(lead)}
        if model:
            params["model"] = model
        return self._get("/api/field", **params)

    def latest_run(self) -> dict:
        runs = self._get("/api/runs")
        live = next((r for r in runs if isinstance(r, dict) and r.get("kind") == "live"), None) if isinstance(runs, list) else None
        if live is None:
            raise WindUnavailable("Samanvay has no live run")
        init = datetime.strptime(live["init"], "%Y-%m-%dT%H:%MZ").replace(tzinfo=timezone.utc)
        if self.now() - init > STALE_AFTER:
            raise WindUnavailable(f"newest Samanvay run {live['id']} (init {live['init']}) is more than 2 days old")
        return {**live, "init_dt": init}

    def get_wind(self, lat: float, lon: float, lead_day: int = 1) -> dict:
        run = self.latest_run()
        meta = self._get(f"/api/runs/{urllib.parse.quote(run['id'])}")
        g = meta["grid"]
        if int(lead_day) not in [int(x) for x in meta.get("leads", [])]:
            raise WindUnavailable(f"lead day {lead_day} not in run {run['id']}")
        i, j = round((lat - g["lat0"]) / g["step"]), round((lon - g["lon0"]) / g["step"])
        if not (0 <= i < g["ny"] and 0 <= j < g["nx"]):
            raise WindUnavailable(f"({lat}, {lon}) is outside the Samanvay grid")
        f = self._get("/api/field", run=run["id"], var="wind", lead=int(lead_day))
        k = i * g["nx"] + j
        speed, u, v = f["values"][k], f["u"][k], f["v"][k]
        if speed is None:
            raise WindUnavailable(f"no wind value at cell ({i}, {j}) for lead {lead_day}")
        direction = None if u is None or v is None else round((270 - math.degrees(math.atan2(v, u))) % 360, 1)
        valid = run["init_dt"] + timedelta(days=int(lead_day))
        return {"kind": "forecast", "source": "Samanvay blend (ECMWF IFS, ECMWF AIFS, NOAA GFS), 10 m",
                "run": run["id"], "init": run["init"], "valid_utc": valid.strftime("%Y-%m-%dT%H:%MZ"),
                "lead_day": int(lead_day), "speed_ms": float(speed), "from_deg": direction,
                "cell_lat": g["lat0"] + i * g["step"], "cell_lon": g["lon0"] + j * g["step"], "cell_km": round(g["step"] * 111)}


_default = WindSource()


def get_wind(lat: float, lon: float, lead_day: int = 1) -> dict:
    """10 m wind forecast at the 1.5 deg cell containing (lat, lon). Raises WindUnavailable."""
    return _default.get_wind(lat, lon, lead_day)
