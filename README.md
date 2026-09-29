# SIH26080 — Regime-Aware Rainfall Post-Processing

**Build an AI/ML system that identifies the prevailing monsoon rainfall regime, then applies a regime-specific bias correction to raw NWP rainfall forecasts.**
Ministry of Earth Sciences (MoES) / NCMRWF · Software · Smart Automation.

Rainfall forecast errors are not uniform: they behave differently in active monsoon, break monsoon, depressions, orographic and coastal settings, and near western disturbances. One global bias-correction curve averages that structure away. We classify the regime first — from forecast-time information only, so it's deployable — then apply a correction fitted to that regime, and report the PS's own named scorecard (RMSE, ETS, CSI, POD, FAR, FSS) against raw NWP, honestly, under a leave-one-monsoon-out split.

**Most teams will detect and correct with one model. We tell the model what kind of day it's forecasting first — and we report all six metrics the problem statement actually asked for.**

## What is here

```
PRD.md                    product requirements — what and why (§1-20)
TECHNICAL_SPEC.md         engineering spec — data contracts, modules, CLI, tests
docs/PS26080_Brief.md     the original problem-statement text, verbatim
docs/PPT_BRIEF.md         deck-ready narrative, claims, demo script, for the PPT team
```

No MVP exists yet at time of writing (29 Sep 2026) — this is the pre-build planning set. `PRD.md` §18 has the build-phase order; `TECHNICAL_SPEC.md` §7 has the proposed CLI once a `regimerain` package exists, mirroring `../143/`'s structure.

## Status

Selected 29 Sep 2026 alongside PS26081 (built separately by Mridul) to replace the team's two closed slots — PS26143 (Dark Transit, 500/500) and PS26167 (SatQuery, filled). Selection rationale and the live submission-count comparison against seven other candidates: `../extra/problem-statements/SLOT2_CANDIDATES.md`.

Built by the team excluding Mridul. Every algorithm in this plan (gradient-boosted trees, empirical quantile mapping) was chosen to be tabular-scale and not require a dedicated ML specialist — see `PRD.md` §18 and §20.
