"""`regimerain fit-final`: refit on every season and write `models/<model_set_id>/` (MODEL_SPEC 17).

M1: all seasons, num_boost_round = 1.1 x the median fold best iteration, no early stopping;
    T = the median fold temperature. Without finished folds it falls back to early stopping on the
    last season (logged and recorded in info.json: numbers shown must still come from a backtest).
M3: experts A and B refit on all seasons.
The scores shown with this model always come from the backtest report, never from this fit.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from regimerain.backtest import git_commit
from regimerain.classify.model import (class_weights, fit_temperature, raw_logits, train_classifier)
from regimerain.config import by_mode, config_sha256, lgb_params
from regimerain.correct.experts import ExpertSet
from regimerain.data import load_table
from regimerain.features.schema import BASE_FEATURES, CATEGORICAL, assert_no_leak
from regimerain.folds import done_info, fold_dir
from regimerain.modelset import _sha, model_set_id, save_model_set
from regimerain.static.basic import static_path


def fold_summary(cfg: dict) -> tuple[list[int], list[float], list[int]]:
    """Best iterations and temperatures of finished folds whose config matches this one."""
    sha, iters, temps, seasons = config_sha256(cfg), [], [], []
    for season, info in done_info(cfg["paths"]["cache"]).items():
        p = fold_dir(cfg["paths"]["cache"], season) / "classifier.json"
        if info.get("config_sha256") != sha or not p.exists():
            continue
        d = json.loads(p.read_text())
        seasons.append(season)
        iters.append(int(d["best_iteration"]))
        temps.append(float(d["temperature"]))
    return seasons, temps, iters


def fit_final(cfg: dict, log=print) -> Path:
    import lightgbm as lgb
    seasons, leads = list(cfg["seasons"]), cfg["leads"]
    tr = load_table(cfg, seasons, leads)
    if tr.empty:
        raise RuntimeError("fit-final: empty feature table - run `features` first")
    stride = int(by_mode(cfg, cfg["classifier"]["cell_stride"]))
    fit = tr[(tr.lat_idx % stride == 0) & (tr.lon_idx % stride == 0)] if stride > 1 else tr
    fold_seasons, temps, iters = fold_summary(cfg)
    if iters:
        rounds = max(1, int(round(1.1 * float(np.median(iters)))))
        T = float(np.median(temps))
        params = lgb_params(cfg, cfg["classifier"]["params"])
        params.pop("num_boost_round", None)
        assert_no_leak(BASE_FEATURES)
        y = fit.y_synoptic.to_numpy()
        ds = lgb.Dataset(fit[BASE_FEATURES], y, weight=class_weights(y), categorical_feature=CATEGORICAL)
        booster = lgb.train(params, ds, num_boost_round=rounds)
        how = f"all {len(seasons)} seasons, {rounds} rounds (1.1 x median of folds {fold_seasons}), T = median fold T"
    else:
        val_season = seasons[-1]
        f_, v_ = fit[fit.season != val_season], fit[fit.season == val_season]
        booster = train_classifier(f_, v_, cfg)
        T = fit_temperature(raw_logits(booster, v_), v_.y_synoptic.to_numpy())
        how = f"no matching backtest folds: early stopping and T on {val_season}, trained on the rest"
        log(f"fit-final: WARNING {how}")
    log(f"fit-final: classifier {how}")
    q = cfg["qm"]
    EA = ExpertSet.from_config(q).fit(tr, None)
    EB = ExpertSet.from_config(q).fit(tr, "y_synoptic")
    commit = git_commit()
    sp = static_path(cfg)
    msid = model_set_id(cfg, commit, _sha(sp) if sp.exists() else "none")
    out = save_model_set(Path(cfg["paths"]["models"]) / msid, cfg, booster, T, {"A": EA, "B": EB}, sp,
                         {"model_set_id": msid, "kind": "final", "fitted_on": seasons, "leads": list(leads),
                          "git_commit": commit, "classifier_fit": how, "fold_seasons": fold_seasons,
                          "temperature": T})
    log(f"fit-final: model set {msid} -> {out}")
    return out
