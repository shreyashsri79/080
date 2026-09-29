"""FastAPI app: the run exports and backtest reports, plus the built web app, on one port.

Read-only (TRD 4.14): it lists, reads and serves files the exporter and `report` wrote. It never
computes a forecast or a metric (NFR-2); the one write endpoint only starts the same code path as
`regimerain run --source gfs` in a background thread (api/jobs.py). `regimerain serve` runs it with uvicorn.

    GET /api/health
    GET /api/runs                               newest first
    GET /api/runs/latest[?kind=model|replay|interim|mock]
    GET /api/runs/{run_id}/{file}.json          manifest | grid | places | qm_curves | verification
    GET /api/reports
    GET /api/reports/{backtest_id}/verification[?variant=&lead=&threshold=&synoptic=&fold=]
    POST /api/runs/live                         start a live GFS run (only with `serve --live`): 202, or 409 if one is running
    GET /api/runs/live                          status of the current/last live run {status, stage, run_id, log_tail}
    GET /*                                      the built web app (single-page fallback to index.html)
"""
from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response

from regimerain.runs import store
from regimerain.runs.contract import CONTRACT_VERSION, FILES

VERSION = "0.1.0"


def _etag(path: Path) -> str:
    st = path.stat()
    if st.st_mtime_ns <= 0:                      # no usable mtime (Modal mounts files at mtime 0): hash the bytes
        return f'"{_content_tag(str(path), st.st_size, st.st_ino)}"'
    return f'"{st.st_mtime_ns:x}-{st.st_size:x}"'


@lru_cache(maxsize=4096)
def _content_tag(path: str, size: int, inode: int) -> str:
    return hashlib.sha1(Path(path).read_bytes()).hexdigest()[:20]


def _file(request: Request, path: Path, media_type: str, immutable: bool = False) -> Response:
    """File with an ETag; 304 when the client already has it. `no-cache` = always revalidate (a run
    can be re-exported under the same id, and index.html changes with every build). `immutable` is for
    content-hashed build assets, whose name changes whenever their bytes do."""
    tag = _etag(path)
    headers = {"ETag": tag, "Cache-Control": "public, max-age=31536000, immutable" if immutable else "no-cache"}
    if request.headers.get("if-none-match") == tag:
        return Response(status_code=304, headers=headers)
    return FileResponse(path, media_type=media_type, headers=headers)


def create_app(runs_dir: str | Path, reports_dir: str | Path | None = None, web_dist: str | Path | None = None,
               dev_cors: bool = False, live=None) -> FastAPI:
    """`live`: an api.jobs.LiveJobs, or None to disable POST /api/runs/live (503)."""
    runs_dir = Path(runs_dir)
    reports_dir = Path(reports_dir) if reports_dir else None
    dist = Path(web_dist).resolve() if web_dist and Path(web_dist, "index.html").is_file() else None

    app = FastAPI(title="RegimeRain API", version=VERSION, docs_url="/api/docs", openapi_url="/api/openapi.json")
    app.add_middleware(GZipMiddleware, minimum_size=1024)
    if dev_cors:
        from fastapi.middleware.cors import CORSMiddleware
        app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET", "POST"], allow_headers=["*"])

    @app.get("/api/health")
    def health():
        return {"ok": True, "version": VERSION, "contract_version": CONTRACT_VERSION,
                "runs_dir": str(runs_dir), "n_runs": len(store.list_runs(runs_dir)), "web": dist is not None, "live": live is not None}

    @app.get("/api/runs")
    def runs():
        return store.list_runs(runs_dir)

    @app.get("/api/runs/latest")
    def latest(kind: Optional[str] = Query(None, pattern="^(model|replay|interim|mock)$")):
        run = store.latest(runs_dir, kind)
        if run is None:
            raise HTTPException(404, "no runs" + (f" of kind {kind}" if kind else ""))
        d = store.web_dir(runs_dir, run["run_id"])
        return {"run_id": run["run_id"], "manifest": json.loads((d / "manifest.json").read_text(encoding="utf-8"))}

    @app.post("/api/runs/live", status_code=202)
    def live_start():
        if live is None:
            raise HTTPException(503, "live runs are off: start the server with `regimerain serve --live`")
        st = live.start()
        if st is None:
            raise HTTPException(409, "a live run is already in progress")
        return st

    @app.get("/api/runs/live")
    def live_status():
        if live is None:
            raise HTTPException(503, "live runs are off: start the server with `regimerain serve --live`")
        return live.status()

    @app.get("/api/runs/{run_id}/{name}.json")
    def run_file(run_id: str, name: str, request: Request):
        d = store.web_dir(runs_dir, run_id)
        if d is None:
            raise HTTPException(404, f"unknown run {run_id!r}")
        if name not in FILES:
            raise HTTPException(404, f"unknown file {name!r}; one of {', '.join(FILES)}")
        f = d / f"{name}.json"
        if not f.is_file():
            raise HTTPException(404, f"{name}.json is not in run {run_id} (not built for this run)")
        return _file(request, f, "application/json")

    @app.get("/api/reports")
    def reports():
        return store.list_reports(reports_dir) if reports_dir else []

    @app.get("/api/reports/{backtest_id}/verification")
    def verification(backtest_id: str, variant: Optional[str] = None, lead: Optional[int] = None,
                     threshold: Optional[float] = None, synoptic: Optional[str] = None, fold: Optional[str] = None):
        p = store.report_path(reports_dir, backtest_id) if reports_dir else None
        if p is None:
            raise HTTPException(404, f"unknown backtest {backtest_id!r}")
        rep = json.loads(p.read_text(encoding="utf-8"))

        def keep(r):
            return ((variant is None or r.get("variant") == variant) and (lead is None or r.get("lead") == lead)
                    and (threshold is None or (r.get("threshold") is not None and abs(float(r["threshold"]) - threshold) < 1e-6))
                    and (synoptic is None or r.get("synoptic") == synoptic) and (fold is None or str(r.get("fold")) == fold))
        return JSONResponse({**{k: v for k, v in rep.items() if k not in ("rows", "deltas")},
                             "rows": [r for r in rep.get("rows", []) if keep(r)],
                             "deltas": [d for d in rep.get("deltas", []) if keep({**d, "fold": fold})]})

    @app.get("/api/{rest:path}", include_in_schema=False)
    def api_404(rest: str):
        raise HTTPException(404, f"no endpoint /api/{rest}")

    if dist is not None:
        @app.get("/{path:path}", include_in_schema=False)
        def web(path: str, request: Request):
            f = (dist / path).resolve()
            if path and f.is_file() and f.is_relative_to(dist):
                return _file(request, f, _media(f), immutable=path.startswith("assets/"))
            if "." in path.rsplit("/", 1)[-1]:
                # a missing file (e.g. an old build's hashed asset during a redeploy) is a 404, not the
                # app shell: HTML served as a module script breaks the page instead of letting it reload
                raise HTTPException(404, f"no file /{path}")
            return _file(request, dist / "index.html", "text/html")   # client-side routes: /forecast, /scorecard ...

    return app


def _media(f: Path) -> str:
    import mimetypes
    return mimetypes.guess_type(f.name)[0] or "application/octet-stream"
