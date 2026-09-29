# Regime-Aware Rainfall Post-Processing — Product Requirements Document

**Problem statement:** SIH26080 · *Regime-Aware AI Post-Processing of Monsoon Rainfall Forecasts*
**Organisation:** Ministry of Earth Sciences (MoES) / NCMRWF · **Category:** Software · **Theme:** Smart Automation
**Revision:** A
**Date:** 29 September 2026 · **Portal deadline:** 20 September 2026 (idea submission; build happens at the finale)

---

## Document control

| | |
|---|---|
| Status | Working draft, binding on the build |
| Owner | Tech lead |
| Source PS text | `docs/PS26080_Brief.md` |
| Companion documents | `TECHNICAL_SPEC.md` (how), `docs/PPT_BRIEF.md` (deck narrative) |
| Sibling project | PS26081 (Hybrid AI–NWP blending), built separately by Mridul; shares the same data pipeline and India domain but is out of scope here |
| Team on this PS | Everyone except Mridul (who owns PS26081) |

**How to read this.** §1–§7 are orientation, readable by a non-specialist. §8–§13 are the build contract: requirement IDs here are the IDs to reuse in code, tests and the deck. §14–§20 are execution planning. Nothing in this document has been measured yet — there is no MVP as of this revision. Every number in §17 is a target, not a result, until an experiment produces it.

---

## Table of contents

**Part I — Orientation**
1. [Summary](#1-summary)
2. [Problem and context](#2-problem-and-context)
3. [The ask, decoded](#3-the-ask-decoded)
4. [Positioning: why this PS, why this angle](#4-positioning-why-this-ps-why-this-angle)
5. [Goals and non-goals](#5-goals-and-non-goals)
6. [Users](#6-users)
7. [Domain primer and glossary](#7-domain-primer-and-glossary)

**Part II — The build contract**
8. [Architecture](#8-architecture)
9. [Functional requirements](#9-functional-requirements)
10. [Algorithms in detail](#10-algorithms-in-detail)
11. [Data model and artefact schemas](#11-data-model-and-artefact-schemas)
12. [API contract](#12-api-contract)
13. [Interface specification](#13-interface-specification)

**Part III — Execution**
14. [Data sources](#14-data-sources)
15. [Stack and rejected alternatives](#15-stack-and-rejected-alternatives)
16. [Non-functional requirements](#16-non-functional-requirements)
17. [Validation and metrics](#17-validation-and-metrics)
18. [Build order, phases, team](#18-build-order-phases-team)
19. [Acceptance criteria](#19-acceptance-criteria)
20. [Risk register and open questions](#20-risk-register-and-open-questions)

---
---

# Part I — Orientation

## 1. Summary

Raw NWP rainfall forecasts are wrong in systematic, regime-dependent ways: they behave differently during active monsoon spells, break spells, monsoon depressions, orographic events (Western Ghats, Himalayan foothills), coastal convection, and western disturbances. One global bias-correction curve, fit across all of these at once, averages away the very structure that would make the correction useful for the events that matter — heavy and very heavy rainfall.

**The one line.** Most bias-correction systems fit one curve to every day of the year. We fit one curve per weather regime, predict the regime from the forecast itself, and only then correct — so the correction sharpens on the events that cost the most: heavy and very heavy rainfall days.

**Why this framing wins this problem statement.** The PS text names its own scorecard — RMSE, ETS, CSI, POD, FAR, FSS — which most teams will not build all six of, and few will run under a leave-one-season-out split (the only split that doesn't leak). NCMRWF's judges are atmospheric scientists; they will ask for skill against a named baseline (raw NWP), not for a nice map. A regime-conditioned correction with the full metric suite, honestly reported including where it does *not* help, is the credible answer to a MoES panel.

## 2. Problem and context

India's rainfall forecast errors are not uniform. A forecast system tuned to perform well on average performs worse than it should during the specific spells that cause damage:

- **Active monsoon** spells (enhanced rainfall over the core monsoon zone) tend toward different error characteristics than **break monsoon** spells (suppressed rainfall, false alarms elsewhere).
- **Monsoon depressions** — low-pressure systems tracked by IMD/IBTrACS — bring concentrated heavy rainfall that models under- or mis-place.
- **Orographic rainfall** (windward Western Ghats, Himalayan foothills/terai belt) is a standing model weakness: coarse-resolution NWP smooths terrain-forced convection.
- **Coastal rainfall** has its own error signature near the coastline versus inland.
- **Western disturbances**, chiefly a winter phenomenon, can interact with the monsoon during onset/withdrawal transitions.

A single global bias-correction (one quantile-mapping curve, one calibration) is what most operational post-processing does. It necessarily under-corrects the regime that most needs it and over-corrects the regime that didn't. The PS asks for the regime-first approach: classify, then correct — and to report the improvement using six named skill scores rather than an anecdote.

## 3. The ask, decoded

The brief (§`docs/PS26080_Brief.md`) lists five deliverables. This is the literal mapping from ask to build:

| PS deliverable | What we build |
|---|---|
| Weather regime classifier (active / break / depression / coastal-orographic) | A multi-class classifier (§10.1) trained on retrospectively-labelled regimes, using only features available *at forecast time* — so it is deployable, not a hindsight label. |
| Bias-corrected rainfall forecast, better than raw NWP | Per-regime empirical quantile mapping (§10.2), conditioned on the classifier's predicted regime. |
| Heavy-rainfall probability above operational thresholds | Gradient-boosted exceedance model (§10.3) for IMD's heavy (≥64.5 mm/day) and very-heavy (≥124.5 mm/day) thresholds. |
| District-level rainfall product | Area-weighted aggregation of the corrected grid to Indian district polygons (§10.4), rendered as table and choropleth. |
| Verification report, RMSE/ETS/CSI/POD/FAR/FSS | §17 — all six, computed under leave-one-monsoon-out cross-validation, against the raw-NWP baseline. |

## 4. Positioning: why this PS, why this angle

Three things separate a credible answer from a UI wrapped around invented numbers:

1. **We name a real baseline and beat it on a named scorecard, or say honestly where we don't.** Bias correction gains are typically a few percent, not a headline. The pitch should not oversell it — see §20.
2. **The regime classifier is causally upstream of the correction, and is itself falsifiable.** A judge can ask "what regime is active today" and get an answer with a probability, not a black box.
3. **This is the least novel of the team's shortlisted candidates (§`../extra/problem-statements/SLOT2_CANDIDATES.md` §1) — we win on rigour, not on originality.** That reframes the deck: don't oversell the idea, oversell the verification discipline.

## 5. Goals and non-goals

**Goals**
- G1. Classify the prevailing rainfall regime for a given day/grid-cell using only forecast-time-available inputs.
- G2. Produce a bias-corrected rainfall forecast that improves on raw NWP under leave-one-monsoon-out CV, on at least RMSE and FSS.
- G3. Produce calibrated heavy/very-heavy exceedance probabilities, evaluated with a reliability diagram.
- G4. Produce a district-level rainfall table/map from the corrected grid.
- G5. Report all six named metrics against the raw-NWP baseline, honestly, including where correction does not help.
- G6. Ship a live "today" demo: pull today's open forecast, run the full pipeline, render the map.

**Non-goals (explicitly out of scope for the finale)**
- NG1. Ingesting NCMRWF's own NCUM/NEPS-G output — not public. We validate on open models (HRES, ERA5) and document an adapter interface instead.
- NG2. Real IMD gridded rainfall as ground truth, unless confirmed reachable from the team's network before the build starts (§14, §20). CHIRPS is the default truth.
- NG3. Week 3–4 or seasonal forecasting — this PS is about short/medium-range post-processing, not the extended-range problem PS26086 covers.
- NG4. Radar, lightning, or satellite nowcasting inputs — different PS, different data class.
- NG5. A general-purpose weather UI. The interface exists to demonstrate this pipeline's output, not to be a product on its own.

## 6. Users

| User | What they need from this |
|---|---|
| NCMRWF forecaster (primary, judge proxy) | A regime-aware correction they can audit: which regime was predicted, what correction was applied, what the skill scores say, including failure cases. |
| District disaster-management officer (downstream user, named in framing) | A district-level table/map: corrected rainfall and heavy-rain probability for their district, in plain units. |
| SIH judges | A working demo on today's live data, a named baseline, and six real numbers — not a static mockup. |

## 7. Domain primer and glossary

- **NWP** — Numerical Weather Prediction; the raw physics-based forecast we are correcting (HRES/IFS in this build; NCUM operationally, not accessible to us).
- **Active / break monsoon** — the standard oscillation of the Indian monsoon: active spells have above-normal rainfall over the core monsoon zone (central India); break spells have below-normal rainfall there. Defined operationally via a normalized rainfall-anomaly index over the core monsoon zone, sustained over multiple days.
- **Monsoon depression** — an organized low-pressure system (IMD classifies by sustained wind speed: depression 17–27 kt, deep depression 28–33 kt) that produces concentrated heavy rainfall; tracked historically in IBTrACS.
- **Orographic rainfall** — rainfall enhanced by terrain forcing air upward (Western Ghats windward slopes, Himalayan foothills/terai belt); a standing weakness of coarse-grid NWP.
- **Western disturbance** — an extratropical trough moving in from the Mediterranean/West Asia, primarily a winter/pre-monsoon phenomenon, relevant here mainly at monsoon onset/withdrawal.
- **MJO** — Madden–Julian Oscillation; an intraseasonal (30–60 day) tropical convection pattern, tracked via the RMM (Real-time Multivariate MJO) index, that modulates monsoon active/break cycles.
- **Quantile mapping (QM)** — a bias-correction method that maps the forecast's empirical CDF onto the truth's empirical CDF, so that a forecast value at the p-th percentile is replaced by the truth value at the same percentile.
- **RMSE, ETS, CSI, POD, FAR, FSS** — see §17.1 for exact formulas; these are the PS's own named scorecard.
- **Leave-one-monsoon-out CV** — cross-validation where each fold holds out one entire June–September season, training on the rest; the only split that does not leak within-season autocorrelation into the test set.

---
---

# Part II — The build contract

## 8. Architecture

```
                         ┌─────────────────────────┐
  ERA5 / HRES (WB2) ────▶│ 1. Ingestion            │
  CHIRPS 2.0        ────▶│    India domain slice   │
  IBTrACS           ────▶│                         │
  MJO RMM index     ────▶└──────────┬──────────────┘
                                     ▼
                         ┌─────────────────────────┐
                         │ 2. Regime labelling      │  (historical/training only)
                         │  active/break index,     │
                         │  depression flag,        │
                         │  static orographic/      │
                         │  coastal masks           │
                         └──────────┬──────────────┘
                                     ▼
                         ┌─────────────────────────┐
                         │ 3. Regime classifier     │  forecast-time features only
                         │    (multi-class GBM)     │  → regime probabilities
                         └──────────┬──────────────┘
                                     ▼
                ┌────────────────────┴────────────────────┐
                ▼                                          ▼
   ┌─────────────────────────┐              ┌─────────────────────────┐
   │ 4. Per-regime quantile   │              │ 5. Exceedance model      │
   │    mapping correction    │              │    (heavy / very-heavy   │
   │                          │              │    GBM classifiers)      │
   └──────────┬──────────────┘              └──────────┬───────────────┘
              └───────────────────┬─────────────────────┘
                                   ▼
                         ┌─────────────────────────┐
                         │ 6. District aggregation  │
                         └──────────┬──────────────┘
                                     ▼
                         ┌─────────────────────────┐
                         │ 7. Verification module   │  RMSE/ETS/CSI/POD/FAR/FSS
                         │    (vs raw-NWP baseline) │  reliability diagrams
                         └──────────┬──────────────┘
                                     ▼
                    ┌────────────────────────────────┐
                    │ 8. API (FastAPI)                │
                    └──────────────┬──────────────────┘
                                     ▼
                    ┌────────────────────────────────┐
                    │ 9. Frontend (MapLibre, Field    │
                    │    Atlas design system)         │
                    └────────────────────────────────┘
```

Stages 1–2 run once, offline, over the historical record to build training data. Stages 3–7 run both in training/backtest mode and in live "today" mode against the latest open forecast. Stage 9 reuses the SatQuery (PS26167) frontend pattern — see `../167/` — for the MapLibre setup and the Field Atlas visual language (see `docs/PPT_BRIEF.md` §Design).

## 9. Functional requirements

| ID | Requirement |
|---|---|
| FR-1 | The system shall classify each forecast grid-cell/day into one of {active, break, depression, coastal, orographic, other} using only inputs available at forecast issue time. |
| FR-2 | The classifier shall output a probability distribution over regimes, not a hard label only. |
| FR-3 | The system shall apply a regime-conditioned quantile-mapping correction to raw NWP rainfall, selected by the classifier's most probable regime (or a probability-weighted blend, §10.2). |
| FR-4 | The system shall output calibrated exceedance probabilities for IMD heavy (≥64.5 mm/day) and very-heavy (≥124.5 mm/day) rainfall thresholds. |
| FR-5 | The system shall aggregate corrected rainfall and exceedance probabilities to Indian district polygons and expose both a table and a choropleth map. |
| FR-6 | The system shall compute RMSE, ETS, CSI, POD, FAR and FSS (at ≥2 neighbourhood scales) for both the raw-NWP baseline and the corrected output, under leave-one-monsoon-out CV. |
| FR-7 | The system shall support a "live" mode: pull the latest available open forecast (HRES or GFS), run the full pipeline, and render current-day output without retraining. |
| FR-8 | The interface shall let a user toggle between raw and corrected rainfall, and between regime layers, on the same map. |
| FR-9 | Every rendered number (skill score, probability, corrected value) shall be traceable to a run artefact on disk — no number typed directly into the frontend or deck. |

## 10. Algorithms in detail

### 10.1 Regime classifier

- **Labels (training only, retrospective):**
  - Active/break: normalized rainfall-anomaly index over the core monsoon zone (central India box), computed from CHIRPS/ERA5, thresholded at ±1σ, requiring persistence over multiple consecutive days (standard active/break convention).
  - Depression: day/location flagged from IBTrACS North Indian Ocean basin tracks (depression-strength or higher, within an event radius).
  - Coastal / orographic: static geography masks (distance-to-coast, elevation/terrain-slope from a DEM) applied independent of the day's weather.
  - Precedence order when multiple labels apply on the same cell/day: depression > orographic > coastal > active/break > other (a depression signal dominates the local error characteristics regardless of the background monsoon phase).
- **Inference features (forecast-time only, no leakage):** forecast rainfall field itself, 850 hPa wind (low-level jet strength/direction) from the forecast, moisture flux convergence, MJO RMM phase and amplitude (public, updated daily, available well ahead of the forecast), static terrain/coastal masks, day-of-year/season.
- **Model:** gradient-boosted trees (multi-class), one model for all regimes; a rule-based override forces the static coastal/orographic mask regardless of classifier output in those geographies, since those labels don't need to be learned.
- **Output:** a probability vector over regimes per grid-cell/day.

### 10.2 Regime-conditioned bias correction

- **Method:** empirical quantile mapping, fit separately per regime per season, on historical (forecast, truth) rainfall pairs within that regime's labelled days.
- **Correction rule:** for a new forecast value, take the classifier's regime probabilities; either (a) apply the single most-probable regime's QM curve (simpler, the default), or (b) apply a probability-weighted blend across the top-2 regimes' QM curves (more robust near regime transitions — a stretch goal, not required for the acceptance bar in §19).
- **Truth series:** CHIRPS 2.0 daily 5 km (default); switch to IMD gridded rainfall if confirmed reachable (§14, open question in §20).
- **Known limitation to disclose:** quantile mapping assumes a stationary forecast-truth relationship within a regime; a regime with few historical days (e.g. depression) has a noisier empirical CDF. Report the sample count behind every QM curve.

### 10.3 Heavy-rainfall exceedance model

- **Model:** gradient-boosted binary classifier, one per threshold (heavy, very-heavy), predicting P(truth rainfall ≥ threshold | forecast features, regime probabilities).
- **Features:** raw and corrected forecast rainfall, regime probability vector, terrain/coastal masks, day-of-year.
- **Calibration:** isotonic or Platt scaling fit on a held-out fold; report a reliability diagram (§17), not just AUC.

### 10.4 District aggregation

- **Boundaries:** public Indian district polygons (GADM level-2 or Survey of India equivalent, whichever the team can source and redistribute legally by build day — flag in §20 if unresolved).
- **Method:** area-weighted mean of the corrected grid and the exceedance probabilities over each district polygon; report both the mean and the max grid-cell value inside the district (a district-mean can hide a localized heavy-rain cell).

## 11. Data model and artefact schemas

Every pipeline run writes to `runs/<run_id>/` (mirrors the pattern in `../143/mvp/`):

```
runs/<run_id>/
  manifest.json          # run date, forecast source, truth source, git commit, seed
  regime_probs.nc         # grid × time × regime probability
  corrected_rainfall.nc   # grid × time, bias-corrected
  exceedance_probs.nc     # grid × time × {heavy, very_heavy}
  district_table.csv      # district_id, date, corrected_mean, corrected_max, p_heavy, p_very_heavy
  verification_report.json  # RMSE/ETS/CSI/POD/FAR/FSS, per fold and pooled, baseline vs corrected
  reliability_diagram.png
```

`manifest.json` records enough to reproduce the run byte-for-byte given the same input archive snapshot: forecast issue date, truth dataset + version, regime classifier model hash, QM curve set version, random seed.

## 12. API contract

FastAPI, following the SatQuery (`../167/`) backend pattern.

| Endpoint | Method | Returns |
|---|---|---|
| `/runs/{run_id}/regime` | GET | Regime probability grid for the run, as GeoJSON or PNG overlay |
| `/runs/{run_id}/rainfall?variant=raw\|corrected` | GET | Rainfall grid, either variant |
| `/runs/{run_id}/exceedance/{threshold}` | GET | Exceedance probability grid (`heavy` \| `very_heavy`) |
| `/runs/{run_id}/districts` | GET | District table (JSON), matches `district_table.csv` |
| `/runs/{run_id}/verification` | GET | The verification report JSON |
| `/runs/live` | POST | Triggers a live run against today's open forecast; returns a `run_id` |

## 13. Interface specification

Two views, one page, reusing the Field Atlas visual language (light, globe/map-first, no dark techy chrome — see `docs/PPT_BRIEF.md`):

1. **Map view.** India basemap (MapLibre). Layer toggle: regime (categorical colour by cell), raw rainfall, corrected rainfall, heavy/very-heavy exceedance probability. A raw-vs-corrected slider or side-by-side split. District boundaries overlaid; click a district for its table row.
2. **Scorecard panel.** The six metrics, baseline vs corrected, as a small bar/table pair — this is the panel a judge should be able to read in five seconds and see the honest delta (§20 — do not hide a metric that doesn't improve).

---
---

# Part III — Execution

## 14. Data sources

| Source | What | Access | Status |
|---|---|---|---|
| WeatherBench2 `gs://weatherbench2` (ERA5) | Reanalysis truth 1959–2022, large-scale fields for regime features | Public zarr, no login | Confirmed reachable (25 Sep) |
| WeatherBench2 `hres` | IFS HRES deterministic forecast 2016–2022, 0.25° | Public zarr | Confirmed reachable |
| CHIRPS 2.0 daily, 0.05° (~5 km) | Default rainfall truth for verification and QM fitting | Open HTTPS | Confirmed reachable |
| IBTrACS | Historical depression/cyclone tracks, North Indian Ocean basin | Open HTTPS/CSV | Confirmed reachable |
| BOM/NOAA MJO RMM index | Daily MJO phase and amplitude | Open, public | Confirmed reachable |
| NOAA GFS (AWS Open Data) | Live forecast for the "today" demo | Open S3 | Confirmed reachable |
| IMD gridded rainfall | Higher-fidelity India-specific truth (preferred over CHIRPS if available) | Unconfirmed from this network | **Open question, §20** — try again from the team's network before the build |
| District boundaries (GADM / Survey of India) | For §10.4 aggregation | Public, licence varies | Confirm redistribution terms before shipping in the repo |

## 15. Stack and rejected alternatives

- **Backend:** FastAPI + xarray/zarr for gridded data, same as SatQuery's pattern — reuse rather than reinvent (§4, team-capacity argument in `../extra/problem-statements/SLOT2_CANDIDATES.md` §2).
- **ML:** gradient-boosted trees (LightGBM or XGBoost) for both the regime classifier and the exceedance models — tabular-scale, trains in minutes on a laptop or Kaggle, no GPU dependency. *Rejected:* a deep model (CNN/U-Net) on the gridded fields — no accuracy case for it at this data volume and it burns build hours the verification work needs instead.
- **Bias correction:** empirical quantile mapping — closed-form, auditable, explainable to a judge in one sentence. *Rejected:* a learned correction network — harder to explain "why this correction" to an MoES panel, and the PS explicitly frames this as classify-then-correct, not end-to-end learning.
- **Frontend:** MapLibre GL, reusing `../167/`'s web workstation scaffolding and the Field Atlas design system (light theme, globe-first, no dashboard-dark chrome — `docs/PPT_BRIEF.md` has the full rationale).

## 16. Non-functional requirements

- NFR-1. **Determinism.** A run with a fixed manifest (same input snapshot, same seed) reproduces identical outputs.
- NFR-2. **No fabricated numbers.** Every skill score, probability or corrected value shown anywhere (interface or deck) must trace to a `verification_report.json` or a run artefact. This is the same discipline `../143/` encoded as a repo-level test; replicate it here (§19).
- NFR-3. **Runtime budget.** A full pipeline run against one live forecast (stages 3–8, no retraining) should complete in well under a minute on a laptop — this is the "today" demo, and it must not stall in front of judges.
- NFR-4. **Honest degradation.** If the corrected output does not beat raw NWP on a given metric/regime, the verification report and the deck say so, rather than omitting that row.

## 17. Validation and metrics

### 17.1 The six named metrics (exact definitions)

Let hits (H), misses (M), false alarms (FA), correct negatives (CN) be counted per rain/no-rain or threshold-exceedance contingency table, and let $\hat{r}$ = forecast rainfall, $r$ = truth rainfall, over $n$ points.

- **RMSE** = $\sqrt{\frac{1}{n}\sum (\hat r - r)^2}$ — continuous accuracy, computed on the corrected vs raw grid against truth.
- **POD** (Probability of Detection) = $H / (H + M)$.
- **FAR** (False Alarm Ratio) = $FA / (H + FA)$.
- **CSI** (Critical Success Index / Threat Score) = $H / (H + M + FA)$.
- **ETS** (Equitable Threat Score) = $(H - H_{random}) / (H + M + FA - H_{random})$, where $H_{random} = (H+M)(H+FA)/n$ — corrects CSI for hits expected by chance.
- **FSS** (Fractions Skill Score) — computed over a spatial neighbourhood of radius $r$: compare the fraction of exceedance within each neighbourhood in forecast vs truth, at ≥2 radii (e.g. 25 km, 50 km), so a forecast that is spatially close but not pixel-perfect still scores well. This is the metric that rewards "right event, near-right place" rather than penalizing every displacement as a total miss.

All six are computed **both** for the raw-NWP baseline and for the corrected output, at both the heavy and very-heavy thresholds, and reported side by side — the delta is the actual claim.

### 17.2 Cross-validation

Leave-one-monsoon-out: for each historical June–September season available in the training window, hold that season out entirely, fit the regime classifier / QM curves / exceedance model on the rest, evaluate on the held-out season. Report metrics per fold and pooled. This is the only split that doesn't leak a monsoon's own autocorrelated rainfall into its own training fold.

### 17.3 Calibration

Reliability diagram (predicted exceedance probability bucket vs observed frequency) for the heavy and very-heavy exceedance models, on the pooled leave-one-monsoon-out predictions.

## 18. Build order, phases, team

Team on this PS: everyone except Mridul (PS26081). Assume roughly four to five people, none pre-committed as the dedicated modeler — the techniques in §10 are deliberately tabular-scale (gradient-boosted trees, empirical quantile mapping) so they don't require a specialist to execute, unlike a deep-learning approach would.

| Phase | Work | Depends on |
|---|---|---|
| 0. Data check (before the 36-hour clock starts, if allowed) | Confirm CHIRPS + WeatherBench2 pulls; confirm which WB2 models actually carry a precipitation variable; retry IMD gridded rainfall from the team's network; source district boundaries and check licence | — |
| 1. Regime labelling + features | Build the historical active/break index, depression flags from IBTrACS, static masks | Phase 0 |
| 2. Regime classifier | Train and validate FR-1/FR-2 | Phase 1 |
| 3. Bias correction | Fit per-regime QM curves (FR-3) | Phase 1, parallel with Phase 2 |
| 4. Exceedance model | Train heavy/very-heavy classifiers (FR-4) | Phase 2, 3 |
| 5. District aggregation | FR-5 | Phase 3, 4 |
| 6. Verification module | All six metrics, leave-one-monsoon-out (FR-6) | Phase 2–5 |
| 7. API + frontend | FR-7, FR-8, FR-9 | Phase 6 producing real numbers to render |
| 8. Live demo wiring | Pull today's GFS/HRES, run end-to-end | Phase 7 |
| 9. Deck | Pull real numbers from `verification_report.json` into the slides; see `docs/PPT_BRIEF.md` | Phase 6 onward, in parallel |

This build order puts the verification module (Phase 6) before the interface (Phase 7) deliberately — the interface exists to display real numbers, not to be built first and filled in later with placeholders that risk becoming the numbers actually shown.

## 19. Acceptance criteria

- AC-1. The regime classifier produces a probability vector for every forecast grid-cell/day using only forecast-time features (no truth leakage) — verified by a unit test that asserts the feature set excludes any truth-derived column.
- AC-2. The corrected forecast's RMSE and FSS are reported against the raw-NWP baseline under leave-one-monsoon-out CV, for at least one full historical monsoon season.
- AC-3. All six named metrics appear in `verification_report.json`, computed for both baseline and corrected, at both thresholds.
- AC-4. The live-mode pipeline runs end-to-end against a real, freshly pulled forecast and renders on the map without manual intervention.
- AC-5. No number in the frontend or the deck is hand-typed; every one traces to a run artefact (grep-able test, following `../143/`'s pattern).
- AC-6. If correction does not improve a given metric/regime, `verification_report.json` and the deck state that plainly.

## 20. Risk register and open questions

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| IMD gridded rainfall unreachable from the team's network | Medium | Low | CHIRPS is the default truth; IMD is an upgrade, not a dependency. |
| Not every WeatherBench2 model variant carries a usable precipitation variable | Medium | Medium | Check before build day (Phase 0); HRES is the fallback forecast source regardless. |
| District boundary licence/redistribution terms unclear | Low | Medium | Resolve in Phase 0; GADM is the fallback if Survey of India data can't be redistributed. |
| Bias-correction gain is small (a few % RMSE) and looks unimpressive on a headline slide | High | Medium | Lean the pitch on the regime-conditioning story and the honest FSS/reliability results, not a big single number (§4, §20 disclosure norm). |
| Least novel of the team's shortlisted candidates — a judge may see this as "textbook" | Medium | Medium | Win on rigour: full six-metric suite, leave-one-monsoon-out CV, calibration diagram — most teams will not build all of this. |
| Regime classifier's depression class is rare in the historical record (few labelled days) → noisy QM curve | Medium | Medium | Report the sample count behind every regime's QM curve; disclose low-confidence regimes rather than hide them. |
| Team lacks a dedicated modeller for this PS (Mridul is on PS26081) | Medium | Medium | All ML in §10 is tabular-scale gradient boosting and empirical QM — deliberately chosen to not require deep-learning expertise. |

**Open questions**
- [ ] Confirm IMD gridded rainfall reachability from the team's network before the build.
- [ ] Confirm which WeatherBench2 precipitation variables exist per model (HRES vs others).
- [ ] Confirm district boundary source and licence.
- [ ] Confirm SIH 2026 rules on pre-build data/model preparation (same open question as `../extra/problem-statements/SLOT2_CANDIDATES.md` §5).
- [ ] Decide whether the probability-weighted QM blend (§10.2b) is worth the build time, or whether the single-most-probable-regime version is the whole finale scope.
