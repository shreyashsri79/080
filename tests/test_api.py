"""API (BACKEND_BUILD_PLAN section 4): read-only, serves exactly the files on disk, safe paths."""
import json
from dataclasses import replace

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient

from regimerain.api.app import create_app
from regimerain.config import load_config
from regimerain.runs.export_web import export_run
from regimerain.runs.mock import mock_curves, mock_fields, mock_report


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    root = tmp_path_factory.mktemp("api")
    cfg = load_config()
    f = mock_fields(cfg)
    mock = export_run(f, cfg, root / "runs", report=mock_report(cfg), curves=mock_curves(cfg))
    replay = export_run(replace(f, kind="replay", source="hres", provenance={"backtest_id": "20260930_abcdef12",
                                                                           "held_out_season": 2020}), cfg, root / "runs")
    rep = root / "reports" / "20260930_abcdef12"
    rep.mkdir(parents=True)
    (rep / "verification_report.json").write_text(json.dumps(mock_report(cfg) | {"backtest_id": "20260930_abcdef12"}))
    dist = root / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>app</title>")
    (dist / "assets" / "app.js").write_text("console.log(1)")
    (root / "secret.txt").write_text("no")
    client = TestClient(create_app(root / "runs", root / "reports", dist))
    return {"client": client, "mock": mock, "replay": replay, "root": root}


def test_health_and_listing(world):
    c = world["client"]
    h = c.get("/api/health").json()
    assert h["ok"] and h["contract_version"] == 2 and h["n_runs"] == 2 and h["web"]
    runs = c.get("/api/runs").json()
    assert {r["kind"] for r in runs} == {"mock", "replay"}
    assert next(r for r in runs if r["kind"] == "replay")["held_out_season"] == 2020


def test_latest_prefers_real_runs(world):
    c = world["client"]
    assert c.get("/api/runs/latest").json()["manifest"]["kind"] == "replay"
    assert c.get("/api/runs/latest?kind=mock").json()["manifest"]["kind"] == "mock"
    assert c.get("/api/runs/latest?kind=model").status_code == 404
    assert c.get("/api/runs/latest?kind=bogus").status_code == 422


def test_files_are_the_bytes_on_disk_with_etag(world):
    c = world["client"]
    run_id = world["mock"].parent.name
    r = c.get(f"/api/runs/{run_id}/grid.json")
    assert r.status_code == 200 and r.content == (world["mock"] / "grid.json").read_bytes()
    assert r.headers["content-type"].startswith("application/json")
    again = c.get(f"/api/runs/{run_id}/grid.json", headers={"If-None-Match": r.headers["etag"]})
    assert again.status_code == 304
    gz = c.get(f"/api/runs/{run_id}/grid.json", headers={"Accept-Encoding": "gzip"})
    assert gz.headers.get("content-encoding") == "gzip"


def test_missing_and_unknown(world):
    c = world["client"]
    replay_id = world["replay"].parent.name
    assert c.get(f"/api/runs/{replay_id}/verification.json").status_code == 404     # not built for this run
    assert c.get("/api/runs/nope/manifest.json").status_code == 404
    assert c.get(f"/api/runs/{replay_id}/secrets.json").status_code == 404
    assert c.get("/api/nothing-here").status_code == 404


@pytest.mark.parametrize("path", ["/api/runs/..%2F..%2Fsecret/manifest.json", "/api/runs/%2E%2E/manifest.json",
                                  "/..%2Fsecret.txt", "/assets/..%2F..%2Fsecret.txt"])
def test_paths_cannot_escape(world, path):
    r = world["client"].get(path)
    assert b"no" != r.content and r.status_code in (200, 404)
    if r.status_code == 200:                                   # web fallback, never the file outside dist
        assert b"<title>app</title>" in r.content


def test_reports_are_filtered_not_recomputed(world):
    c = world["client"]
    assert c.get("/api/reports").json()[0]["backtest_id"] == "20260930_abcdef12"
    r = c.get("/api/reports/20260930_abcdef12/verification?variant=B&lead=1&threshold=64.5&fold=pooled").json()
    assert r["rows"] and all(x["variant"] == "B" and x["lead"] == 1 and x["threshold"] == 64.5 for x in r["rows"])
    assert c.get("/api/reports/unknown/verification").status_code == 404


def test_web_app_and_spa_fallback(world):
    c = world["client"]
    assert c.get("/assets/app.js").text == "console.log(1)"
    for route in ("/", "/forecast", "/scorecard?run=x"):
        r = c.get(route)
        assert r.status_code == 200 and "<title>app</title>" in r.text
    assert c.get("/assets/index-oldhash.js").status_code == 404        # stale asset: 404, never the HTML shell


def test_etag_follows_content_when_mtime_is_zero(world, tmp_path):
    """Modal mounts files at mtime 0: two builds' index.html of equal size must still get different ETags."""
    import os
    from regimerain.api.app import _etag
    a, b = tmp_path / "a.html", tmp_path / "b.html"
    a.write_text("<script src=/assets/x-AAAA.js>")
    b.write_text("<script src=/assets/x-BBBB.js>")
    for f in (a, b):
        os.utime(f, ns=(0, 0))
    assert _etag(a) != _etag(b)
    r = world["client"].get("/assets/app.js")
    assert "immutable" in r.headers["cache-control"] and world["client"].get("/").headers["cache-control"] == "no-cache"
