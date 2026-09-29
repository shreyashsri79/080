"""Command-line interface (TRD section 9).

Usage: python -m regimerain.cli <command> [options] [--config FILE ...] [--data-root DIR]

Commands not yet implemented exit with code 2 and point to the MODEL_SPEC section to build next.
Heavy dependencies are imported inside commands so `--help` works on a bare install.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from regimerain.config import config_sha256, load_config

REPO_ROOT = Path(__file__).resolve().parent.parent

PLANNED = {
    "ingest": "MODEL_SPEC section 4 (HRES, IMD, CHIRPS, tracks, MJO)",
    "static": "MODEL_SPEC section 5 (DEM, coast, geo class, zones, district weights)",
    "label": "MODEL_SPEC section 6 (active/break, depression, synoptic labels)",
    "features": "MODEL_SPEC section 7 (feature tables)",
    "backtest": "MODEL_SPEC sections 9-13 (LOMO backtest)",
    "fit-final": "MODEL_SPEC section 17 (final fit)",
    "run": "MODEL_SPEC section 18 (live GFS run)",
    "serve": "TRD section 4.14 (FastAPI + web)",
}


class NotBuiltYet(SystemExit):
    def __init__(self, command: str):
        super().__init__(2)
        print(f"`{command}` is not implemented yet -> build {PLANNED[command]}.", file=sys.stderr)


def _common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--config", action="append", default=[], metavar="FILE",
                   help="YAML config; repeat to layer overrides (default: config/default.yaml)")
    p.add_argument("--data-root", default=None, help="re-root relative paths.* entries")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="regimerain", description="SIH26080 regime-aware rainfall post-processing")
    sub = ap.add_subparsers(dest="command", required=True)

    def add(name, help_):
        p = sub.add_parser(name, help=help_)
        _common(p)
        return p

    add("config", "print the merged config and its sha256")
    p = add("ingest", "download/prepare forecasts, truth, tracks, MJO")
    p.add_argument("--years", default=None)
    p.add_argument("--truth", choices=["imd", "chirps"], default=None)
    p.add_argument("--imd-climatology", default=None)
    add("static", "static layers, zones, district weights")
    add("label", "synoptic regime labels")
    p = add("features", "feature tables")
    p.add_argument("--leads", default="1-5")
    p = add("backtest", "leave-one-monsoon-out backtest")
    p.add_argument("--variants", default="raw,A,B,C")
    p.add_argument("--mode", choices=["fast", "full"], default=None)
    p.add_argument("--folds", default=None, help="comma-separated test seasons (default: all)")
    p.add_argument("--force", action="store_true", help="rerun folds that already have a DONE marker")
    add("report", "pool all DONE folds -> verification report + skill gate")
    add("fit-final", "refit all models on every season")
    p = add("run", "live run")
    p.add_argument("--source", choices=["gfs", "hres"], default="gfs")
    p.add_argument("--init", default="today")
    p = add("selftest", "run the test suite")
    p.add_argument("--quick", action="store_true", help="only tests marked `quick`")
    add("serve", "start the API + web app")
    return ap


def parse_range(text: str) -> list[int]:
    """'2016-2018' -> [2016, 2017, 2018]; '1,3,5' -> [1, 3, 5]."""
    out: list[int] = []
    for part in str(text).split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-")
            out.extend(range(int(a), int(b) + 1))
        elif part:
            out.append(int(part))
    return out


def cmd_config(cfg: dict, args) -> int:
    print(json.dumps(cfg, indent=2, default=str))
    print("config_sha256:", config_sha256(cfg))
    return 0


def cmd_selftest(cfg: dict, args) -> int:
    cmd = [sys.executable, "-m", "pytest", str(REPO_ROOT / "tests"), "-q"]
    if args.quick:
        cmd += ["-m", "quick"]
    return subprocess.call(cmd, cwd=REPO_ROOT)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    cfg = load_config(args.config, args.data_root)
    if getattr(args, "mode", None):
        cfg["mode"] = args.mode
    handlers = {"config": cmd_config, "selftest": cmd_selftest}
    if args.command == "report":
        from regimerain.folds import check_poolable
        check_poolable(cfg["paths"]["cache"], cfg["seasons"])
        print("All folds poolable; report writer not implemented yet -> build MODEL_SPEC section 13.",
              file=sys.stderr)
        return 2
    if args.command in handlers:
        return handlers[args.command](cfg, args)
    raise NotBuiltYet(args.command)


if __name__ == "__main__":
    sys.exit(main())
