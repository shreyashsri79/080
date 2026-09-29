"""`regimerain preflight`: is this machine ready to demo? (BACKEND_BUILD_PLAN B7)

Checks, each PASS / WARN / FAIL with the fix:
    runs         at least one exported run; every export passes the v2 contract check
    real runs    at least one non-mock run (replay or model), so the demo isn't synthetic only
    model set    the newest model set loads and its hashes match (WARN if none: live runs off)
    web          the built web app exists (mvp/web/dist/index.html)
    gfs cache    a complete cached GFS init for the offline fallback (WARN if none)
    port         the serve port is free
Exit code 1 if anything FAILs.
"""
from __future__ import annotations

import socket
from pathlib import Path


def _port_free(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((host, port))
            return True
        except OSError:
            return False


def checks(cfg: dict, web_dist: Path, host: str = "127.0.0.1", port: int = 8000) -> list[tuple[str, str, str]]:
    from regimerain.runs import contract as C, store
    out = []
    runs = store.list_runs(cfg["paths"]["runs"])
    if not runs:
        out.append(("FAIL", "runs", f"no runs in {cfg['paths']['runs']}: `regimerain run --source replay --pick wettest` (or --source mock)"))
    else:
        bad = [r["run_id"] for r in runs if C.check_folder(store.web_dir(cfg["paths"]["runs"], r["run_id"]))]
        out.append(("FAIL", "runs", f"contract check fails: {', '.join(bad)}; re-export them") if bad
                   else ("PASS", "runs", f"{len(runs)} run(s), all valid v2 exports"))
        real = [r for r in runs if r["kind"] != "mock"]
        out.append(("PASS", "real runs", f"{len(real)} replay/model run(s); latest shown: {store.latest(cfg['paths']['runs'])['run_id']}")
                   if real else ("WARN", "real runs", "only mock runs: the site will show the yellow 'Sample run' banner"))
    try:
        from regimerain.modelset import ModelSet, resolve
        ms = ModelSet.load(resolve(cfg, "latest"))
        out.append(("PASS", "model set", f"{ms.id}: hashes match ({len(ms.hashes)} files)"))
    except ImportError as e:
        out.append(("WARN", "model set", f"cannot load ({e}); install the ml extras"))
    except Exception as e:
        out.append(("WARN", "model set", f"{e} (live GFS runs need one)"))
    out.append(("PASS", "web", str(web_dist)) if (web_dist / "index.html").is_file()
               else ("FAIL", "web", f"no {web_dist}/index.html: `cd mvp/web && npm run build`"))
    from regimerain.live.gfs import cached_inits
    have = cached_inits(cfg)
    out.append(("PASS", "gfs cache", f"newest cached init {have[-1]}") if have
               else ("WARN", "gfs cache", "no cached GFS init: run `regimerain run --source gfs` once while online"))
    out.append(("PASS", "port", f"{host}:{port} free") if _port_free(host, port)
               else ("FAIL", "port", f"{host}:{port} in use: stop the other server or pass --port"))
    return out
