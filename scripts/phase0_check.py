"""Phase 0 data checks (docs/MODEL_SPEC.md section 3). Run on a laptop or in Colab:

    pip install -e ".[data,live]"
    python scripts/phase0_check.py            # all checks
    python scripts/phase0_check.py hres imd   # selected checks

Each check prints PASS/FAIL with what it found. Paste the output into docs/PHASE0_FINDINGS.md.
Nothing here writes large files; the IMD check downloads one year (~25 MB) into ./data/raw/imd_probe.
"""
from __future__ import annotations

import sys
import traceback
from datetime import datetime, timedelta, timezone

import yaml

HRES_URL = "gs://weatherbench2/datasets/hres/2016-2022-0012-1440x721.zarr"
IBTRACS_NI = ("https://www.ncei.noaa.gov/data/international-best-track-archive-for-climate-stewardship-ibtracs/"
              "v04r01/access/csv/ibtracs.NI.list.v04r01.csv")
RMM_URL = "http://www.bom.gov.au/climate/mjo/graphics/rmm.74toRealtime.txt"
NEEDED_LEVELS = {1000, 925, 850, 700, 600, 500, 400, 300}


def check_hres():
    import xarray as xr
    ds = xr.open_zarr(HRES_URL, storage_options={"token": "anon"})
    precip = [v for v in ds.data_vars if "precip" in v]
    info = {
        "precip_vars": {v: {"units": ds[v].attrs.get("units"), "dims": list(ds[v].dims)} for v in precip},
        "first_leads_h": [float(x / 3.6e12) for x in ds.prediction_timedelta.values[:6].astype("int64")],
        "lat_ascending": bool(ds.latitude.values[0] < ds.latitude.values[-1]),
        "levels": sorted(int(x) for x in ds.level.values) if "level" in ds.dims else None,
        "vars": sorted(ds.data_vars),
    }
    missing_levels = NEEDED_LEVELS - set(info["levels"] or [])
    ok = bool(precip) and not missing_levels
    return ok, dict(info, missing_levels=sorted(missing_levels))


def check_imd():
    import imdlib as imd
    imd.get_data("rain", 2016, 2016, fn_format="yearwise", file_dir="data/raw/imd_probe")
    da = imd.open_data("rain", 2016, 2016, "yearwise", "data/raw/imd_probe").get_xarray()["rain"]
    da = da.where(da > -998)
    return True, {"dims": dict(da.sizes), "lat_range": [float(da.lat.min()), float(da.lat.max())],
                  "lon_range": [float(da.lon.min()), float(da.lon.max())],
                  "jul_mean_mm": float(da.sel(time=da.time.dt.month == 7).mean())}


def check_ibtracs():
    import pandas as pd
    df = pd.read_csv(IBTRACS_NI, skiprows=[1], low_memory=False, nrows=50000)
    cols = [c for c in ("SID", "ISO_TIME", "LAT", "LON", "NEWDELHI_GRADE", "NEWDELHI_WIND") if c in df.columns]
    return "NEWDELHI_GRADE" in df.columns, {"columns_found": cols, "rows_read": len(df)}


def check_mjo():
    import pandas as pd
    df = pd.read_csv(RMM_URL, sep=r"\s+", skiprows=2, header=None, usecols=range(7),
                     names=["year", "month", "day", "rmm1", "rmm2", "phase", "amplitude"])
    df = df[df.amplitude < 100]
    return len(df) > 1000, {"first": df.iloc[0].tolist(), "last": df.iloc[-1].tolist()}


def check_gfs():
    from herbie import Herbie
    init = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d 00:00")
    windows = {}
    for fxx in (3, 6, 9, 12, 27):
        inv = Herbie(init, model="gfs", product="pgrb2.0p25", fxx=fxx).inventory(":APCP:")
        windows[fxx] = inv["search_this"].tolist() if "search_this" in inv else inv.to_string()
    return True, {"init": init, "apcp_messages": windows}


CHECKS = {"hres": check_hres, "imd": check_imd, "ibtracs": check_ibtracs, "mjo": check_mjo, "gfs": check_gfs}


def main(names: list[str]) -> int:
    names = names or list(CHECKS)
    results = {}
    for name in names:
        try:
            ok, info = CHECKS[name]()
        except Exception as exc:  # report and continue with the other checks
            ok, info = False, {"error": f"{type(exc).__name__}: {exc}", "trace": traceback.format_exc(limit=2)}
        results[name] = {"status": "PASS" if ok else "FAIL", **info}
        print(f"\n=== {name}: {'PASS' if ok else 'FAIL'} ===")
        print(yaml.safe_dump(info, sort_keys=False, width=110))
    failed = [n for n, r in results.items() if r["status"] != "PASS"]
    print("\nSummary:", {n: r["status"] for n, r in results.items()})
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
