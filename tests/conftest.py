import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(scope="session")
def pipeline(tmp_path_factory):
    """The pilot pipeline (static -> label -> features -> backtest -> report) on the synthetic world of
    test_pipeline_e2e, built once and shared by the replay, model-set and live tests."""
    import numpy as np
    import yaml
    pytest.importorskip("lightgbm")
    pytest.importorskip("zarr")
    from test_pipeline_e2e import SEASONS, make_world
    from regimerain import cli
    from regimerain.config import load_config
    root = tmp_path_factory.mktemp("pipeline")
    make_world(root, np.random.default_rng(0))
    over = {
        "seasons": SEASONS, "leads": [1], "num_threads": 2,
        "paths": {k: str(root / v) for k, v in {"raw": "raw", "static": "data/static", "table": "data/table", "cache": "cache",
                                               "reports": "reports", "imd": "imd", "runs": "runs", "models": "models"}.items()},
        "grid": {"rain_box": [10.0, 14.0, 70.0, 75.0]},
        "labels": {"climatology": "self", "cmz_box": [10, 14, 70, 75], "depression_radius_km": 150},
        "features": {"llj_box": [8, 12, 68, 72], "trough_lon_band": [72, 76], "trough_lat_band": [9, 15],
                     "bob_box": [12, 16, 73, 77], "vort_max_filter_cells": 5},
        "classifier": {"params": {"num_boost_round": 60, "min_data_in_leaf": 50}},
        "qm": {"n0_days": 10},
        "verify": {"bootstrap_B": {"fast": 30, "full": 30}},
    }
    f = root / "test.yaml"
    f.write_text(yaml.safe_dump(over))
    cfgs = ["--config", str(cli.REPO_ROOT / "config" / "default.yaml"), "--config", str(f)]
    for step in (["static"], ["label"], ["features"], ["backtest", "--variants", "raw,A,B"], ["report"]):
        assert cli.main(step + cfgs) == 0
    return root, cfgs, load_config([cli.REPO_ROOT / "config" / "default.yaml", f])


