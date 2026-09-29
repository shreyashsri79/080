"""RegimeRain on Modal: the API and the built web app on one URL (same as `regimerain serve`).

    https://<workspace>--regimerain.modal.run/          web app
    https://<workspace>--regimerain.modal.run/api/docs  API

Code and the web build are baked into the image; everything the pipeline produces lives in the
`regimerain-data` Volume, so new runs, reports and model sets go live without redeploying:

    /data/runs/<run_id>/web/*.json      run exports       (regimerain run ... -> deploy/sync.sh)
    /data/reports/<backtest_id>/        backtest reports
    /data/models/<model_set_id>/        model sets        (enables live GFS runs, see LIVE below)
    /data/raw/gfs/<date>/               cached GFS downloads (written by live runs)

Deploy:   cd mvp/web && npm run build && cd ../.. && modal deploy deploy/modal_app.py
Upload:   deploy/sync.sh            (pushes local runs/, reports/, models/ to the Volume)

LIVE: POST /api/runs/live is off unless the Modal secret `regimerain-live` has LIVE=1 and a model set
is in the Volume. When on, it requires the header `X-Live-Token: <LIVE_TOKEN>` from that
secret, so a public URL can't be used to start GFS downloads.
"""
from __future__ import annotations

import time
from pathlib import Path

import modal

ROOT = Path(__file__).resolve().parent.parent
DATA = "/data"
APP_NAME = "regimerain"

volume = modal.Volume.from_name("regimerain-data", create_if_missing=True)

image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install(
        "numpy>=1.24", "pandas>=2.0", "scipy>=1.10", "pyarrow>=12", "xarray>=2023.6", "pyyaml>=6",
        "pydantic>=2", "fastapi", "lightgbm>=4.0", "scikit-learn>=1.3",           # api + model sets
        "zarr>=2.16,<3", "netcdf4", "herbie-data", "cfgrib", "eccodes",           # live GFS runs
    )
    .env({"PYTHONUNBUFFERED": "1"})
    .add_local_dir(ROOT / "config", "/root/config")
    .add_local_dir(ROOT / "mvp" / "web" / "dist", "/root/web")
    .add_local_python_source("regimerain")
)

app = modal.App(APP_NAME, image=image)

# create once: modal secret create regimerain-live LIVE=0 LIVE_TOKEN=<random>; set LIVE=1 when a model set is uploaded
live_secret = [modal.Secret.from_name("regimerain-live")]


@app.function(volumes={DATA: volume}, secrets=live_secret, min_containers=0, max_containers=1,
              scaledown_window=900, timeout=1800)
@modal.concurrent(max_inputs=100)                   # one container: live-job state is shared
@modal.asgi_app(label=APP_NAME)
def web():
    import os

    from fastapi import Request
    from fastapi.responses import JSONResponse

    from regimerain.api.app import create_app
    from regimerain.config import load_config

    cfg = load_config()
    cfg["paths"] = {**cfg["paths"], **{k: f"{DATA}/{v}" for k, v in {
        "runs": "runs", "reports": "reports", "models": "models", "raw": "raw", "cache": "cache",
        "static": "static", "table": "table"}.items()}}
    for k in ("runs", "reports", "models"):
        Path(cfg["paths"][k]).mkdir(parents=True, exist_ok=True)

    live = None
    token = os.environ.get("LIVE_TOKEN", "")
    if os.environ.get("LIVE") == "1" and token:
        from regimerain.api.jobs import LiveJobs
        from regimerain.cli import live_run

        def runner(log):
            volume.reload()
            run_id = live_run(cfg, os.environ.get("LIVE_INIT", "today"), os.environ.get("LIVE_MODEL_SET", "latest"), log)
            volume.commit()                         # persist the new run + GFS cache
            return run_id
        live = LiveJobs(runner)

    api = create_app(cfg["paths"]["runs"], cfg["paths"]["reports"], "/root/web", live=live)
    last = {"t": 0.0}

    @api.middleware("http")
    async def fresh_volume_and_token(request: Request, call_next):
        # pick up runs uploaded with `modal volume put` without restarting (at most every 30 s)
        if request.url.path.startswith("/api/") and time.time() - last["t"] > 30:
            try:
                volume.reload()
            except Exception:
                pass
            last["t"] = time.time()
        if request.method == "POST" and request.url.path == "/api/runs/live" and live is not None:
            if request.headers.get("x-live-token") != token:
                return JSONResponse({"detail": "missing or wrong X-Live-Token"}, status_code=401)
        return await call_next(request)

    return api
