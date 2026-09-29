"""Write a SYNTHETIC run so the frontend can be built before the regimerain pipeline exists.

Nothing written here is a forecast or a measurement. Every file carries "synthetic": true and the
UI shows a banner while it is set. The real pipeline writes the same file names and shapes into
web/public/run/<run_id>/, so the frontend needs no change when a real run replaces this one.

Also writes web/public/geo/land.json: Natural Earth 1:50m land (public domain), clipped to the map
box. Coastline only; no political boundaries are drawn anywhere in the UI.

    python3 mvp/tools/make_sample_run.py
"""
import json
import math
import pathlib
import urllib.request

import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
WEB = HERE.parent / "web" / "public"
RUN = WEB / "run" / "sample"
GEO = WEB / "geo"
CACHE = HERE / "cache"
NE_URL = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_50m_land.geojson"

for d in (RUN, GEO, CACHE):
    d.mkdir(parents=True, exist_ok=True)
rng = np.random.default_rng(26080)

# ---------------------------------------------------------------- land polygons
MAP_BOX = (10.0, -12.0, 125.0, 50.0)  # lon0, lat0, lon1, lat1 (map extent, wider than the data box)


def clip_ring(ring, box):
    """Sutherland-Hodgman clip of one ring against an axis-aligned box."""
    x0, y0, x1, y1 = box
    edges = [
        (lambda p: p[0] >= x0, lambda a, b: (x0, a[1] + (b[1] - a[1]) * (x0 - a[0]) / (b[0] - a[0]))),
        (lambda p: p[0] <= x1, lambda a, b: (x1, a[1] + (b[1] - a[1]) * (x1 - a[0]) / (b[0] - a[0]))),
        (lambda p: p[1] >= y0, lambda a, b: (a[0] + (b[0] - a[0]) * (y0 - a[1]) / (b[1] - a[1]), y0)),
        (lambda p: p[1] <= y1, lambda a, b: (a[0] + (b[0] - a[0]) * (y1 - a[1]) / (b[1] - a[1]), y1)),
    ]
    pts = [tuple(p) for p in ring]
    for inside, cut in edges:
        if not pts:
            break
        out = []
        for i, cur in enumerate(pts):
            prev = pts[i - 1]
            if inside(cur):
                if not inside(prev):
                    out.append(cut(prev, cur))
                out.append(cur)
            elif inside(prev):
                out.append(cut(prev, cur))
        pts = out
    return pts


src = CACHE / "ne_50m_land.geojson"
if not src.exists():
    urllib.request.urlretrieve(NE_URL, src)
land_rings = []
for f in json.loads(src.read_text())["features"]:
    g = f["geometry"]
    polys = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
    for poly in polys:
        outer = poly[0]
        xs = [p[0] for p in outer]
        ys = [p[1] for p in outer]
        if max(xs) < MAP_BOX[0] or min(xs) > MAP_BOX[2] or max(ys) < MAP_BOX[1] or min(ys) > MAP_BOX[3]:
            continue
        r = clip_ring(outer, MAP_BOX)
        if len(r) >= 4:
            r = [[round(x, 3), round(y, 3)] for x, y in r]
            if r[0] != r[-1]:
                r.append(r[0])
            land_rings.append(r)
(GEO / "land.json").write_text(json.dumps({
    "type": "FeatureCollection",
    "attribution": "Made with Natural Earth (public domain). Coastline only.",
    "features": [{"type": "Feature", "properties": {}, "geometry": {"type": "Polygon", "coordinates": [r]}}
                 for r in land_rings],
}, separators=(",", ":")))


def point_in_rings(lon, lat, rings):
    """Vectorised even-odd test; lon/lat are flat arrays."""
    inside = np.zeros(lon.shape, bool)
    for ring in rings:
        r = np.asarray(ring)
        xs, ys = r[:, 0], r[:, 1]
        if lon.max() < xs.min() or lon.min() > xs.max():
            continue
        x1, y1, x2, y2 = xs[:-1], ys[:-1], xs[1:], ys[1:]
        for a, b, c, d in zip(x1, y1, x2, y2):
            cond = (b > lat) != (d > lat)
            xint = (c - a) * (lat - b) / np.where(d - b == 0, 1e-12, d - b) + a
            inside ^= cond & (lon < xint)
    return inside


# ---------------------------------------------------------------- grid
STEP = 0.5
LATS = np.arange(6.25, 38.0, STEP)
LONS = np.arange(68.25, 98.0, STEP)
NLAT, NLON = len(LATS), len(LONS)
LAT, LON = np.meshgrid(LATS, LONS, indexing="ij")  # row 0 = southmost
LAND = point_in_rings(LON.ravel(), LAT.ravel(), land_rings).reshape(NLAT, NLON)

# coastal = land cell with a sea cell within one grid step
pad = np.pad(~LAND, 1, constant_values=True)
near_sea = np.zeros_like(LAND)
for dy in (-1, 0, 1):
    for dx in (-1, 0, 1):
        near_sea |= pad[1 + dy:1 + dy + NLAT, 1 + dx:1 + dx + NLON]
COAST = LAND & near_sea

REGIMES = ["active", "break", "depression", "coastal", "orographic", "other"]
LEADS = 5
DATES = ["2022-07-15", "2022-07-16", "2022-07-17", "2022-07-18", "2022-07-19"]


def band(x, lo, hi, w=1.2):
    """Soft 0..1 window: ~1 between lo and hi, fading over w degrees (no hard edges in the sample field)."""
    return 1 / (1 + np.exp(-(x - lo) / (w / 4))) * 1 / (1 + np.exp((x - hi) / (w / 4)))


def smooth(a, k=2):
    out = a.copy()
    for _ in range(k):
        out = (out + np.roll(out, 1, 0) + np.roll(out, -1, 0) + np.roll(out, 1, 1) + np.roll(out, -1, 1)) / 5
    return out


ghats_lon = 73.5 + (21 - LAT) * (3.5 / 12.5)
GHATS = np.exp(-((LON - ghats_lon + 0.25) / 0.55) ** 2) * band(LAT, 8, 21.5)
foot_lat = np.interp(LON, [76, 80, 84, 88, 92, 96], [31.0, 29.3, 27.8, 27.0, 27.2, 28.2])
HIMAL = np.exp(-((LAT - foot_lat) / 0.8) ** 2) * band(LON, 75.5, 96.5, 2)
KHASI = np.exp(-((LAT - 25.3) ** 2 + (LON - 91.7) ** 2) / 0.35)
ARAKAN = np.exp(-((LON - (93.8 - (LAT - 17) * 0.35)) / 0.6) ** 2) * band(LAT, 15.5, 22.5)
TERRAIN = np.clip(GHATS + HIMAL + KHASI + ARAKAN, 0, 1)
TIBET = band(LAT, 31, 60, 2) * band(LON, 78, 120, 2)

FACTOR = {"active": 1.10, "break": 0.82, "depression": 1.36, "coastal": 0.93, "orographic": 1.24, "other": 1.0}
noise_base = smooth(rng.normal(0, 1, (NLAT, NLON)), 4)

layers = {k: [] for k in ("raw", "corrected", "p_heavy", "p_very_heavy", "regime", "u850", "v850", "wind850")}
regime_probs = []
per_lead_cells = []

for d in range(LEADS):
    t = d / (LEADS - 1)
    clat, clon = 20.0 + 3.6 * t, 87.6 - 10.0 * t
    dx, dy = LON - clon, LAT - clat
    r = np.hypot(dx, dy) + 1e-6

    u = 13 * np.exp(-((LAT - 12.5) / 4.5) ** 2) - 6 * np.exp(-((LAT - 27.5) / 2.5) ** 2) + 2
    v = 4.5 * np.exp(-((LAT - 13) / 6) ** 2)
    vt = 15 * (r / 2.6) * np.exp(1 - r / 2.6)
    u += -vt * dy / r
    v += vt * dx / r
    damp = np.where(LAND, 0.65, 1.0) * (1 - 0.65 * TIBET)
    u, v = u * damp, v * damp

    noise = smooth(noise_base * 0.6 + rng.normal(0, 1, (NLAT, NLON)) * 0.8, 3)
    trough_lat = 22.5 + 1.2 * t
    raw = (
        1.2
        + 3.4 * np.clip(u, 0, None) * GHATS
        + 34 * HIMAL + 70 * KHASI + 38 * ARAKAN
        + 92 * np.exp(-((dx + 0.9) ** 2 + (dy + 0.7) ** 2) / (2 * 1.5 ** 2))
        + 17 * np.exp(-((LAT - trough_lat) / 2.8) ** 2) * band(LON, 71, 89, 4)
    )
    raw *= np.exp(0.38 * noise)
    raw *= 1 - 0.75 * TIBET
    raw *= 1 - 0.65 * band(LON, 50, 75.5, 3) * band(LAT, 23.5, 60, 3)  # Thar and the north-west stay dry
    SHADOW = band(LAT, 0, 17, 2) * band(LON, 76.5, 80.5, 1.5)
    raw *= 1 - 0.55 * SHADOW  # rain shadow east of the Ghats

    scores = np.stack([
        2.2 * np.exp(-((LAT - trough_lat) / 3.2) ** 2) * band(LON, 71, 89, 3),
        1.4 * SHADOW + 0.25,
        3.6 * np.exp(-(r ** 2) / (2 * 2.0 ** 2)),
        1.5 * COAST,
        2.4 * TERRAIN,
        np.full(LAT.shape, 0.75),
    ], -1) + rng.normal(0, 0.15, (NLAT, NLON, 6))
    e = np.exp(scores * 1.7 - (scores * 1.7).max(-1, keepdims=True))
    probs = e / e.sum(-1, keepdims=True)
    top = probs.argmax(-1)

    fac = np.vectorize(lambda i: FACTOR[REGIMES[i]])(top)
    corrected = raw * fac * np.exp(rng.normal(0, 0.035, raw.shape))
    p_h = 1 / (1 + np.exp(-(corrected - 64.5) / 10))
    p_vh = 1 / (1 + np.exp(-(corrected - 124.5) / 13))

    def land_only(a, nd):
        return [round(float(x), nd) if m else None for x, m in zip(a.ravel(), LAND.ravel())]

    layers["raw"].append(land_only(raw, 1))
    layers["corrected"].append(land_only(corrected, 1))
    layers["p_heavy"].append(land_only(p_h, 2))
    layers["p_very_heavy"].append(land_only(p_vh, 2))
    layers["regime"].append([int(x) if m else -1 for x, m in zip(top.ravel(), LAND.ravel())])
    layers["u850"].append([round(float(x), 1) for x in u.ravel()])
    layers["v850"].append([round(float(x), 1) for x in v.ravel()])
    layers["wind850"].append([round(float(x), 1) for x in np.hypot(u, v).ravel()])
    pr = (probs * 100).round().astype(int)
    regime_probs.append([int(x) if m else 0 for x, m in zip(pr.reshape(-1, 6).ravel(), np.repeat(LAND.ravel(), 6))])
    per_lead_cells.append(dict(raw=raw, corrected=corrected, p_h=p_h, p_vh=p_vh, top=top, probs=probs,
                               centre=(round(clat, 2), round(clon, 2))))

(RUN / "grid.json").write_text(json.dumps({
    "synthetic": True,
    "lat0": float(LATS[0]), "lon0": float(LONS[0]), "step": STEP, "nlat": NLAT, "nlon": NLON,
    "row_order": "south_to_north",
    "regimes": REGIMES,
    "leads": [{"index": i, "valid_date": DATES[i], "lead_hours": 24 * (i + 1)} for i in range(LEADS)],
    "layers": layers,
    "regime_probs_pct": regime_probs,
}, separators=(",", ":")))

# ---------------------------------------------------------------- places
PLACES = [
    ("Mumbai", 19.08, 72.88), ("Delhi", 28.61, 77.21), ("Kolkata", 22.57, 88.36), ("Chennai", 13.08, 80.27),
    ("Bengaluru", 12.97, 77.59), ("Hyderabad", 17.39, 78.49), ("Ahmedabad", 23.02, 72.57), ("Pune", 18.52, 73.86),
    ("Jaipur", 26.91, 75.79), ("Lucknow", 26.85, 80.95), ("Bhopal", 23.26, 77.41), ("Nagpur", 21.15, 79.09),
    ("Patna", 25.59, 85.14), ("Bhubaneswar", 20.30, 85.82), ("Raipur", 21.25, 81.63), ("Ranchi", 23.34, 85.31),
    ("Guwahati", 26.14, 91.74), ("Shillong", 25.58, 91.89), ("Kochi", 9.93, 76.27),
    ("Thiruvananthapuram", 8.52, 76.94), ("Mangaluru", 12.91, 74.86), ("Panaji", 15.49, 73.83),
    ("Visakhapatnam", 17.69, 83.22), ("Indore", 22.72, 75.86), ("Varanasi", 25.32, 82.97),
    ("Dehradun", 30.32, 78.03), ("Srinagar", 34.08, 74.80), ("Chandigarh", 30.73, 76.78),
    ("Jabalpur", 23.18, 79.99), ("Surat", 21.17, 72.83), ("Kozhikode", 11.26, 75.78), ("Imphal", 24.82, 93.94),
    ("Agartala", 23.83, 91.28), ("Siliguri", 26.73, 88.40), ("Gorakhpur", 26.76, 83.37), ("Jodhpur", 26.24, 73.02),
    ("Sambalpur", 21.47, 83.97), ("Balasore", 21.49, 86.93), ("Jagdalpur", 19.08, 82.03), ("Ratnagiri", 16.99, 73.31),
]
N_DAYS = {"active": 612, "break": 388, "depression": 141, "coastal": 1804, "orographic": 1377, "other": 2461}

places = []
for name, la, lo in PLACES:
    i, j = int(round((la - LATS[0]) / STEP)), int(round((lo - LONS[0]) / STEP))
    if not LAND[i, j]:
        cands = [(abs(a) + abs(b), i + a, j + b) for a in (-1, 0, 1) for b in (-1, 0, 1)
                 if 0 <= i + a < NLAT and 0 <= j + b < NLON and LAND[i + a, j + b]]
        _, i, j = min(cands)
    leads = []
    for c in per_lead_cells:
        reg = REGIMES[int(c["top"][i, j])]
        leads.append({
            "raw_mm": round(float(c["raw"][i, j]), 1), "corrected_mm": round(float(c["corrected"][i, j]), 1),
            "p_heavy": round(float(c["p_h"][i, j]), 2), "p_very_heavy": round(float(c["p_vh"][i, j]), 2),
            "regime": reg, "regime_probs": {r: round(float(p), 2) for r, p in zip(REGIMES, c["probs"][i, j])},
            "qm_curve": f"{reg}/JJAS", "qm_curve_days": N_DAYS[reg],
        })
    places.append({"name": name, "lat": la, "lon": lo, "cell": {"lat": float(LATS[i]), "lon": float(LONS[j])},
                   "leads": leads})
(RUN / "places.json").write_text(json.dumps({"synthetic": True, "places": places}, separators=(",", ":")))

# ---------------------------------------------------------------- quantile-mapping curves
QS = np.linspace(0, 1, 41)
SHAPE = {"active": 1.3, "break": 0.8, "depression": 1.6, "coastal": 1.1, "orographic": 1.4, "other": 0.9}
SCALE = {"active": 14, "break": 6, "depression": 28, "coastal": 11, "orographic": 18, "other": 7}
curves = []
allf, allt = [], []
for reg in REGIMES:
    f = rng.gamma(SHAPE[reg], SCALE[reg], N_DAYS[reg] * 40)
    tail = 1 + 0.35 * (FACTOR[reg] - 1) * np.clip(f / np.percentile(f, 90), 0, 3)
    tr = f * FACTOR[reg] * tail * np.exp(rng.normal(0, 0.18, f.size))
    allf.append(f)
    allt.append(tr)
    curves.append({"regime": reg, "id": f"{reg}/JJAS", "n_days": N_DAYS[reg], "quantiles": QS.round(3).tolist(),
                   "forecast_mm": np.quantile(f, QS).round(1).tolist(), "truth_mm": np.quantile(tr, QS).round(1).tolist()})
F, T = np.concatenate(allf), np.concatenate(allt)
curves.append({"regime": "global", "id": "global/JJAS", "n_days": sum(N_DAYS.values()), "quantiles": QS.round(3).tolist(),
               "forecast_mm": np.quantile(F, QS).round(1).tolist(), "truth_mm": np.quantile(T, QS).round(1).tolist()})
(RUN / "qm_curves.json").write_text(json.dumps({"synthetic": True, "curves": curves}, separators=(",", ":")))

# ---------------------------------------------------------------- verification (invented, flagged)
KEYS = ["rmse", "ets", "csi", "pod", "far", "fss_25km", "fss_50km"]
POOLED = {
    "heavy": ([14.8, 0.21, 0.27, 0.46, 0.52, 0.38, 0.51], [13.9, 0.24, 0.30, 0.50, 0.54, 0.43, 0.56]),
    "very_heavy": ([31.0, 0.08, 0.11, 0.22, 0.71, 0.17, 0.26], [30.1, 0.09, 0.13, 0.27, 0.70, 0.20, 0.26]),
}
REG_DELTA = {  # corrected minus raw, sign convention per metric; invented to exercise the UI
    "active": [-0.8, 0.02, 0.03, 0.04, -0.01, 0.04, 0.04],
    "break": [0.6, -0.01, -0.02, -0.03, 0.05, -0.02, -0.01],
    "depression": [-2.9, 0.06, 0.07, 0.11, -0.03, 0.09, 0.08],
    "coastal": [-0.2, 0.00, 0.01, 0.00, 0.02, 0.01, 0.00],
    "orographic": [-1.6, 0.04, 0.05, 0.07, 0.01, 0.06, 0.07],
    "other": [-0.1, 0.00, 0.00, 0.01, 0.00, 0.00, 0.01],
}
counts = {r: N_DAYS[r] for r in REGIMES}
report = []
for th, (b, c) in POOLED.items():
    report.append({"fold": "pooled", "threshold": th, "baseline": dict(zip(KEYS, b)), "corrected": dict(zip(KEYS, c)),
                   "n_samples": 0, "regime_sample_counts": counts})
    for season in range(2016, 2023):
        j = rng.normal(0, 1, len(KEYS))
        bb = [round(x * (1 + 0.08 * jj), 3) for x, jj in zip(b, j)]
        cc = [round(x * (1 + 0.08 * jj) + (y - x) * (1 + 0.6 * rng.normal()), 3) for x, y, jj in zip(b, c, j)]
        report.append({"fold": str(season), "threshold": th, "baseline": dict(zip(KEYS, bb)),
                       "corrected": dict(zip(KEYS, cc)), "n_samples": 0})
    scale = 1.0 if th == "heavy" else 0.7
    for reg, dl in REG_DELTA.items():
        cc = [round(x + y * scale, 3) for x, y in zip(b, dl)]
        report.append({"fold": "pooled", "threshold": th, "regime": reg, "baseline": dict(zip(KEYS, b)),
                       "corrected": dict(zip(KEYS, cc)), "n_samples": 0})

bins = np.linspace(0.05, 0.95, 10)
reliability = {
    th: [{"p_forecast": round(float(p), 2),
          "p_observed": round(float(np.clip(p * (0.88 if th == "heavy" else 0.8) + rng.normal(0, 0.03), 0, 1)), 3),
          "n": int(4000 * math.exp(-5 * p) + 40)} for p in bins]
    for th in ("heavy", "very_heavy")
}
(RUN / "verification.json").write_text(json.dumps(
    {"synthetic": True, "cv": "leave-one-monsoon-out", "entries": report, "reliability": reliability}, indent=1))

# ---------------------------------------------------------------- manifest
best = max(((d, i, j) for d in range(LEADS) for i in range(NLAT) for j in range(NLON) if LAND[i, j]),
           key=lambda k: per_lead_cells[k[0]]["corrected"][k[1], k[2]])
d, i, j = best
c = per_lead_cells[d]
(RUN / "manifest.json").write_text(json.dumps({
    "synthetic": True,
    "run_id": "sample",
    "forecast_issue_date": "2022-07-14",
    "forecast_source": "sample (not real)",
    "truth_source": "sample (not real)",
    "grid_step_deg": STEP,
    "unit": "mm/day",
    "thresholds_mm": {"heavy": 64.5, "very_heavy": 124.5},
    "fss_radii_km": [25, 50],
    "regime_days": counts,
    "depression_track": [{"lead": k, "lat": c2["centre"][0], "lon": c2["centre"][1]} for k, c2 in enumerate(per_lead_cells)],
    "wettest": {
        "lead": d, "valid_date": DATES[d], "lat": float(LATS[i]), "lon": float(LONS[j]),
        "raw_mm": round(float(c["raw"][i, j]), 1), "corrected_mm": round(float(c["corrected"][i, j]), 1),
        "p_heavy": round(float(c["p_h"][i, j]), 2), "p_very_heavy": round(float(c["p_vh"][i, j]), 2),
        "regime": REGIMES[int(c["top"][i, j])],
    },
}, indent=2))

for p in sorted(RUN.iterdir()) + [GEO / "land.json"]:
    print(f"{p.stat().st_size / 1024:8.1f} KB  {p.relative_to(WEB)}")
print(f"land cells: {int(LAND.sum())} of {NLAT * NLON}")
