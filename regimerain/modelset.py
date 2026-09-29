"""Model sets: the saved, hashed artefacts one forecast needs (TRD 3.4, MODEL_SPEC 17).

    models/<model_set_id>/
      config.yaml                   frozen config
      classifier/booster.txt        LightGBM regime classifier (lead is a feature)
      classifier/temperature.json   {"T": float, "best_iteration": int}
      qm/experts.parquet            ExpertSet.to_frame for variants A and B (column `variant`)
      static.zarr                   the static layer the model was trained with (land, geo, zone, ...)
      feature_list.json             exact ordered classifier features
      info.json                     seasons, git commit, config hash, what the set was fitted on
      hashes.json                   sha256 of every file above (written last: its presence = complete)

The same layout is written per backtest fold (`cache/fold=Y/model/`) so the parity test can check
a loaded set against the fold's predictions.parquet (BACKEND_BUILD_PLAN 5).

`ModelSet.predict` is the only inference path: classifier -> temperature -> grid smoothing -> mixture QM,
calling the same functions the backtest calls, so a value is never computed by two code paths (TRD 6).
"""
from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import yaml

from regimerain.config import config_sha256
from regimerain.features.schema import BASE_FEATURES

HASHES = "hashes.json"


class ModelSetError(RuntimeError):
    pass


def _sha(p: Path) -> str:
    h = hashlib.sha256()
    if p.is_dir():                                           # zarr store: hash every chunk file in order
        for f in sorted(x for x in p.rglob("*") if x.is_file()):
            h.update(f.relative_to(p).as_posix().encode())
            h.update(f.read_bytes())
    else:
        h.update(p.read_bytes())
    return h.hexdigest()


def _hash_targets(d: Path) -> list[Path]:
    return sorted([p for p in d.rglob("*") if p.is_file() and ".zarr" not in p.as_posix() and p.name != HASHES]
                  + [p for p in d.glob("*.zarr")])


def model_set_id(cfg: dict, commit: str, static_sha: str) -> str:
    """MODEL_SPEC 17: sha256 of (config hash + git commit + data snapshot hash), first 12 characters."""
    return hashlib.sha256(f"{config_sha256(cfg)}|{commit}|{static_sha}".encode()).hexdigest()[:12]


def save_model_set(out: Path, cfg: dict, booster, T: float, experts: dict, static_src: Path | None,
                   info: dict, features=BASE_FEATURES) -> Path:
    """Write a complete model set to `out` (replaced if present). `experts`: {"A": ExpertSet, "B": ExpertSet}."""
    out = Path(out)
    tmp = out.with_name(out.name + ".partial")
    shutil.rmtree(tmp, ignore_errors=True)
    (tmp / "classifier").mkdir(parents=True)
    (tmp / "qm").mkdir()
    (tmp / "config.yaml").write_text(yaml.safe_dump(cfg, sort_keys=False))
    booster.save_model(str(tmp / "classifier" / "booster.txt"))
    (tmp / "classifier" / "temperature.json").write_text(
        json.dumps({"T": float(T), "best_iteration": int(booster.best_iteration or booster.current_iteration())}))
    frames = [e.to_frame(v) for v, e in experts.items() if e is not None]
    pd.concat(frames, ignore_index=True).to_parquet(tmp / "qm" / "experts.parquet", index=False)
    (tmp / "feature_list.json").write_text(json.dumps(list(features)))
    if static_src is not None and Path(static_src).exists():
        shutil.copytree(static_src, tmp / "static.zarr")
    (tmp / "info.json").write_text(json.dumps({**info, "config_sha256": config_sha256(cfg)}, indent=2, default=str))
    hashes = {p.relative_to(tmp).as_posix(): _sha(p) for p in _hash_targets(tmp)}
    (tmp / HASHES).write_text(json.dumps(hashes, indent=2, sort_keys=True))
    shutil.rmtree(out, ignore_errors=True)
    tmp.rename(out)
    return out


def resolve(cfg: dict, ref: str) -> Path:
    """A model set by id (under paths.models), by path, or `latest` (newest complete set)."""
    p = Path(ref)
    if (p / HASHES).is_file():
        return p
    root = Path(cfg["paths"]["models"])
    if ref == "latest":
        sets = sorted((d for d in root.glob("*") if (d / HASHES).is_file() and not d.name.endswith(".partial")), key=lambda d: (d / HASHES).stat().st_mtime)
        if not sets:
            raise ModelSetError(f"no model sets in {root}; run `fit-final` or copy the Kaggle `ps26080-models` output here")
        return sets[-1]
    hits = [d for d in root.glob(f"{ref}*") if (d / HASHES).is_file() and not d.name.endswith(".partial")] if ref and "/" not in ref and ".." not in ref else []
    if len(hits) == 1:
        return hits[0]
    raise ModelSetError(f"model set {ref!r} not found in {root}" if not hits else f"model set prefix {ref!r} is ambiguous")


@dataclass
class ModelSet:
    path: Path
    id: str
    cfg: dict
    booster: object
    T: float
    features: list[str]
    experts: dict            # variant -> ExpertSet
    hashes: dict
    info: dict

    @classmethod
    def load(cls, path: Path, verify: bool = True) -> "ModelSet":
        import lightgbm as lgb
        from regimerain.correct.experts import ExpertSet
        path = Path(path)
        if not (path / HASHES).is_file():
            raise ModelSetError(f"{path} is not a complete model set (no {HASHES})")
        hashes = json.loads((path / HASHES).read_text())
        if verify:
            bad = [k for k, h in hashes.items() if not (path / k).exists() or _sha(path / k) != h]
            if bad:
                raise ModelSetError(f"model set {path.name}: hash mismatch or missing file: {', '.join(bad)}")
        cfg = yaml.safe_load((path / "config.yaml").read_text())
        feats = json.loads((path / "feature_list.json").read_text())
        booster = lgb.Booster(model_file=str(path / "classifier" / "booster.txt"))
        if booster.feature_name() != feats:
            raise ModelSetError("booster features differ from feature_list.json")
        T = float(json.loads((path / "classifier" / "temperature.json").read_text())["T"])
        ex = pd.read_parquet(path / "qm" / "experts.parquet")
        n0 = float(cfg["qm"]["n0_days"])
        experts = {v: ExpertSet.from_frame(g, n0) for v, g in ex.groupby("variant")}
        info = json.loads((path / "info.json").read_text()) if (path / "info.json").exists() else {}
        return cls(path, info.get("model_set_id", path.name), cfg, booster, T, feats, experts, hashes, info)

    @property
    def static_path(self) -> Path | None:
        p = self.path / "static.zarr"
        return p if p.exists() else None

    def expert_frame(self) -> pd.DataFrame:
        return pd.read_parquet(self.path / "qm" / "experts.parquet")

    def predict(self, df: pd.DataFrame, grid_shape: tuple[int, int]) -> pd.DataFrame:
        """Rows of the feature table (any inits/leads) -> raw, A, B and p_* per row, as the backtest writes them."""
        from regimerain.classify.model import predict_proba, smooth_on_grid
        from regimerain.correct.mixture import correct_mixture
        from regimerain.features.schema import REGIME_PROB_FEATURES
        missing = [c for c in self.features if c not in df]
        if missing:
            raise ModelSetError(f"feature rows lack {missing}")
        df = df.reset_index(drop=True)
        P = predict_proba(self.booster, df, self.T, self.features)
        P = smooth_on_grid(df, P, grid_shape, int(self.cfg["classifier"].get("smooth_size", 3)))
        out = pd.DataFrame({"raw": df["f_rain"].to_numpy("float32")})
        out[REGIME_PROB_FEATURES] = P.astype("float32")
        q = self.cfg["qm"]
        if "A" in self.experts:
            out["A"] = self.experts["A"].apply_global(df)
        if "B" in self.experts:
            out["B"] = correct_mixture(df, P, self.experts["B"], q["p_min"], q["p_hard"])
        return out
