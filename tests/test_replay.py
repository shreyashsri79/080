"""Replay (BACKEND_BUILD_PLAN phase B3) against a real backtest: the pilot pipeline runs end to end on the
synthetic world of test_pipeline_e2e, then a replay run must show exactly what that backtest wrote."""
import json

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("lightgbm")
pytest.importorskip("zarr")

from test_pipeline_e2e import LAT, LON, SEASONS

from regimerain import cli
from regimerain.runs import contract as C
from regimerain.runs.replay import pick_init, replay_fields


def test_backtest_saves_experts(pipeline):
    root, _, _ = pipeline
    for y in SEASONS:
        e = pd.read_parquet(root / "cache" / f"fold={y}" / "experts_B.parquet")
        assert {"f_q", "o_q", "regime", "geo", "zone", "lead", "n_days"} <= set(e.columns)


def test_replay_equals_the_backtest(pipeline):
    root, cfgs, cfg = pipeline
    init = pd.Timestamp("2020-07-15")
    f, report, curves, days = replay_fields(cfg, init.date())
    preds = pd.read_parquet(root / "cache" / "fold=2020" / "predictions.parquet")
    preds = preds[pd.to_datetime(preds.init).dt.normalize() == init]
    i, j = preds.lat_idx.to_numpy(int), preds.lon_idx.to_numpy(int)
    for col, arr in (("raw", f.raw), ("B", f.corrected), ("A", f.corrected_global), ("o_rain", f.truth)):
        np.testing.assert_allclose(arr[0, i, j], preds[col].to_numpy("float32"), rtol=0, atol=1e-5, err_msg=col)
    assert np.allclose(f.p_synoptic[0, i, j], preds[["p_active", "p_break", "p_depression", "p_normal"]].to_numpy(), atol=1e-5)
    assert f.kind == "replay" and not f.synthetic and f.provenance["held_out_season"] == 2020
    assert f.p_heavy is None                                             # exceedance not built: absent, not faked
    assert f.u850 is not None and f.mslp is not None and np.nanmedian(f.mslp) < 2000   # Pa -> hPa
    assert report is not None and report["config_sha256"] == f.provenance["config_sha256"]
    assert curves and {c["variant"] for c in curves} == {"A", "B"} and days


def test_replay_cli_exports_a_valid_real_run(pipeline, capsys):
    root, cfgs, _ = pipeline
    assert cli.main(["run", "--source", "replay", "--pick", "wettest"] + cfgs) == 0
    web = next((root / "runs").glob("*_replay-*/web"))
    assert C.check_folder(web) == []
    m = json.loads((web / "manifest.json").read_text())
    assert m["kind"] == "replay" and m["synthetic"] is False and m["forecast_source"].startswith("ECMWF")
    assert "truth" in m["layers"] and "p_heavy" not in m["layers"] and m["truth_source"].startswith("IMD")
    assert m["provenance"]["held_out_season"] in SEASONS and "basic static mode" in m["provenance"]["note"]
    g = json.loads((web / "grid.json").read_text())
    assert (g["nlat"], g["nlon"]) == (len(LAT), len(LON))
    v = json.loads((web / "verification.json").read_text())
    assert v["synthetic"] is False and v["entries"]
    q = json.loads((web / "qm_curves.json").read_text())
    assert any(c["regime"] == "global" for c in q["curves"])


def test_pick_follows_observed_labels(pipeline):
    _, _, cfg = pipeline
    d = pick_init(cfg, "active")
    preds = pd.read_parquet(f"{cfg['paths']['cache']}/fold={d.year}/predictions.parquet", columns=["init", "y_synoptic"])
    day = preds[pd.to_datetime(preds.init).dt.normalize() == pd.Timestamp(d)]
    assert (day.y_synoptic == 0).mean() > 0.5


def test_replay_errors_are_clear(pipeline):
    _, cfgs, _ = pipeline
    assert cli.main(["run", "--source", "replay", "--init", "2015-07-01"] + cfgs) == 1      # season never backtested
    assert cli.main(["run", "--source", "replay"] + cfgs) == 2                              # needs --init or --pick
