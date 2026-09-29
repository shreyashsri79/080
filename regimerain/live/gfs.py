"""NCEP GFS 0.25 deg -> the raw forecast schema of the HRES ingest (MODEL_SPEC 18, PHASE0_FINDINGS).

For one 00 UTC init this writes <raw>/gfs/<YYYYMMDD>/:
    rain.nc   f_rain(lead, lat, lon)  rain-day totals on the rain grid, mm
    dyn.nc    u850 v850 mslp w500 pw ivtx ivty (lead, lat, lon) rain-day means on the dynamics grid
    DONE      what was fetched (written last; a folder without it is incomplete)

Exactly the definitions of `ingest.hres`: rain day L = APCP(0-{27+24(L-1)}) - APCP(0-{3+24(L-1)});
dynamics = mean of the instants at 6/12/18/24 h (+24 per lead); pw/ivt from the same `column_integrals`
over the same pressure levels. GFS files carry a running total from init (confirmed in Phase 0); where
the running total is listed twice (f003, f006) the first message is used.
"""
from __future__ import annotations

import json
import shutil
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import xarray as xr

from regimerain.features.dynamics import column_integrals
from regimerain.ingest.hres import COLUMN_LEVELS, INSTANT_HOURS

LEVEL_RE = "|".join(str(l) for l in COLUMN_LEVELS)


class GFSError(RuntimeError):
    pass


def gfs_dir(cfg: dict, init: date) -> Path:
    return Path(cfg["paths"]["raw"]) / "gfs" / f"{init:%Y%m%d}"


def cached_inits(cfg: dict) -> list[date]:
    """Inits with a complete download, oldest first."""
    root = Path(cfg["paths"]["raw"]) / "gfs"
    return sorted(datetime.strptime(d.name, "%Y%m%d").date() for d in root.glob("[0-9]" * 8) if (d / "DONE").is_file())


def hours_needed(leads) -> tuple[list[int], list[int]]:
    """(APCP running-total hours, instantaneous dynamics hours)."""
    acc = sorted({h for L in leads for h in (3 + 24 * (L - 1), 27 + 24 * (L - 1))})
    inst = sorted({h + 24 * (L - 1) for L in leads for h in INSTANT_HOURS})
    return acc, inst


def _to_box(ds, box):
    """GFS: latitude descending, longitude 0..360 -> ascending lat/lon cut to box."""
    ds = ds.rename({"latitude": "lat", "longitude": "lon"})
    ds = ds.drop_vars([c for c in ds.coords if c not in ("lat", "lon", "isobaricInhPa")])
    ds = ds.isel(lat=slice(None, None, -1))
    lat0, lat1, lon0, lon1 = box
    return ds.sel(lat=slice(lat0, lat1), lon=slice(lon0 % 360, lon1 % 360))


def _retry(fn, what: str, tries: int = 4, wait: float = 5.0, log=print):
    """NOAA's S3 bucket times out now and then; retry with backoff before giving up."""
    import time
    for k in range(tries):
        try:
            return fn()
        except Exception as e:
            if k == tries - 1:
                raise GFSError(f"{what}: {e}") from e
            log(f"{what}: {type(e).__name__}, retry {k + 1}/{tries - 1}")
            time.sleep(wait * (k + 1))


def _first(ds):
    return ds[0] if isinstance(ds, list) else ds


class HerbieSource:
    """Fetches GRIB subsets with Herbie (byte-range downloads of only the listed messages)."""

    def __init__(self, init: date, save_dir: Path):
        self.init, self.save_dir = init, save_dir

    def _h(self, fxx: int):
        from herbie import Herbie
        return Herbie(f"{self.init:%Y-%m-%d} 00:00", model="gfs", product="pgrb2.0p25", fxx=fxx,
                      save_dir=str(self.save_dir), verbose=False)

    def available(self) -> bool:
        try:
            from herbie import Herbie  # noqa: F401
        except ImportError as e:
            raise GFSError(f"live GFS needs the `live` extra: pip install -e '.[live]' ({e})") from e
        try:
            return self._h(123).grib is not None
        except Exception:
            return False

    def prefetch(self, acc_hours, inst_hours, workers: int = 8, log=print) -> None:
        """Download every needed GRIB subset in parallel (network-bound); decoding stays serial because
        eccodes is not thread-safe. The later apcp()/dynamics() calls then read the local files."""
        from concurrent.futures import ThreadPoolExecutor
        jobs = [(h, rf":APCP:surface:0-{h} hour acc") for h in acc_hours]
        for h in inst_hours:
            jobs += [(h, rf":(UGRD|VGRD|SPFH):({LEVEL_RE}) mb:"), (h, ":PRMSL:"), (h, ":VVEL:500 mb:")]

        def once(h, search):
            H = self._h(h)
            try:
                return H.download(search)
            except Exception:
                Path(H.get_localFilePath(search)).unlink(missing_ok=True)     # never reuse a half file
                raise

        def get(job):
            h, search = job
            return _retry(lambda: once(h, search), f"GFS f{h:03d} {search}", log=log)
        with ThreadPoolExecutor(workers) as ex:
            list(ex.map(get, jobs))

    def apcp(self, h: int) -> xr.DataArray:
        ds = _first(self._h(h).xarray(rf":APCP:surface:0-{h} hour acc", remove_grib=True))
        return ds["tp"]

    def dynamics(self, h: int) -> xr.Dataset:
        H = self._h(h)
        lv = _first(H.xarray(rf":(UGRD|VGRD|SPFH):({LEVEL_RE}) mb:", remove_grib=True))
        ms = _first(H.xarray(":PRMSL:", remove_grib=True))
        w = _first(H.xarray(":VVEL:500 mb:", remove_grib=True))
        return xr.Dataset({"u": lv["u"], "v": lv["v"], "q": lv["q"], "prmsl": ms["prmsl"], "w500": w["w"]})


def latest_init(now: datetime | None = None, source_cls=HerbieSource, tmp: Path | None = None) -> date:
    """Newest 00 UTC cycle whose f123 is published (GFS lands ~3.5-5 h after the cycle)."""
    now = now or datetime.now(timezone.utc)
    for back in range(0, 3):
        d = (now - timedelta(days=back)).date()
        if back == 0 and now.hour < 4:
            continue
        if source_cls(d, tmp or Path("/tmp")).available():
            return d
    raise GFSError("no complete GFS 00 UTC cycle in the last 3 days (network down?); use --init cached")


def fetch(cfg: dict, init: date, leads=(1, 2, 3, 4, 5), source=None, log=print, force: bool = False) -> Path:
    """Download and convert one init. Returns the folder; a complete folder is reused unless force."""
    out = gfs_dir(cfg, init)
    if (out / "DONE").is_file() and not force:
        have = json.loads((out / "DONE").read_text()).get("leads", [])
        if set(leads) <= set(have):
            log(f"gfs {init}: cached at {out}")
            return out
        log(f"gfs {init}: cache has leads {have}, need {list(leads)}: downloading again")
    tmp = out.with_name(out.name + ".partial")
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    src = source or HerbieSource(init, tmp / "grib")
    rain_box, dyn_box = cfg["grid"]["rain_box"], cfg["grid"]["dyn_box"]
    acc_h, inst_h = hours_needed(leads)
    try:
        if hasattr(src, "prefetch"):
            log(f"gfs {init}: downloading {len(acc_h)} APCP + {len(inst_h)} dynamics steps")
            src.prefetch(acc_h, inst_h, log=log)
        cum = {}
        for h in acc_h:
            log(f"gfs {init}: APCP 0-{h} h")
            cum[h] = _retry(lambda: _to_box(src.apcp(h).to_dataset(name="tp"), rain_box)["tp"].load(),
                            f"GFS APCP 0-{h} h", log=log)
        rain = []
        for L in leads:
            a, b = 3 + 24 * (L - 1), 27 + 24 * (L - 1)
            r = (cum[b] - cum[a]).clip(min=0)
            rain.append(r.expand_dims(lead=[L]))
        rain = xr.concat(rain, "lead").astype("float32").to_dataset(name="f_rain")
        inst = {}
        for h in inst_h:
            log(f"gfs {init}: dynamics +{h} h")
            ds = _retry(lambda: _to_box(src.dynamics(h), dyn_box).load(), f"GFS dynamics +{h} h", log=log)
            lev = ds.isobaricInhPa.values.astype(float)
            pw, ivtx, ivty = column_integrals(ds.q.values, ds.u.values, ds.v.values, lev, level_axis=0)
            k850 = int(np.argmin(np.abs(lev - 850)))
            dims = ("lat", "lon")
            inst[h] = xr.Dataset({
                "u850": (dims, ds.u.values[k850]), "v850": (dims, ds.v.values[k850]),
                "mslp": (dims, ds.prmsl.values), "w500": (dims, ds.w500.values),
                "pw": (dims, pw), "ivtx": (dims, ivtx), "ivty": (dims, ivty)},
                coords={"lat": ds.lat.values, "lon": ds.lon.values})
        dyn = xr.concat([xr.concat([inst[h + 24 * (L - 1)] for h in INSTANT_HOURS], "hour").mean("hour").expand_dims(lead=[L])
                         for L in leads], "lead").astype("float32")
        rain.to_netcdf(tmp / "rain.nc")
        dyn.to_netcdf(tmp / "dyn.nc")
        shutil.rmtree(tmp / "grib", ignore_errors=True)
        (tmp / "DONE").write_text(json.dumps({"init": init.isoformat(), "leads": list(leads), "apcp_hours": acc_h,
                                              "instant_hours": inst_h,
                                              "fetched_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}))
    except Exception:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    shutil.rmtree(out, ignore_errors=True)
    tmp.rename(out)
    return out


def load(folder: Path) -> tuple[xr.Dataset, xr.Dataset, dict]:
    return (xr.open_dataset(folder / "rain.nc").load(), xr.open_dataset(folder / "dyn.nc").load(),
            json.loads((folder / "DONE").read_text()))
