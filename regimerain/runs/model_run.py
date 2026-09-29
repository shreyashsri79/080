"""ModelPredictor: a saved model set on one forecast init (BACKEND_BUILD_PLAN phase B4).

`run --source hres --init D --model-set ID` takes the feature rows of init D from the feature table
(built from HRES by `features`, the same rows the backtest used) and runs `ModelSet.predict`, which calls
the backtest's own classifier, smoothing and mixture functions. For a fold model set on its held-out
season this reproduces `predictions.parquet` (the parity test).

Truth is shown only when the init's season was *not* in the model's training seasons, so a final-fit
run never displays an in-sample comparison as if it were a forecast check.
"""
from __future__ import annotations

from datetime import date

import pandas as pd

from regimerain.modelset import ModelSet, resolve
from regimerain.runs.fields import RunFields
from regimerain.runs.gridding import land_mask, regime_probs, rows_to_grid
from regimerain.runs.replay import _dynamics, curves_from, find_report, regime_days_from


class ModelRunError(RuntimeError):
    pass


def init_rows(cfg: dict, init: date, leads) -> pd.DataFrame:
    from regimerain.data import load_table
    try:
        df = load_table(cfg, [init.year], leads)
    except (FileNotFoundError, OSError) as e:
        raise ModelRunError(f"no feature table at {cfg['paths']['table']} ({e}); run `features` for {init.year}") from e
    if df.empty:
        raise ModelRunError(f"feature table has no season {init.year}; run `features --seasons {init.year}`")
    df = df[pd.to_datetime(df["init"]).dt.normalize() == pd.Timestamp(init)]
    if df.empty:
        raise ModelRunError(f"no feature rows for init {init} (JJAS inits only)")
    return df.reset_index(drop=True)


def load_static_for(cfg: dict, ms: ModelSet):
    """The static layer the model set was trained with (its own snapshot), else the configured one."""
    import xarray as xr
    if ms.static_path is not None:
        return xr.open_zarr(ms.static_path).load()
    from regimerain.static.basic import load_static
    return load_static(cfg)


def model_fields(cfg: dict, init: date, model_set: str = "latest"):
    """RunFields for one HRES init under a model set, plus the report, curves and regime-day counts."""
    ms = ModelSet.load(resolve(cfg, model_set))
    leads = [int(L) for L in (ms.info.get("leads") or ms.cfg["leads"])]
    df = init_rows(cfg, init, leads)
    st = load_static_for(cfg, ms)
    held_out = init.year not in [int(s) for s in ms.info.get("fitted_on", [])]
    dyn = _dynamics(cfg, init.year, pd.Timestamp(init), sorted(int(L) for L in df.lead.unique()),
                    st.lat.values.astype(float), st.lon.values.astype(float))
    if held_out:
        extra = f" Season {init.year} was not in its training data, so the IMD comparison is out-of-sample."
    else:
        extra = " This season was in its training data, so no IMD comparison is shown; scores come from the backtest."
    return fields_from_rows(cfg, ms, df, st, init, "hres", dyn, show_truth=held_out, note_extra=extra)


def fields_from_rows(cfg: dict, ms: ModelSet, df: pd.DataFrame, st, init: date, source: str, dyn: dict,
                     show_truth: bool = False, note_extra: str = "", provenance_extra: dict | None = None):
    """Feature rows of one init (all leads) -> ModelSet.predict -> RunFields (+ report, curves, regime days)."""
    leads = sorted(int(L) for L in df.lead.unique())
    lat, lon = st.lat.values.astype(float), st.lon.values.astype(float)
    shape2 = (len(lat), len(lon))
    df = df.reset_index(drop=True)
    pred = ms.predict(df, shape2)
    df = pd.concat([df, pred.drop(columns=["raw"])], axis=1)

    land = land_mask(df, leads, shape2)
    grid = lambda col: rows_to_grid(df, leads, shape2, col, land)
    P = regime_probs(df, leads, shape2, land)
    geo = st["geo"].values.astype("int8").copy()
    geo[~land] = -1

    fitted_on = [int(s) for s in ms.info.get("fitted_on", [])]
    report, report_id = find_report(cfg, ms.info.get("config_sha256"))
    ex = ms.expert_frame()
    curves = curves_from(ex[ex.variant == "B"], ex[ex.variant == "A"] if (ex.variant == "A").any() else None, leads[0])
    days = regime_days_from(ex[ex.variant == "B"])
    src = {"hres": "the HRES init", "gfs": "the live GFS init"}.get(source, source)
    note = f"Model set {ms.id} ({ms.info.get('kind', 'final')}, fitted on seasons {fitted_on or 'unknown'}) on {src}." + note_extra
    if st.attrs.get("mode", "full") == "basic":
        note += " Terrain classes not built yet (basic static mode): every cell is plains."
    truth = grid("o_rain") if show_truth and "o_rain" in df else None
    f = RunFields(
        kind="model", init=init, source=source, lat=lat, lon=lon, leads=leads, land=land,
        raw=grid("f_rain"), corrected=grid("B"), corrected_global=grid("A") if "A" in df else None,
        p_synoptic=P, geo=geo, u850=dyn.get("u850"), v850=dyn.get("v850"), mslp=dyn.get("mslp"),
        truth=truth,
        provenance={"model_set_id": ms.id, "model_hashes": ms.hashes, "config_sha256": ms.info.get("config_sha256"),
                    "git_commit": ms.info.get("git_commit"), "backtest_id": report_id,
                    "held_out_season": init.year if truth is not None else None, "note": note,
                    **(provenance_extra or {})},
    )
    return f.validate(), report, curves, days, ms
