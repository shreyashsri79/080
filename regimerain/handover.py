"""`regimerain import-kaggle DIR`: bring a Kaggle (or Colab) training output into this checkout.

DIR is the downloaded notebook output (the `ps26080-models` dataset, unzipped), or any folder that
contains some of:
    models/<model_set_id>/     -> paths.models      (hash-verified before copying)
    reports/<backtest_id>/     -> paths.reports
    cache/fold=<Y>/            -> paths.cache       (only the small files a replay needs, not the tables)
Nothing is overwritten unless --force. Returns what was imported.
"""
from __future__ import annotations

import shutil
from pathlib import Path

FOLD_FILES = ("predictions.parquet", "classifier.json", "qm_counts_A.csv", "qm_counts_B.csv",
              "experts_A.parquet", "experts_B.parquet")      # DONE is copied last, after these and model/


def _find(root: Path, pattern: str) -> list[Path]:
    return sorted({p.parent for p in root.glob(f"**/{pattern}")})


def import_output(cfg: dict, src: Path, force: bool = False, log=print) -> dict:
    from regimerain.modelset import ModelSet
    src = Path(src)
    if not src.is_dir():
        raise FileNotFoundError(f"{src} is not a folder (unzip the Kaggle output first)")
    done = {"models": [], "reports": [], "folds": [], "skipped": []}

    def copy(a: Path, b: Path, kind: str, name: str, files=None):
        if b.exists() and not force:
            done["skipped"].append(f"{kind} {name} (exists; --force to replace)")
            return
        if b.exists():
            shutil.rmtree(b)
        if files is None:
            shutil.copytree(a, b)
        else:
            b.mkdir(parents=True)
            for f in files:
                if (a / f).exists():
                    shutil.copy2(a / f, b / f)
            if (a / "model").is_dir():
                shutil.copytree(a / "model", b / "model")
            shutil.copy2(a / "DONE", b / "DONE")                     # last: its presence = fold complete
        done[kind].append(name)

    for d in _find(src, "hashes.json"):
        if d.name == "model" and d.parent.name.startswith("fold="):
            continue                                                  # fold models travel with their fold
        ms = ModelSet.load(d)                                         # raises on a hash mismatch
        copy(d, Path(cfg["paths"]["models"]) / d.name, "models", ms.id)
    for d in _find(src, "verification_report.json"):
        copy(d, Path(cfg["paths"]["reports"]) / d.name, "reports", d.name)
    for d in _find(src, "DONE"):
        if d.name.startswith("fold="):
            copy(d, Path(cfg["paths"]["cache"]) / d.name, "folds", d.name, FOLD_FILES)
    for k in ("models", "reports", "folds"):
        if done[k]:
            log(f"imported {k}: {', '.join(done[k])}")
    for s in done["skipped"]:
        log(f"skipped {s}")
    if not any(done[k] for k in ("models", "reports", "folds", "skipped")):
        raise FileNotFoundError(f"nothing to import in {src}: no models/*/hashes.json, reports/*/verification_report.json or cache/fold=*/DONE")
    return done
