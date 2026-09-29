"""One live GFS init -> features -> ModelSet -> RunFields (BACKEND_BUILD_PLAN B5, MODEL_SPEC 18.1).

Feature rows come from `features.build.rows_for_init`, the function that built the training table,
so the only thing that changes between training and live is the forecast source (HRES -> GFS). That
transfer is disclosed in every live run's note.
"""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from regimerain.features.build import DYN_VARS, _rmm, rows_for_init
from regimerain.live import gfs
from regimerain.modelset import ModelSet, resolve
from regimerain.runs.model_run import fields_from_rows, load_static_for


def resolve_init(cfg: dict, init: str | None) -> date:
    """`today` (default) = newest published cycle, `cached` = newest complete download, or YYYY-MM-DD."""
    if init in (None, "today"):
        return gfs.latest_init(tmp=gfs.gfs_dir(cfg, date.today()).parent / ".probe")
    if init == "cached":
        have = gfs.cached_inits(cfg)
        if not have:
            raise gfs.GFSError(f"no cached GFS download in {cfg['paths']['raw']}/gfs; run once with --init today")
        return have[-1]
    try:
        return date.fromisoformat(init)
    except ValueError:
        raise gfs.GFSError(f"--init must be today, cached or YYYY-MM-DD, got {init!r}") from None


def frozen_cfg(cfg: dict, ms: ModelSet) -> dict:
    """The model set's frozen settings (features, grid, thresholds, leads) with this machine's paths:
    live features must be computed exactly as in training, whatever the local config says."""
    return {**ms.cfg, "paths": cfg["paths"]}


def gfs_fields(cfg: dict, init: date, model_set: str = "latest", source=None, log=print):
    ms = ModelSet.load(resolve(cfg, model_set))
    cfg = frozen_cfg(cfg, ms)
    leads = [int(L) for L in (ms.info.get("leads") or cfg["leads"])]
    folder = gfs.fetch(cfg, init, leads, source=source, log=log)
    rain, dyn, meta = gfs.load(folder)
    st = load_static_for(cfg, ms)
    lat_r, lon_r = st.lat.values.astype(float), st.lon.values.astype(float)
    rain = rain.sel(lat=lat_r, lon=lon_r, method="nearest")
    latd, lond = dyn.lat.values, dyn.lon.values
    rmm = _rmm(cfg)
    fcfg, dry = cfg["features"], float(cfg["labels"]["dry_threshold_mm"])
    frames = []
    for L in leads:
        d = {k: dyn[k].sel(lead=L).values.astype("float64") for k in DYN_VARS}
        df = rows_for_init(rain["f_rain"].sel(lead=L).values, d, latd, lond, st, pd.Timestamp(init), L, rmm, fcfg)
        df["lead"] = np.int16(L)
        df.loc[df.f_rain < dry, "f_rain"] = 0.0
        frames.append(df)
    df = pd.concat(frames, ignore_index=True)

    near = dyn.sel(lat=lat_r, lon=lon_r, method="nearest")
    show = {k: near[k].transpose("lead", "lat", "lon").values.astype("float32") for k in ("u850", "v850", "mslp")}
    show["mslp"] = show["mslp"] / 100.0                               # Pa -> hPa for display
    from regimerain.ingest.mjo import value_on
    mjo = value_on(rmm, pd.Timestamp(init)) if rmm is not None else {"stale": True}
    note = (" Live forecast: the models were trained on ECMWF HRES and applied here to NCEP GFS, so skill may"
            " differ from the backtest scores shown." +
            (" MJO input neutral (no RMM value within 3 days)." if mjo.get("stale") else ""))
    return fields_from_rows(cfg, ms, df, st, init, "gfs", show, show_truth=False, note_extra=note)
