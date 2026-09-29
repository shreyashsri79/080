"""Interim runs from Samanvay data: real layers only, nothing from mock.py, depression placed at the MSLP low."""
import json

import numpy as np
import pytest

from regimerain.config import load_config
from regimerain.runs import contract as C
from regimerain.runs.export_web import export_run
from regimerain.runs.interim import InterimError, interim_fields, jjas_hindcasts, regrid

G = {"lat0": 6.0, "lon0": 66.0, "step": 1.5, "ny": 23, "nx": 23}
CLAT = 6 + 1.5 * np.arange(23)
CLON = 66 + 1.5 * np.arange(23)


class FakeSamanvay:
    def __init__(self, label="Depression", low=(21.0, 87.0)):
        self.label, self.low = label, low

    def runs(self):
        return [{"id": "live-x", "kind": "live", "init": "2026-09-29T00:00Z"},
                {"id": "hindcast-20200804", "kind": "hindcast", "init": "2020-08-04T00:00Z", "status": "ok"},
                {"id": "hindcast-20200101", "kind": "hindcast", "init": "2020-01-01T00:00Z", "status": "ok"}]

    def meta(self, run_id):
        return {"grid": G, "leads": list(range(1, 11)), "regime": {"label": self.label},
                "modelsByVar": {"rain": ["hres", "graphcast"]}, "notes": ["Weights for this date are fitted without its month."]}

    def field(self, run_id, var, lead, model=None):
        LAT, LON = np.meshgrid(CLAT, CLON, indexing="ij")
        if var == "mslp":
            d2 = (LAT - self.low[0]) ** 2 + (LON - self.low[1]) ** 2
            v = 1008 - 16 * np.exp(-d2 / 8)
        else:
            v = 10 + 5 * np.sin(LON / 5) + (3 if model is None else 0)
            v[0, 0] = np.nan                                               # a null cell
        return {"values": [None if np.isnan(x) else float(x) for x in v.ravel()]}


@pytest.fixture(scope="module")
def cfg():
    return load_config()


def test_regrid_is_bilinear_and_south_first():
    vals = [float(i) for i in range(23) for _ in range(23)]                 # value = row index (south = 0)
    a = regrid(vals, G, np.array([6.0, 6.75, 39.0]), np.array([70.0]))
    np.testing.assert_allclose(a[:, 0], [0.0, 0.5, 22.0])


def test_interim_run_layers_are_real_or_absent(cfg, tmp_path):
    f = interim_fields(cfg, __import__("datetime").date(2020, 8, 4), FakeSamanvay())
    assert f.kind == "interim" and not f.synthetic
    assert f.layers() == ["raw", "corrected", "regime", "geo"]              # no wind, P(heavy), truth: not faked
    assert np.nanmean(f.corrected - f.raw) == pytest.approx(3, abs=0.01)    # blend vs HRES member, as served
    top = f.p_synoptic.argmax(-1)
    i, j = np.argmin(abs(f.lat - 21.0)), np.argmin(abs(f.lon - 87.0))
    near_land = f.land[i - 8:i + 8, j - 8:j + 8]
    assert (top[0, i - 8:i + 8, j - 8:j + 8][near_land] == 2).any()          # depression around the low
    assert (top[0][f.land] == 3).any() and f.geo[f.land].max() <= 1          # normal elsewhere; no orographic guess
    web = export_run(f, cfg, tmp_path)
    assert C.check_folder(web) == []
    m = json.loads((web / "manifest.json").read_text())
    assert m["run_id"] == "20200804T00Z_samanvay-hres_interim" and m["depression_track"]
    assert abs(m["depression_track"][0]["lat"] - 21) <= 1 and abs(m["depression_track"][0]["lon"] - 87) <= 1


def test_only_jjas_hindcasts_and_known_labels(cfg):
    assert [r["id"] for r in jjas_hindcasts(FakeSamanvay())] == ["hindcast-20200804"]
    with pytest.raises(InterimError, match="regime label"):
        interim_fields(cfg, __import__("datetime").date(2020, 8, 4), FakeSamanvay(label="Winter"))
