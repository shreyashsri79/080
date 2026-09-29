"""Model sets (BACKEND_BUILD_PLAN phase B4): fit-final, the saved fold model's parity with the backtest,
and `run --source hres` on the synthetic pipeline of test_replay."""
import json
from datetime import date

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("lightgbm")
pytest.importorskip("zarr")

from regimerain import cli
from regimerain.modelset import ModelSet, ModelSetError, resolve
from regimerain.runs import contract as C
from regimerain.runs.model_run import model_fields


def test_model_parity(pipeline):
    """A fold model loaded from disk reproduces the fold's predictions.parquet (p within 1e-6, B within 0.01 mm)."""
    root, _, cfg = pipeline
    init = pd.Timestamp("2020-07-15")
    f, *_ = model_fields(cfg, init.date(), str(root / "cache" / "fold=2020" / "model"))
    preds = pd.read_parquet(root / "cache" / "fold=2020" / "predictions.parquet")
    preds = preds[pd.to_datetime(preds.init).dt.normalize() == init]
    i, j = preds.lat_idx.to_numpy(int), preds.lon_idx.to_numpy(int)
    P = preds[["p_active", "p_break", "p_depression", "p_normal"]].to_numpy()
    np.testing.assert_allclose(f.p_synoptic[0, i, j], P, atol=1e-6)
    np.testing.assert_allclose(f.corrected[0, i, j], preds["B"].to_numpy(), atol=0.01)
    np.testing.assert_allclose(f.corrected_global[0, i, j], preds["A"].to_numpy(), atol=0.01)
    assert f.truth is not None and f.provenance["held_out_season"] == 2020      # 2020 held out of this fold


def test_fit_final_and_hres_run(pipeline):
    root, cfgs, cfg = pipeline
    assert cli.main(["fit-final"] + cfgs) == 0
    d = resolve(cfg, "latest")
    info = json.loads((d / "info.json").read_text())
    assert info["kind"] == "final" and info["fitted_on"] == [2019, 2020, 2021] and "median of folds" in info["classifier_fit"]
    assert {"config.yaml", "classifier/booster.txt", "qm/experts.parquet", "static.zarr", "feature_list.json"} <= set(
        json.loads((d / "hashes.json").read_text()))
    assert cli.main(["run", "--source", "hres", "--init", "2021-08-01", "--model-set", d.name[:6]] + cfgs) == 0
    web = root / "runs" / f"20210801T00Z_hres_{d.name[:8]}" / "web"
    assert C.check_folder(web) == []
    m = json.loads((web / "manifest.json").read_text())
    assert m["kind"] == "model" and m["synthetic"] is False and m["provenance"]["model_set_id"] == d.name
    assert "truth" not in m["layers"] and m.get("truth_source") is None      # in-sample season: no IMD comparison
    assert m["provenance"]["model_hashes"]


def test_tampered_model_set_is_refused(pipeline, tmp_path):
    import shutil
    root, _, _ = pipeline
    d = tmp_path / "ms"
    shutil.copytree(root / "cache" / "fold=2019" / "model", d)
    with open(d / "classifier" / "temperature.json", "w") as fh:
        fh.write('{"T": 9.0}')
    with pytest.raises(ModelSetError, match="hash mismatch"):
        ModelSet.load(d)


def test_hres_run_errors(pipeline):
    _, cfgs, _ = pipeline
    assert cli.main(["run", "--source", "hres"] + cfgs) == 2
    assert cli.main(["run", "--source", "hres", "--init", "2021-08-01", "--model-set", "nope"] + cfgs) == 1
    assert cli.main(["run", "--source", "hres", "--init", "2021-01-05", "--model-set", "latest"] + cfgs) == 1


def test_import_kaggle_output(pipeline, tmp_path):
    """A Kaggle output folder (models/, reports/, cache/fold=*/) lands in a fresh checkout's paths."""
    import shutil
    root, cfgs, cfg = pipeline
    if not list((root / "models").glob("*/hashes.json")):
        assert cli.main(["fit-final"] + cfgs) == 0
    out = tmp_path / "kaggle" / "working"
    for k in ("models", "reports", "cache"):
        shutil.copytree(root / k, out / k)
    dest = tmp_path / "checkout"
    assert cli.main(["import-kaggle", str(tmp_path / "kaggle"), "--data-root", str(dest)] + cfgs[:2]) == 0
    assert list((dest / "models").glob("*/hashes.json")) and list((dest / "reports").glob("*/verification_report.json"))
    fold = dest / "cache" / "fold=2020"
    assert (fold / "DONE").exists() and (fold / "predictions.parquet").exists() and (fold / "model" / "hashes.json").exists()
    assert cli.main(["import-kaggle", str(tmp_path / "kaggle"), "--data-root", str(dest)] + cfgs[:2]) == 0   # idempotent skip
    assert cli.main(["import-kaggle", str(tmp_path / "empty"), "--data-root", str(dest)] + cfgs[:2]) == 1


def test_partial_model_sets_are_not_resolved(pipeline):
    import shutil
    root, cfgs, cfg = pipeline
    if not list((root / "models").glob("*/hashes.json")):
        assert cli.main(["fit-final"] + cfgs) == 0
    good = resolve(cfg, "latest")
    part = good.with_name(good.name + ".partial")
    shutil.copytree(good, part)
    try:
        assert resolve(cfg, "latest") == good and resolve(cfg, good.name[:6]) == good
    finally:
        shutil.rmtree(part)
