"""Runs on disk: `runs/<run_id>/web/*.json` as written by `export_web` (BACKEND_BUILD_PLAN section 2.1).

Read-only helpers shared by the API and the CLI. Run folders are resolved only through `web_dir`,
which validates the id, so a request can never reach outside the runs directory.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
# `latest` prefers real model runs, then held-out replays, then interim runs (real data, stand-in
# correction), then synthetic mocks.
KIND_RANK = {"model": 0, "replay": 1, "interim": 2, "mock": 3}


def web_dir(runs_dir: str | Path, run_id: str) -> Path | None:
    """The export folder of a run, or None if the id is malformed or the run doesn't exist."""
    if not RUN_ID.match(run_id) or ".." in run_id:
        return None
    d = Path(runs_dir) / run_id / "web"
    return d if (d / "manifest.json").is_file() else None


def summary(manifest: dict) -> dict:
    return {"run_id": manifest["run_id"], "kind": manifest.get("kind"), "synthetic": manifest.get("synthetic"),
            "forecast_source": manifest.get("forecast_source"), "forecast_issue_date": manifest.get("forecast_issue_date"),
            "created_utc": manifest.get("created_utc"), "layers": manifest.get("layers", []),
            "held_out_season": (manifest.get("provenance") or {}).get("held_out_season")}


def list_runs(runs_dir: str | Path) -> list[dict]:
    """Every exported run, newest first. Folders without a readable v2 manifest are skipped."""
    out = []
    for m in Path(runs_dir).glob("*/web/manifest.json"):
        try:
            man = json.loads(m.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if man.get("contract_version") == 2 and man.get("run_id") == m.parent.parent.name:
            out.append(summary(man))
    return sorted(out, key=lambda r: r.get("created_utc") or "", reverse=True)


def latest(runs_dir: str | Path, kind: str | None = None) -> dict | None:
    runs = [r for r in list_runs(runs_dir) if kind is None or r["kind"] == kind]
    if not runs:
        return None
    # stable sort: newest first within each kind, kinds in preference order
    return sorted(runs, key=lambda r: KIND_RANK.get(r["kind"], 9))[0]


def list_reports(reports_dir: str | Path) -> list[dict]:
    out = []
    for f in Path(reports_dir).glob("*/verification_report.json"):
        try:
            rep = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        out.append({"backtest_id": rep.get("backtest_id", f.parent.name), "dir": f.parent.name,
                    "seasons": rep.get("seasons", []), "leads": rep.get("leads", []), "variants": rep.get("variants", []),
                    "config_sha256": rep.get("config_sha256"), "mtime": f.stat().st_mtime})
    return sorted(out, key=lambda r: r["mtime"], reverse=True)


def report_path(reports_dir: str | Path, backtest_id: str) -> Path | None:
    if not RUN_ID.match(backtest_id) or ".." in backtest_id:
        return None
    for r in list_reports(reports_dir):
        if backtest_id in (r["backtest_id"], r["dir"]):
            return Path(reports_dir) / r["dir"] / "verification_report.json"
    return None
