# Regime-Aware Rainfall Post-Processing — Technical Specification

Engineering counterpart to `PRD.md`. This is the how: units, coordinate frames, data contracts field by field, module-by-module design, numerical rules, and the CLI. No MVP exists yet at time of writing — every number here is a design target, not a measurement. Write measured numbers into `runs/<run_id>/verification_report.json` as they appear, and only quote those.

Package name (proposed, matching the `../143/darktransit` convention): **`regimerain`**.

---

## 1. Scope and traceability to the PRD

Implements PRD §8–§13 (architecture, functional requirements FR-1..FR-9, algorithms §10, data model §11, API §12, interface §13). Read `PRD.md` first for *why*; this document is *how*.

## 2. Coordinate frames, domains and grids

- **Spatial domain.** India bounding box, roughly 6°N–38°N, 68°E–98°E. All gridded products are clipped to this box before any computation — do not carry global WeatherBench2/CHIRPS extents through the pipeline.
- **Forecast/reanalysis grid.** WeatherBench2 HRES and ERA5 are natively 0.25°. This is the classifier and QM working grid.
- **Truth grid (CHIRPS).** Native 0.05° (~5 km). Two uses, two treatments:
  - For QM fitting and the six-metric verification against the forecast grid: **conservative-average CHIRPS down to the 0.25° forecast grid** (area-weighted mean of the 5×5 CHIRPS cells inside each 0.25° cell). Do not point-sample or bilinear-interpolate truth onto a coarser grid — that discards the extremes the whole PS is about.
  - For the district-level product (PRD §10.4): use **native-resolution CHIRPS**, corrected by applying the (coarser) regime-conditioned correction ratio/offset at each fine cell, then aggregate to district polygons. This keeps sub-grid variability in the district product instead of losing it at the 0.25° regridding step.
- **Time.** All timestamps UTC, ISO-8601 in every artefact. Daily-accumulated rainfall (00–24 UTC) is the modelling unit — do not mix IST daily-accumulation conventions (03 UTC–03 UTC, IMD's usual convention) with WeatherBench2/CHIRPS UTC-day conventions inside one pipeline; pick UTC-day everywhere and document the offset from IMD's convention once, in `docs/units.md`.
- **Units.** Rainfall in mm/day throughout, both truth and forecast, before any conversion. Wind fields in m/s. Convert once at ingestion (module 1); no unit conversion inside any downstream module.
- **District polygons.** Indian district boundaries, WGS84 (EPSG:4326), same CRS as everything else in the pipeline — no reprojection step should exist in the codebase.

## 3. Data contracts

### 3.1 Ingested inputs (module 1 output — `data/raw/`)

| File | Contents | Dims | Units |
|---|---|---|---|
| `era5_india_<year>.nc` | ERA5 fields: total precipitation, 850 hPa u/v wind, specific humidity, vertically integrated moisture flux | `time, lat, lon` | mm/day, m/s, kg/kg, kg/m/s |
| `hres_india_<year>.nc` | HRES forecast, same variables, forecast lead time dimension | `time, lead, lat, lon` | as above |
| `chirps_india_<year>.nc` | CHIRPS daily rainfall, native 0.05° | `time, lat, lon` | mm/day |
| `ibtracs_nio.csv` | North Indian Ocean basin track records | row per (storm, timestep) | knots, lat/lon |
| `mjo_rmm.csv` | Daily RMM1, RMM2, phase, amplitude | row per day | dimensionless |
| `district_boundaries.geojson` | District polygons + IDs | — | WGS84 |
| `terrain_dem_india.nc` | Elevation, slope, distance-to-coast (precomputed static layers) | `lat, lon` | m, degrees, km |

### 3.2 Derived training data (module 2 output — `data/labelled/`)

`regime_labels_<year>.nc`: `time, lat, lon` → categorical regime label ∈ {active, break, depression, coastal, orographic, other}, built by the precedence rule in PRD §10.1. Carries a `label_confidence` companion variable (1.0 for static coastal/orographic masks, index-magnitude-scaled for active/break, track-distance-scaled for depression).

### 3.3 Run artefacts (`runs/<run_id>/`)

As specified in PRD §11. Additionally, per this spec:

- `manifest.json` MUST include: `forecast_issue_date`, `forecast_source` (`hres` \| `gfs`), `truth_source` (`chirps` \| `imd`), `regime_model_sha256`, `qm_curve_set_version`, `exceedance_model_sha256`, `seed`, `git_commit`.
- `verification_report.json` schema:
  ```json
  {
    "fold": "2019" ,
    "threshold": "heavy",
    "baseline": {"rmse": 0.0, "ets": 0.0, "csi": 0.0, "pod": 0.0, "far": 0.0, "fss_25km": 0.0, "fss_50km": 0.0},
    "corrected": {"rmse": 0.0, "ets": 0.0, "csi": 0.0, "pod": 0.0, "far": 0.0, "fss_25km": 0.0, "fss_50km": 0.0},
    "n_samples": 0,
    "regime_sample_counts": {"active": 0, "break": 0, "depression": 0, "coastal": 0, "orographic": 0, "other": 0}
  }
  ```
  One object per (fold, threshold) pair; the full report is a JSON array of these plus a pooled entry with `"fold": "pooled"`.

## 4. Module-by-module design

### 4.1 `ingest` — module 1

Pulls WeatherBench2 zarr stores (via `xarray`/`gcsfs`, anonymous access), CHIRPS over HTTPS, IBTrACS and MJO RMM as flat files, clips all to the India box, writes `data/raw/`. Idempotent: re-running with the same date range and same source versions produces byte-identical output (NFR-1).

**Performance budget.** One monsoon season (Jun–Sep) of 0.25° India-box HRES + ERA5 + CHIRPS ≈ low hundreds of MB; a full multi-year pull for training should complete in well under an hour on a laptop with a normal connection — this is a download-bound step, not compute-bound.

### 4.2 `label` — module 2

Computes the active/break index (normalized rainfall anomaly over the core monsoon zone box, threshold ±1σ, ≥3 consecutive days to flag — standard convention, cite the exact formula used in the module docstring), flags depression days/cells from IBTrACS (within an event radius, currently proposed 300 km — tune during Phase 0/1 and record the chosen radius in `manifest.json`), and applies the static terrain/coastal masks. Runs once over the full historical window; output feeds both classifier training (module 3) and QM fitting (module 4).

### 4.3 `classify` — module 3

Trains a multi-class gradient-boosted classifier (LightGBM, `objective=multiclass`) on forecast-time-only features (§ PRD 10.1) against the module-2 labels. **Leakage guard:** the feature builder must not import any column whose name matches `*_truth*` or that is derived from CHIRPS; enforce with a unit test that inspects the feature list at training time (this is AC-1 from the PRD, made concrete).

At inference: outputs a probability vector per grid-cell/day; the static coastal/orographic masks override the learned probabilities for cells inside those masks (PRD §10.1).

### 4.4 `correct` — module 4

Fits one empirical-CDF quantile-mapping curve per (regime, season) pair on historical (forecast, truth) rainfall pairs restricted to that regime's labelled days. Implementation: sort forecast and truth samples independently, build empirical CDFs via linear interpolation between sorted order statistics; for a new forecast value, find its percentile in the forecast CDF and map to the truth value at that percentile. **Tail handling:** for forecast values above the training range's maximum, extrapolate using the ratio of the top-decile mean (truth/forecast) rather than a flat clip — heavy-rain values are exactly the tail this PS cares about, and clipping would silently defeat the point.

Records the sample count behind each curve in the curve's metadata (risk mitigation in PRD §20).

### 4.5 `exceed` — module 5

Two binary GBM classifiers (heavy ≥64.5 mm/day, very-heavy ≥124.5 mm/day — IMD's operational thresholds), features per PRD §10.3. Calibrated post-hoc (isotonic regression) on a held-out fold, never on the same fold used for the reliability diagram shown in the deck.

### 4.6 `aggregate` — module 6

Area-weighted spatial join of corrected rainfall + exceedance grids onto district polygons (`geopandas` + exact-overlap area weights, not centroid-in-polygon — a district's true area-weighted mean requires the former). Outputs both mean and max per district (PRD §10.4).

### 4.7 `verify` — module 7

Computes the six metrics (formulas in PRD §17.1) for baseline and corrected, at both thresholds, per leave-one-monsoon-out fold and pooled. FSS computed via the standard fractions-in-neighbourhood method at 25 km and 50 km radii (radii chosen as roughly 1 and 2 forecast grid cells at 0.25°; document if the final grid choice changes this). Writes `verification_report.json` per §3.3 and the reliability diagram PNG.

### 4.8 `api` — module 8

FastAPI app per PRD §12. Stateless beyond reading `runs/<run_id>/` off disk; a `POST /runs/live` handler triggers ingest (today only) → classify → correct → exceed → aggregate → verify against the live forecast, writes a new `run_id`, and returns it. No retraining in the live path — models load from the last fitted artefact.

### 4.9 `web` — module 9

Static frontend, MapLibre GL, following `../167/`'s workstation scaffolding (basemap handling, layer toggles) and the Field Atlas visual language (light theme — see `docs/PPT_BRIEF.md`). Two panels per PRD §13: map view and scorecard panel. No client-side computation of any metric — every displayed number is read from the API response, never recomputed in JS (NFR-2).

## 5. Determinism and numerical rules

- Fix random seeds for all GBM training and any stochastic split; record the seed in `manifest.json` (NFR-1).
- Quantile-mapping curves and trained model artefacts are content-hashed (`sha256`) and the hash recorded in `manifest.json`, so a run can be traced to the exact model version that produced it, even after retraining.
- No metric or corrected value is ever computed twice by two different code paths (e.g., once in the pipeline, once again in the frontend for display) — single source of truth is `verify` module output.

## 6. Non-functional and safety notes

- All data sources are open (§ PRD 14); no PII, no access credentials to manage, no dual-use sensitivity comparable to `../143/`'s vessel-attribution problem. The one integrity control that matters here is NFR-2 (no fabricated numbers) — replicate `../143/`'s pattern of a repo-level test that asserts no metric/score literal appears in frontend source that isn't read from a run artefact.
- District boundary data licence must be checked before redistribution in the public repo (PRD §20 open question) — if unresolved by build day, ship a small extract (India-only, attribution included) or link to the source rather than committing an unclear-licence file wholesale.

## 7. CLI reference (proposed, mirrors `../143/darktransit/cli.py`)

```bash
python3 -m regimerain.cli ingest --years 2015-2022        # module 1
python3 -m regimerain.cli label                            # module 2
python3 -m regimerain.cli fit                               # modules 3-5, trains all models
python3 -m regimerain.cli validate                          # module 7, leave-one-monsoon-out backtest
python3 -m regimerain.cli run --date today                  # live mode, modules 3-7 against today's forecast
python3 -m regimerain.cli selftest                          # unit + leakage-guard + no-fabricated-number checks
python3 -m regimerain.cli serve                             # http://127.0.0.1:8000/  (map + scorecard)
```

## 8. Test plan

- **Leakage guard** (AC-1): assert the classifier's feature list contains no truth-derived column.
- **No-fabricated-number guard** (AC-5, NFR-2): grep the frontend source for numeric literals that look like scores/probabilities; every one should read from an API call, none hardcoded.
- **Metric correctness**: unit tests for RMSE/ETS/CSI/POD/FAR/FSS against hand-computed toy contingency tables (2×2 cases with known answers) before trusting the pipeline's output on real data.
- **QM round-trip**: mapping the truth distribution through its own fitted QM curve should return ~identity (sanity check on the CDF interpolation implementation).
- **Leave-one-monsoon-out fold isolation**: assert no date from the held-out season appears in any training artefact for that fold (classifier training set, QM curve fitting set, exceedance training set).
