"""Live GFS path (BACKEND_BUILD_PLAN B5) with a fake GRIB source: conversion to the raw schema, features
through the training code, a model-set run export, the cache, and the API job runner."""
import json
import time
from datetime import date

import numpy as np
import pytest
import xarray as xr

pytest.importorskip("lightgbm")
pytest.importorskip("zarr")

from regimerain import cli
from regimerain.ingest.hres import COLUMN_LEVELS
from regimerain.live import gfs
from regimerain.runs import contract as C

LAT = np.arange(40.0, -0.01, -0.25)          # GFS order: latitude descending, longitude 0..360
LON = np.arange(40.0, 110.01, 0.25)


class FakeGFS:
    calls = 0

    def __init__(self, *_):
        pass

    def apcp(self, h):
        FakeGFS.calls += 1
        rate = 0.5 + np.abs(np.sin(np.deg2rad(LAT)))[:, None] * np.ones(len(LON))   # mm/h
        return xr.DataArray((rate * h).astype("float32"), dims=("latitude", "longitude"),
                            coords={"latitude": LAT, "longitude": LON}, name="tp")

    def dynamics(self, h):
        rng = np.random.default_rng(h)
        lev = np.array(COLUMN_LEVELS[::-1], float)
        shp = (len(lev), len(LAT), len(LON))
        c3 = {"isobaricInhPa": lev, "latitude": LAT, "longitude": LON}
        c2 = {"latitude": LAT, "longitude": LON}
        d3 = ("isobaricInhPa", "latitude", "longitude")
        return xr.Dataset({
            "u": (d3, (8 + rng.normal(0, 1, shp)).astype("float32")), "v": (d3, rng.normal(0, 2, shp).astype("float32")),
            "q": (d3, np.full(shp, 0.01, "float32") * (lev[:, None, None] / 1000)),
            "prmsl": (("latitude", "longitude"), (100500 + rng.normal(0, 150, shp[1:])).astype("float32")),
            "w500": (("latitude", "longitude"), rng.normal(0, 0.1, shp[1:]).astype("float32"))}, coords=c3 | c2)


def test_fetch_matches_the_hres_definitions(pipeline):
    _, _, cfg = pipeline
    out = gfs.fetch(cfg, date(2021, 8, 1), leads=[1], source=FakeGFS(), log=lambda m: None)
    rain, dyn, meta = gfs.load(out)
    assert meta["apcp_hours"] == [3, 27] and meta["instant_hours"] == [6, 12, 18, 24]
    np.testing.assert_allclose(rain.f_rain.sel(lead=1).values, (0.5 + np.abs(np.sin(np.deg2rad(rain.lat.values))))[:, None] * 24
                               * np.ones(rain.sizes["lon"]), rtol=1e-5)          # 0-27 h minus 0-3 h
    assert np.all(np.diff(rain.lat.values) > 0) and float(rain.lat[0]) == 10.0 and float(rain.lon[-1]) == 75.0
    assert set(dyn.data_vars) == {"u850", "v850", "mslp", "w500", "pw", "ivtx", "ivty"} and float(dyn.pw.mean()) > 0
    n = FakeGFS.calls
    gfs.fetch(cfg, date(2021, 8, 1), leads=[1], source=FakeGFS(), log=lambda m: None)
    assert FakeGFS.calls == n and gfs.cached_inits(cfg) == [date(2021, 8, 1)]         # cached: no re-download


def test_gfs_run_exports_a_valid_model_run(pipeline, monkeypatch):
    root, cfgs, cfg = pipeline
    if not list((root / "models").glob("*/hashes.json")):
        assert cli.main(["fit-final"] + cfgs) == 0
    monkeypatch.setattr(gfs, "HerbieSource", FakeGFS)
    assert cli.main(["run", "--source", "gfs", "--init", "cached"] + cfgs) == 0
    web = next((root / "runs").glob("20210801T00Z_gfs_*/web"))
    assert C.check_folder(web) == []
    m = json.loads((web / "manifest.json").read_text())
    assert m["kind"] == "model" and not m["synthetic"] and m["forecast_source"] == "NCEP GFS 0.25"
    assert "truth" not in m["layers"] and "wind850" in m["layers"]
    assert "HRES and applied here to NCEP GFS" in m["provenance"]["note"]


def test_live_api_job(pipeline):
    from fastapi.testclient import TestClient
    from regimerain.api.app import create_app
    from regimerain.api.jobs import LiveJobs
    root, _, _ = pipeline

    def runner(log):
        log("working")
        time.sleep(0.3)
        return "20210801T00Z_gfs_x"
    c = TestClient(create_app(root / "runs", live=LiveJobs(runner)))
    assert c.post("/api/runs/live").status_code == 202
    assert c.post("/api/runs/live").status_code == 409                       # one at a time
    for _ in range(50):
        st = c.get("/api/runs/live").json()
        if st["status"] != "running":
            break
        time.sleep(0.05)
    assert st["status"] == "done" and st["run_id"] == "20210801T00Z_gfs_x" and any("working" in l for l in st["log_tail"])

    def boom(log):
        raise RuntimeError("no GFS")
    c = TestClient(create_app(root / "runs", live=LiveJobs(boom)))
    c.post("/api/runs/live")
    time.sleep(0.2)
    st = c.get("/api/runs/live").json()
    assert st["status"] == "failed" and st["error"] == "no GFS"
    assert TestClient(create_app(root / "runs")).post("/api/runs/live").status_code == 503


def test_cache_with_fewer_leads_is_refetched_and_partials_ignored(pipeline):
    _, _, cfg = pipeline
    d = date(2021, 8, 2)
    gfs.fetch(cfg, d, leads=[1], source=FakeGFS(), log=lambda m: None)
    stray = gfs.gfs_dir(cfg, date(2021, 8, 3)).with_name("20210803.partial")
    stray.mkdir(parents=True, exist_ok=True)
    (stray / "DONE").write_text("{}")
    assert d in gfs.cached_inits(cfg) and all(isinstance(x, date) for x in gfs.cached_inits(cfg))
    n = FakeGFS.calls
    out = gfs.fetch(cfg, d, leads=[1, 2], source=FakeGFS(), log=lambda m: None)     # cache lacks lead 2
    assert FakeGFS.calls > n and gfs.load(out)[2]["leads"] == [1, 2]


def test_live_features_use_the_model_sets_frozen_config(pipeline):
    from regimerain.live.run import frozen_cfg
    from regimerain.modelset import ModelSet, resolve
    root, cfgs, cfg = pipeline
    if not list((root / "models").glob("*/hashes.json")):
        assert cli.main(["fit-final"] + cfgs) == 0
    ms = ModelSet.load(resolve(cfg, "latest"))
    local = {**cfg, "features": {**cfg["features"], "llj_box": [0, 1, 0, 1]}}
    f = frozen_cfg(local, ms)
    assert f["features"] == ms.cfg["features"] and f["paths"] == local["paths"]


def test_missing_live_extra_is_named(monkeypatch):
    import builtins
    real = builtins.__import__

    def fake(name, *a, **k):
        if name == "herbie":
            raise ImportError("No module named 'herbie'")
        return real(name, *a, **k)
    monkeypatch.setattr(builtins, "__import__", fake)
    with pytest.raises(gfs.GFSError, match=r"\[live\]"):
        gfs.HerbieSource(date(2021, 8, 1), None).available()
