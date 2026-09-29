"""ReplayPredictor: a held-out hindcast from the LOMO backtest (BACKEND_BUILD_PLAN phase B3).

Real forecasts, real corrections, real IMD truth, real scores, with no final model needed. For an init
date in season Y it reads the backtest fold that held Y out (`cache/fold=Y/`), so every value shown
came from models that never saw that season:

    predictions.parquet     raw, A, B, p_active..p_normal, o_rain (truth), y_synoptic per cell and lead
    DONE                    config_sha256 + git commit of the fold
    qm_counts_B.csv         training days behind each regime's experts
    experts_*.parquet       the fitted curves (written by newer backtests; optional)
    data/raw/hres/dyn_Y.zarr    850 hPa wind and MSLP for the particles and the depression track (optional)
    reports/<id>/verification_report.json   the pooled scores, if a report with the same config exists

Layers the backtest doesn't produce (exceedance, until MODEL_SPEC 12 is built) are left out, never filled.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from regimerain.features.schema import GEO, SYNOPTIC
from regimerain.folds import done_info, fold_dir
from regimerain.runs.fields import RunFields
from regimerain.runs.gridding import land_mask, regime_probs, rows_to_grid

PICKS = ("wettest", "depression", "active", "break")
N_CURVE_Q = 41


class ReplayError(RuntimeError):
    pass


def _fold_preds(cfg: dict, season: int, columns=None) -> pd.DataFrame:
    p = fold_dir(cfg["paths"]["cache"], season) / "predictions.parquet"
    if not p.exists():
        raise ReplayError(f"no backtest predictions for season {season} ({p}); run `backtest --folds {season}`")
    df = pd.read_parquet(p, columns=columns)
    df["init"] = pd.to_datetime(df["init"]).dt.normalize()
    return df


def available_seasons(cfg: dict) -> list[int]:
    return [s for s in done_info(cfg["paths"]["cache"]) if (fold_dir(cfg["paths"]["cache"], s) / "predictions.parquet").exists()]


def pick_init(cfg: dict, how: str) -> date:
    """Choose a showcase init from all held-out seasons.

    wettest: the highest corrected rain anywhere at the first lead. depression / active / break: the
    init whose first-lead valid day has the largest share of cells in that regime by the *observed*
    labels. Labels only choose which past day to show; nothing is computed from them.
    """
    if how not in PICKS:
        raise ReplayError(f"--pick must be one of {', '.join(PICKS)}")
    best = None
    for season in available_seasons(cfg):
        df = _fold_preds(cfg, season, ["init", "lead", "B", "y_synoptic"])
        df = df[df.lead == df.lead.min()]
        if how == "wettest":
            s = df.groupby("init")["B"].max()
        else:
            s = df.assign(hit=df.y_synoptic == SYNOPTIC.index(how)).groupby("init")["hit"].mean()
        init, val = s.idxmax(), float(s.max())
        if best is None or val > best[1]:
            best = (init, val)
    if best is None:
        raise ReplayError("no finished backtest folds with predictions; run `backtest` first")
    return best[0].date()


def find_report(cfg: dict, config_sha: str | None, backtest_id: str | None = None) -> tuple[dict | None, str | None]:
    """The report to show with the replay: the requested id, else the newest with the fold's config hash.

    A report fitted with different settings would show scores for different models, so it is not used.
    """
    from regimerain.runs import store
    reps = store.list_reports(cfg["paths"]["reports"])
    if backtest_id:
        p = store.report_path(cfg["paths"]["reports"], backtest_id)
        if p is None:
            raise ReplayError(f"no report {backtest_id!r} in {cfg['paths']['reports']}")
        rep = json.loads(p.read_text(encoding="utf-8"))
        return rep, rep.get("backtest_id", backtest_id)
    for r in reps:
        if config_sha and r["config_sha256"] == config_sha:
            p = Path(cfg["paths"]["reports"]) / r["dir"] / "verification_report.json"
            rep = json.loads(p.read_text(encoding="utf-8"))
            return rep, rep.get("backtest_id", r["dir"])
    return None, None


def regime_days(cfg: dict, season: int) -> dict | None:
    """Training days behind each regime's curves: the largest n_days among that regime's experts."""
    p = fold_dir(cfg["paths"]["cache"], season) / "qm_counts_B.csv"
    return regime_days_from(pd.read_csv(p)) if p.exists() else None


def regime_days_from(counts: pd.DataFrame) -> dict | None:
    c = counts[counts.regime >= 0]
    out = {SYNOPTIC[int(r)]: int(g.n_days.max()) for r, g in c.groupby("regime")}
    return out or None


def curves(cfg: dict, season: int, lead: int) -> list[dict] | None:
    """Display curves from the fold's saved experts (None if not saved)."""
    d = fold_dir(cfg["paths"]["cache"], season)
    if not (d / "experts_B.parquet").exists():
        return None
    ea = pd.read_parquet(d / "experts_A.parquet") if (d / "experts_A.parquet").exists() else None
    return curves_from(pd.read_parquet(d / "experts_B.parquet"), ea, lead)


def curves_from(eb: pd.DataFrame, ea: pd.DataFrame | None, lead: int) -> list[dict] | None:
    """Per regime (variant B) and the global curve (variant A), each the expert with the most
    training days at this lead, downsampled to N_CURVE_Q quantiles."""
    out = []

    def curve(row, variant, regime):
        f_q, o_q = np.asarray(row["f_q"], float), np.asarray(row["o_q"], float)
        q_full = np.linspace(0, 1, len(f_q))
        idx = np.linspace(0, len(f_q) - 1, N_CURVE_Q).round().astype(int)
        g = int(row["geo"])
        return {"id": f"{variant}/{regime}/{GEO[g] if g >= 0 else 'all'}/zone{int(row['zone'])}/L{lead}".replace("zone-1", "all-India"),
                "variant": variant, "regime": regime, "geo": GEO[g] if g >= 0 else "all", "lead": lead,
                "n_days": int(row["n_days"]), "w_shrink": round(float(row["w_shrink"]), 3),
                "quantiles": q_full[idx].round(3).tolist(), "forecast_mm": f_q[idx].round(1).tolist(),
                "truth_mm": o_q[idx].round(1).tolist()}

    eb = eb[(eb.lead == lead) & (eb.regime >= 0)]
    for r, g in eb.groupby("regime"):
        out.append(curve(g.sort_values("n_days").iloc[-1], "B", SYNOPTIC[int(r)]))
    if ea is not None:
        ea = ea[(ea.lead == lead) & (ea.zone == -1)]
        if len(ea):
            out.append(curve(ea.sort_values("n_days").iloc[-1], "A", "global"))
    return out or None


def _dynamics(cfg: dict, season: int, init: pd.Timestamp, leads, lat, lon) -> dict:
    """850 hPa wind and MSLP on the rain grid (nearest dynamics-domain cell), or {} if not ingested here."""
    import xarray as xr
    p = Path(cfg["paths"]["raw"]) / "hres" / f"dyn_{season}.zarr"
    if not p.exists():
        return {}
    ds = xr.open_zarr(p)
    inits = pd.DatetimeIndex(ds.init.values).normalize()
    if init not in inits:
        return {}
    sub = ds.isel(init=int(inits.get_loc(init))).sel(lead=list(leads)).sel(lat=lat, lon=lon, method="nearest").load()
    out = {k: sub[k].transpose("lead", "lat", "lon").values.astype("float32") for k in ("u850", "v850", "mslp") if k in sub}
    if "mslp" in out and np.nanmedian(out["mslp"]) > 2000:        # Pa -> hPa (TRD 2.3: hPa in display)
        out["mslp"] = out["mslp"] / 100.0
    return out


def replay_fields(cfg: dict, init: date | None = None, pick: str | None = None, backtest_id: str | None = None):
    """RunFields for one held-out init, plus the report, curves and regime-day counts to export with it."""
    from regimerain.static.basic import load_static

    if init is None:
        init = pick_init(cfg, pick or "wettest")
    ts = pd.Timestamp(init).normalize()
    season = ts.year
    info = done_info(cfg["paths"]["cache"]).get(season)
    if info is None:
        raise ReplayError(f"season {season} has no finished backtest fold (cache/fold={season}/DONE)")
    df = _fold_preds(cfg, season)
    df = df[df.init == ts]
    if df.empty:
        raise ReplayError(f"no predictions for init {init} in fold {season}")
    leads = sorted(int(x) for x in df.lead.unique())

    st = load_static(cfg)
    lat, lon = st.lat.values.astype(float), st.lon.values.astype(float)
    shape = (len(leads), len(lat), len(lon))
    land = land_mask(df, leads, shape[1:])
    grid = lambda col: rows_to_grid(df, leads, shape[1:], col, land)
    P = regime_probs(df, leads, shape[1:], land)

    geo = st["geo"].values.astype("int8").copy()
    geo[~land] = -1
    dyn = _dynamics(cfg, season, ts, leads, lat, lon)
    report, report_id = find_report(cfg, info.get("config_sha256"), backtest_id)
    static_mode = st.attrs.get("mode", "full")
    note = "Held-out hindcast from the leave-one-monsoon-out backtest: the fold's models never saw this season."
    if pick:
        note += f" Date picked by: {pick}" + (" (observed labels)." if pick != "wettest" else " (highest corrected rain).")
    if static_mode == "basic":
        note += " Terrain classes not built yet (basic static mode): every cell is plains."
    if report is None:
        note += " No verification report with this backtest's settings was found."

    f = RunFields(
        kind="replay", init=init, source="hres", lat=lat, lon=lon, leads=leads, land=land,
        raw=grid("raw"), corrected=grid("B"), corrected_global=grid("A") if "A" in df else None,
        p_synoptic=P, geo=geo, u850=dyn.get("u850"), v850=dyn.get("v850"), mslp=dyn.get("mslp"),
        p_heavy=grid("p_heavy") if "p_heavy" in df else None,
        p_very_heavy=grid("p_very_heavy") if "p_very_heavy" in df else None,
        truth=grid("o_rain"),
        provenance={"backtest_id": report_id or f"cache-{(info.get('config_sha256') or 'unknown')[:8]}",
                    "held_out_season": season, "config_sha256": info.get("config_sha256"),
                    "git_commit": info.get("git_commit"), "note": note},
    )
    return f.validate(), report, curves(cfg, season, leads[0]), regime_days(cfg, season)
