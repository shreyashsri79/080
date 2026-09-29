"""Command-line interface (TRD section 9).

Usage: python -m regimerain.cli <command> [options] [--config FILE ...] [--data-root DIR]

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

def _common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--config", action="append", default=[], metavar="FILE",
                   help="YAML config; repeat to layer overrides (default: config/default.yaml)")
    p.add_argument("--data-root", default=None, help="re-root relative paths.* entries")
    p.add_argument("--seasons", default=None, help="override config seasons, e.g. 2019-2021")


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
    p.add_argument("--imd-climatology", default=None, help="e.g. 1981-2015: only fetch IMD years for the climatology")
    p.add_argument("--only", default=None, help="comma list of parts: tracks,mjo,imd,hres (default: all)")
    p.add_argument("--force", action="store_true", help="redo parts that already exist")
    add("static", "static layers, zones, district weights")
    add("label", "synoptic regime labels")
    p = add("features", "feature tables")
    p.add_argument("--leads", default=None, help="default: config leads")
    p.add_argument("--force", action="store_true")
    p = add("backtest", "leave-one-monsoon-out backtest")
    p.add_argument("--variants", default="raw,A,B,C")
    p.add_argument("--mode", choices=["fast", "full"], default=None)
    p.add_argument("--folds", default=None, help="comma-separated test seasons (default: all)")
    p.add_argument("--force", action="store_true", help="rerun folds that already have a DONE marker")
    add("report", "pool all DONE folds -> verification report + skill gate")
    add("fit-final", "refit classifier + experts on every season -> models/<model_set_id>/")
    p = add("run", "produce a run and export it for the web (runs/<run_id>/web/)")
    p.add_argument("--source", choices=["mock", "replay", "hres", "gfs", "samanvay"], default="gfs",
                   help="samanvay: interim run from the sister project's hindcasts (no --init = every June-September one)")
    p.add_argument("--init", default=None, help="init date YYYY-MM-DD (mock default 2022-07-14; gfs: today|cached)")
    p.add_argument("--seed", type=int, default=None, help="mock only")
    p.add_argument("--pick", choices=["wettest", "depression", "active", "break"], default=None,
                   help="replay only: choose the init from the held-out seasons instead of --init")
    p.add_argument("--model-set", default="latest", help="hres/gfs: model set id (prefix), path, or latest")
    p.add_argument("--backtest-id", default=None, help="replay only: report to show (default: newest with the fold's config)")
    p.add_argument("--publish", default=None, metavar="NAME",
                   help="also copy the web export to mvp/web/public/run/NAME (static hosting, `npm run dev`)")
    p = add("publish", "copy a run's web export into the static web app")
    p.add_argument("run_id")
    p.add_argument("--as", dest="name", default=None, help="folder name under mvp/web/public/run (default: run_id)")
    p = add("contract", "web contract v2: validate an export folder or write the JSON Schema")
    p.add_argument("--check", default=None, metavar="DIR", help="folder with manifest.json, grid.json, ...")
    p.add_argument("--schema", default=None, metavar="FILE", help="write the JSON Schema here")
    p = add("selftest", "run the test suite")
    p.add_argument("--quick", action="store_true", help="only tests marked `quick`")
    p = add("import-kaggle", "copy a Kaggle/Colab training output (models, reports, fold caches) into this checkout")
    p.add_argument("src", help="unzipped notebook output folder")
    p.add_argument("--force", action="store_true", help="replace what is already here")
    p = add("preflight", "demo readiness: runs, model set, web build, GFS cache, port")
    p.add_argument("--web", default=str(REPO_ROOT / "mvp" / "web" / "dist"))
    p.add_argument("--host", default="127.0.0.1", help="the host `serve` will bind")
    p.add_argument("--port", type=int, default=8000)
    p = add("serve", "API + built web app on one port (read-only; computes nothing)")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--web", default=str(REPO_ROOT / "mvp" / "web" / "dist"),
                   help="built web app to serve at / (npm run build); missing = API only")
    p.add_argument("--dev-cors", action="store_true", help="allow cross-origin requests (a separate dev server)")
    p.add_argument("--live", action="store_true", help="enable POST /api/runs/live (GFS download + model set)")
    p.add_argument("--model-set", default="latest", help="with --live: model set id (prefix), path, or latest")
    p.add_argument("--init", default="today", help="with --live: today | cached | YYYY-MM-DD")
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


def cmd_ingest(cfg: dict, args) -> int:
    from regimerain.ingest.run import run_imd_climatology, run_ingest
    if args.imd_climatology:
        a, b = parse_range(args.imd_climatology)[0], parse_range(args.imd_climatology)[-1]
        run_imd_climatology(cfg, a, b)
        return 0
    years = parse_range(args.years) if args.years else list(cfg["seasons"])
    only = [p.strip() for p in args.only.split(",")] if args.only else None
    run_ingest(cfg, years, truth=args.truth, only=only, force=args.force)
    return 0


def cmd_static(cfg: dict, args) -> int:
    from regimerain.static.basic import build_static_basic, static_path
    from regimerain.truth import load_truth, prepare_truth
    prepare_truth(cfg, cfg["seasons"])
    st = build_static_basic(load_truth(cfg, cfg["seasons"]))
    out = static_path(cfg)
    out.parent.mkdir(parents=True, exist_ok=True)
    st.to_zarr(out, mode="w")
    print(f"static ({st.attrs['mode']}): {int(st.land.sum())} land cells -> {out}")
    return 0


def cmd_label(cfg: dict, args) -> int:
    from regimerain.label.build import build_labels
    build_labels(cfg, cfg["seasons"])
    return 0


def cmd_features(cfg: dict, args) -> int:
    from regimerain.features.build import build_features
    leads = parse_range(args.leads) if args.leads else cfg["leads"]
    build_features(cfg, cfg["seasons"], leads, force=args.force)
    return 0


def cmd_backtest(cfg: dict, args) -> int:
    from regimerain.backtest import run_backtest
    only = parse_range(args.folds) if args.folds else None
    run_backtest(cfg, [v.strip() for v in args.variants.split(",")], only=only, force=args.force)
    return 0


def cmd_report(cfg: dict, args) -> int:
    from regimerain.verify.report import build_report
    out = build_report(cfg)
    print((out / "summary.md").read_text(encoding="utf-8"))
    return 0


WEB_RUNS = REPO_ROOT / "mvp" / "web" / "public" / "run"


def _publish(web_dir: Path, name: str) -> Path:
    import shutil
    dest = WEB_RUNS / name
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(web_dir, dest)
    return dest


TRUTH_NAMES = {"imd": "IMD gridded rainfall (0.25°)", "chirps": "CHIRPS 2.0, regridded to 0.25°"}


def cmd_run(cfg: dict, args) -> int:
    from datetime import date
    if args.source == "replay":
        return _run_replay(cfg, args)
    if args.source in ("hres", "gfs"):
        return _run_model(cfg, args)
    if args.source == "samanvay":
        return _run_interim(cfg, args)
    from regimerain.runs.export_web import export_run
    from regimerain.runs.mock import DEFAULT_INIT, DEFAULT_SEED, MOCK_REGIME_DAYS, mock_curves, mock_fields, mock_report
    seed = DEFAULT_SEED if args.seed is None else args.seed
    init = date.fromisoformat(args.init) if args.init else DEFAULT_INIT
    fields = mock_fields(cfg, init=init, seed=seed)
    web = export_run(fields, cfg, cfg["paths"]["runs"], report=mock_report(cfg, seed), curves=mock_curves(cfg, seed),
                     regime_days=MOCK_REGIME_DAYS)
    print(f"run {web.parent.name} (mock, SYNTHETIC) -> {web}")
    if args.publish:
        print(f"published -> {_publish(web, args.publish)}")
    return 0


def _run_replay(cfg: dict, args) -> int:
    from datetime import date
    from regimerain.runs.export_web import export_run
    from regimerain.runs.replay import ReplayError, replay_fields
    if bool(args.init) == bool(args.pick):
        print("run --source replay needs exactly one of --init YYYY-MM-DD or --pick", file=sys.stderr)
        return 2
    try:
        fields, report, curves, days = replay_fields(cfg, date.fromisoformat(args.init) if args.init else None,
                                                     args.pick, args.backtest_id)
    except ReplayError as e:
        print(f"replay: {e}", file=sys.stderr)
        return 1
    web = export_run(fields, cfg, cfg["paths"]["runs"], report=report, curves=curves, regime_days=days,
                     truth_source=TRUTH_NAMES.get(cfg["sources"]["truth"], cfg["sources"]["truth"]))
    prov = fields.provenance
    print(f"run {web.parent.name} (replay, season {prov['held_out_season']} held out, report {prov['backtest_id']}) -> {web}")
    print(f"  layers: {', '.join(fields.layers())}" + ("" if report else "  (no matching verification report)"))
    if args.publish:
        print(f"published -> {_publish(web, args.publish)}")
    return 0


def model_export(cfg: dict, source: str, init: str | None, model_set: str, log=print):
    """Model set on one init (hres: historical table rows; gfs: live download) -> web export.
    The single path behind `run --source hres|gfs` and POST /api/runs/live."""
    from datetime import date
    from regimerain.runs.export_web import export_run
    if source == "gfs":
        from regimerain.live.run import gfs_fields, resolve_init
        d = resolve_init(cfg, init)
        log(f"init {d}")
        fields, report, curves, days, ms = gfs_fields(cfg, d, model_set, log=log)
    else:
        from regimerain.runs.model_run import model_fields
        fields, report, curves, days, ms = model_fields(cfg, date.fromisoformat(init), model_set)
    log("exporting")
    truth = TRUTH_NAMES.get(cfg["sources"]["truth"], cfg["sources"]["truth"]) if fields.truth is not None else None
    web = export_run(fields, cfg, cfg["paths"]["runs"], report=report, curves=curves, regime_days=days, truth_source=truth)
    return web, fields, report, ms


def live_run(cfg: dict, init: str | None, model_set: str, log=print) -> str:
    """The serve --live job: returns the run id."""
    return model_export(cfg, "gfs", init, model_set, log)[0].parent.name


def _run_model(cfg: dict, args) -> int:
    from regimerain.live.gfs import GFSError
    from regimerain.modelset import ModelSetError
    from regimerain.runs.model_run import ModelRunError
    if args.source == "hres" and not args.init:
        print("run --source hres needs --init YYYY-MM-DD", file=sys.stderr)
        return 2
    try:
        web, fields, report, ms = model_export(cfg, args.source, args.init, args.model_set)
    except (ModelSetError, ModelRunError, GFSError, ValueError) as e:
        print(f"run: {e}", file=sys.stderr)
        return 1
    print(f"run {web.parent.name} (model set {ms.id}) -> {web}")
    print(f"  layers: {', '.join(fields.layers())}" + ("" if report else "  (no verification report with this config)"))
    if args.publish:
        print(f"published -> {_publish(web, args.publish)}")
    return 0


def cmd_import_kaggle(cfg: dict, args) -> int:
    from regimerain.handover import import_output
    from regimerain.modelset import ModelSetError
    try:
        import_output(cfg, Path(args.src), args.force)
    except (FileNotFoundError, ModelSetError) as e:
        print(f"import-kaggle: {e}", file=sys.stderr)
        return 1
    print("next: `regimerain run --source replay --pick wettest`, `regimerain run --source gfs`, `regimerain preflight`")
    return 0


def cmd_preflight(cfg: dict, args) -> int:
    from regimerain.preflight import checks
    res = checks(cfg, Path(args.web), host=args.host, port=args.port)
    for status, name, msg in res:
        print(f"{status:5} {name:10} {msg}")
    return 1 if any(s == "FAIL" for s, _, _ in res) else 0


def cmd_fit_final(cfg: dict, args) -> int:
    from regimerain.final import fit_final
    fit_final(cfg)
    return 0


def _run_interim(cfg: dict, args) -> int:
    from datetime import date
    from regimerain.live.wind_source import WindSource, WindUnavailable
    from regimerain.runs.export_web import export_run
    from regimerain.runs.interim import InterimError, interim_fields, jjas_hindcasts
    client = WindSource()
    try:
        inits = [date.fromisoformat(args.init)] if args.init else [r["init_date"] for r in jjas_hindcasts(client)]
    except WindUnavailable as e:
        print(f"run: {e}", file=sys.stderr)
        return 1
    bad = 0
    for d in inits:
        try:
            f = interim_fields(cfg, d, client)
        except (InterimError, WindUnavailable) as e:
            print(f"run {d}: {e}", file=sys.stderr)
            bad += 1
            continue
        web = export_run(f, cfg, cfg["paths"]["runs"])
        print(f"run {web.parent.name} (interim: real Samanvay data, stand-in correction) -> {web}")
        if args.publish:
            print(f"published -> {_publish(web, args.publish)}")
    return 1 if bad else 0


def cmd_publish(cfg: dict, args) -> int:
    web = Path(cfg["paths"]["runs"]) / args.run_id / "web"
    if not (web / "manifest.json").exists():
        print(f"no web export at {web}", file=sys.stderr)
        return 1
    print(f"published -> {_publish(web, args.name or args.run_id)}")
    return 0


def cmd_contract(cfg: dict, args) -> int:
    from regimerain.runs.contract import check_folder, write_schema
    if args.schema:
        print(f"schema -> {write_schema(args.schema)}")
    if args.check:
        problems = check_folder(args.check)
        for p in problems:
            print("FAIL", p)
        print("OK: web contract v2" if not problems else f"{len(problems)} problem(s)")
        return 1 if problems else 0
    return 0


def cmd_serve(cfg: dict, args) -> int:
    import uvicorn
    from regimerain.api.app import create_app
    from regimerain.runs import store
    web = Path(args.web)
    if not (web / "index.html").is_file():
        print(f"no built web app at {web} (run `npm run build` in mvp/web); serving the API only", file=sys.stderr)
    n = len(store.list_runs(cfg["paths"]["runs"]))
    print(f"{n} run(s) in {cfg['paths']['runs']}; reports in {cfg['paths']['reports']}")
    print(f"open http://{args.host}:{args.port}/   (API docs: /api/docs)")
    live = None
    if args.live:
        from regimerain.api.jobs import LiveJobs
        live = LiveJobs(lambda log: live_run(cfg, args.init, args.model_set, log))
        print(f"live runs on: POST /api/runs/live (init {args.init}, model set {args.model_set})")
    uvicorn.run(create_app(cfg["paths"]["runs"], cfg["paths"]["reports"], web, dev_cors=args.dev_cors, live=live),
                host=args.host, port=args.port, log_level="warning")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    cfg = load_config(args.config, args.data_root)
    if getattr(args, "mode", None):
        cfg["mode"] = args.mode
    if getattr(args, "seasons", None):
        cfg["seasons"] = parse_range(args.seasons)
    handlers = {"config": cmd_config, "selftest": cmd_selftest, "ingest": cmd_ingest, "static": cmd_static,
                "label": cmd_label, "features": cmd_features, "backtest": cmd_backtest, "report": cmd_report,
                "run": cmd_run, "publish": cmd_publish, "contract": cmd_contract, "serve": cmd_serve,
                "fit-final": cmd_fit_final, "preflight": cmd_preflight,
                "import-kaggle": cmd_import_kaggle}
    return handlers[args.command](cfg, args)


if __name__ == "__main__":
    sys.exit(main())
