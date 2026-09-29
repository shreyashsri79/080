"""Interim runs: real forecast data from the Samanvay sister project, before RegimeRain's own model set.

Every value comes from a real source, and each layer states what stands in for the finished component:

    raw         the ECMWF IFS HRES member of a Samanvay hindcast (24 h rain, 1.5 deg), bilinear to 0.25 deg
    corrected   Samanvay's skill-weighted multi-model blend for the same day, weights fitted out of sample
                (its month +-10 days held out). A real post-processed forecast, standing in for the
                regime-aware quantile mapping until the model set is trained.
    regime      the regime Samanvay labels the issue day with (observation-based: active, break,
                depression, normal), held for all leads. On depression days the depression class covers
                land within `labels.depression_radius_km` of the forecast MSLP low (derive.depression_track);
                the rest of the land is `normal`. One-hot: a label, not a classifier probability.
    geo         land from the Survey of India outline, coastal from Natural Earth; orographic needs the DEM
                and is not assigned here.
    absent      850 hPa wind (not in the hindcast cache; Samanvay's wind is 10 m), P(heavy), truth,
                verification. The web hides absent layers; nothing is filled in.

No value here comes from runs/mock.py.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime

import numpy as np
from scipy.interpolate import RegularGridInterpolator
from scipy.ndimage import distance_transform_edt

from regimerain.features.schema import GEO, SYNOPTIC
from regimerain.label.depression import haversine_km
from regimerain.live.wind_source import WindSource, WindUnavailable
from regimerain.runs import geo as geomask
from regimerain.runs.derive import depression_track
from regimerain.runs.fields import RunFields, working_grid

LABELS = {"monsoon active": "active", "monsoon break": "break", "depression": "depression", "monsoon normal": "normal"}
LEADS = [1, 2, 3, 4, 5]


class InterimError(RuntimeError):
    pass


def regime_of(label: str) -> str | None:
    return LABELS.get((label or "").strip().lower())


def jjas_hindcasts(client: WindSource) -> list[dict]:
    """Samanvay hindcasts inside June-September with a regime label we can map."""
    out = []
    for r in client.runs():
        if r.get("kind") != "hindcast" or r.get("status") not in (None, "ok"):
            continue
        init = datetime.strptime(r["init"], "%Y-%m-%dT%H:%MZ").date()
        if 6 <= init.month <= 9:
            out.append({**r, "init_date": init})
    return out


def _coarse(values, g) -> np.ndarray:
    a = np.array([np.nan if v is None else float(v) for v in values], "float64").reshape(g["ny"], g["nx"])
    if np.isnan(a).all():
        raise InterimError("field is all null")
    if np.isnan(a).any():                                    # fill nulls (sea, for rain) from the nearest value
        idx = distance_transform_edt(np.isnan(a), return_distances=False, return_indices=True)
        a = a[tuple(idx)]
    return a


def regrid(values, g, lat, lon) -> np.ndarray:
    """Samanvay cell values (row 0 = south) -> bilinear on the working grid; edges held constant."""
    a = _coarse(values, g)
    clat = g["lat0"] + g["step"] * np.arange(g["ny"])
    clon = g["lon0"] + g["step"] * np.arange(g["nx"])
    LAT, LON = np.meshgrid(np.clip(lat, clat[0], clat[-1]), np.clip(lon, clon[0], clon[-1]), indexing="ij")
    return RegularGridInterpolator((clat, clon), a)(np.stack([LAT, LON], -1)).astype("float32")


def static_layers(cfg: dict, lat, lon) -> tuple[np.ndarray, np.ndarray]:
    land = geomask.mask(lat, lon, "india")
    ne_land = geomask.mask(lat, lon, "land")
    res = float(cfg["grid"]["res_deg"])
    coast_cells = max(1, int(round(float(cfg["static"]["coastal_km"]) / (111.2 * res))))
    g = np.full(land.shape, -1, np.int8)
    g[land] = GEO.index("plains")
    g[land & geomask.near(~ne_land, coast_cells)] = GEO.index("coastal")
    return land, g


def interim_fields(cfg: dict, init: date, client: WindSource | None = None) -> RunFields:
    client = client or WindSource()
    run_id = f"hindcast-{init:%Y%m%d}"
    try:
        meta = client.meta(run_id)
    except WindUnavailable as e:
        raise InterimError(f"Samanvay has no run {run_id}: {e}") from e
    regime = regime_of(meta.get("regime", {}).get("label", ""))
    if regime is None:
        raise InterimError(f"{run_id}: regime label {meta.get('regime')!r} is not one of {sorted(LABELS)}")
    if "hres" not in meta.get("modelsByVar", {}).get("rain", []):
        raise InterimError(f"{run_id} has no HRES rain member")
    g = meta["grid"]
    lat, lon = working_grid(cfg)
    land, geo = static_layers(cfg, lat, lon)
    leads = [L for L in LEADS if L in meta.get("leads", [])]

    raw, blend, mslp = [], [], []
    for L in leads:
        try:
            raw.append(regrid(client.field(run_id, "rain", L, "hres")["values"], g, lat, lon))
            blend.append(regrid(client.field(run_id, "rain", L)["values"], g, lat, lon))
            mslp.append(regrid(client.field(run_id, "mslp", L, "hres")["values"], g, lat, lon))
        except WindUnavailable as e:
            raise InterimError(f"{run_id} lead {L}: {e}") from e
    dry = float(cfg["labels"]["dry_threshold_mm"])

    def rain(stack):
        a = np.clip(np.stack(stack), 0, None)
        a[a < dry] = 0.0
        a[:, ~land] = np.nan
        return a

    shape = (len(leads),) + land.shape
    P = np.zeros(shape + (len(SYNOPTIC),), "float32")
    base = "normal" if regime == "depression" else regime
    P[..., SYNOPTIC.index(base)] = 1.0
    f = RunFields(kind="interim", init=init, source="samanvay-hres", lat=lat, lon=lon, leads=leads, land=land,
                  raw=rain(raw), corrected=rain(blend), p_synoptic=P, geo=geo, mslp=np.stack(mslp))
    lows = depression_track(f) if regime == "depression" else []
    if regime == "depression":
        LAT, LON = np.meshgrid(lat, lon, indexing="ij")
        radius = float(cfg["labels"]["depression_radius_km"])
        for t in lows:
            near = haversine_km(LAT, LON, t["lat"], t["lon"]) <= radius
            P[t["lead"], near] = 0.0
            P[t["lead"], near, SYNOPTIC.index("depression")] = 1.0
    P[:, ~land] = 0.0

    weights = next((n for n in meta.get("notes", []) if n.lower().startswith("weights for this date")), "")
    note = (f"Interim run from real data (Samanvay {run_id}). Raw: ECMWF IFS HRES. Corrected: Samanvay's skill-weighted "
            f"multi-model blend ({', '.join(m for m in meta['modelsByVar']['rain'])}), standing in for the regime-aware "
            f"correction until the model set is trained. {weights} Regime: the issue day's observed label "
            f"({meta['regime']['label']}), held for all leads"
            + (f"; depression within {int(float(cfg['labels']['depression_radius_km']))} km of the forecast MSLP low."
               if regime == "depression" else ".")
            + " Grid: 1.5° values interpolated to 0.25°. Orographic terrain class pending the DEM.")
    return replace(f, p_synoptic=P, provenance={"note": note, "backtest_id": None}).validate()
