"""Rows of (lead, lat_idx, lon_idx) predictions -> (lead, lat, lon) grids. One copy, used by the replay
and the model-set producers, so both place values on the map identically."""
from __future__ import annotations

import numpy as np
import pandas as pd

from regimerain.features.schema import REGIME_PROB_FEATURES


def land_mask(df: pd.DataFrame, leads: list[int], shape2: tuple[int, int]) -> np.ndarray:
    """Cells with a row at every lead (IMD-missing cell-days are dropped upstream)."""
    land = np.ones(shape2, bool)
    for L in leads:
        d = df[df.lead == L]
        m = np.zeros(shape2, bool)
        m[d.lat_idx.to_numpy(int), d.lon_idx.to_numpy(int)] = True
        land &= m
    if not land.any():
        raise ValueError("no cell has a prediction at every lead")
    return land


def rows_to_grid(df: pd.DataFrame, leads: list[int], shape2: tuple[int, int], col: str, land: np.ndarray) -> np.ndarray:
    a = np.full((len(leads),) + shape2, np.nan, "float32")
    for k, L in enumerate(leads):
        d = df[df.lead == L]
        a[k, d.lat_idx.to_numpy(int), d.lon_idx.to_numpy(int)] = d[col].to_numpy("float32")
    a[:, ~land] = np.nan
    return a


def regime_probs(df: pd.DataFrame, leads: list[int], shape2: tuple[int, int], land: np.ndarray) -> np.ndarray:
    """(lead, lat, lon, 4) synoptic probabilities, 0 off land, renormalised on land (float32 after smoothing)."""
    P = np.zeros((len(leads),) + shape2 + (len(REGIME_PROB_FEATURES),), "float32")
    for k, L in enumerate(leads):
        d = df[df.lead == L]
        P[k, d.lat_idx.to_numpy(int), d.lon_idx.to_numpy(int)] = d[REGIME_PROB_FEATURES].to_numpy("float32")
    P[:, ~land] = 0
    P[:, land] /= P[:, land].sum(-1, keepdims=True)
    return P
