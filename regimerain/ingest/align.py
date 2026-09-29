"""Align forecast precipitation to the IMD rain day, 03 UTC -> 03 UTC (TRD section 2.2, MODEL_SPEC 4.2).

HRES in WeatherBench2 has 6-hourly leads, so the 03 UTC boundaries are reached by linear
interpolation of CUMULATIVE precipitation (equivalent to a constant rate within each 6-h block).
Rain day L of a 00 UTC run covers forecast hours [3 + 24(L-1), 27 + 24(L-1)].
"""
from __future__ import annotations

import numpy as np
import xarray as xr

LEADS = (1, 2, 3, 4, 5)


def rainday_window(lead: int) -> tuple[float, float]:
    return 3.0 + 24 * (lead - 1), 27.0 + 24 * (lead - 1)


def to_hours(da: xr.DataArray, dim: str = "prediction_timedelta") -> xr.DataArray:
    """Replace a timedelta lead dimension with a float `hour` dimension."""
    hrs = (da[dim] / np.timedelta64(1, "h")).astype("float64")
    return da.assign_coords(hour=(dim, hrs.values)).swap_dims({dim: "hour"}).drop_vars(dim)


def cumulative_from_buckets(tp: xr.DataArray) -> xr.DataArray:
    """tp: accumulations over consecutive non-overlapping windows ending at each `hour` (>0).

    Returns cumulative precipitation since init with an explicit 0 at hour 0.
    """
    tp = tp.clip(min=0)
    tp = tp.sel(hour=tp.hour > 0)
    cum = tp.cumsum("hour")
    zero = xr.zeros_like(cum.isel(hour=0)).assign_coords(hour=0.0)
    return xr.concat([zero, cum], dim="hour")


def rainday_totals(cum: xr.DataArray, leads=LEADS, scale: float = 1000.0) -> xr.DataArray:
    """cum: cumulative precip since init with a float `hour` coord (metres by default).

    Returns rain-day totals in mm with dims (lead, ...) and a `valid` coord when `init` exists.
    """
    out = []
    for L in leads:
        a, b = rainday_window(L)
        if float(cum.hour.max()) < b:
            raise ValueError(f"lead {L} needs forecast hour {b}, data ends at {float(cum.hour.max())}")
        tot = cum.interp(hour=b) - cum.interp(hour=a)
        out.append(tot.expand_dims(lead=[L]))
    rain = (xr.concat(out, dim="lead") * scale).clip(min=0.0)
    if "hour" in rain.coords:
        rain = rain.drop_vars("hour")
    if "init" in rain.coords:
        valid = rain["init"].dt.floor("D") + (rain["lead"] - 1) * np.timedelta64(1, "D")
        rain = rain.assign_coords(valid=valid)
    return rain.rename("f_rain").astype("float32")


def rainday_mean_instant(da: xr.DataArray, leads=LEADS) -> xr.DataArray:
    """Mean of instantaneous fields at hours 6, 12, 18, 24 (+24(L-1)) inside each rain day."""
    out = []
    for L in leads:
        hrs = [h + 24 * (L - 1) for h in (6, 12, 18, 24)]
        out.append(da.sel(hour=hrs).mean("hour").expand_dims(lead=[L]))
    return xr.concat(out, dim="lead")
