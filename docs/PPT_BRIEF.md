# PPT brief — Regime-Aware Rainfall Post-Processing (SIH26080)

For whoever builds the slide deck. Everything here is sourced from `../PRD.md` and `../TECHNICAL_SPEC.md` — read those for the full reasoning; this is the distilled, deck-ready version. Do not invent a number that isn't in this document or in a `runs/<run_id>/verification_report.json` once the build exists.

## The one line

**Most bias-correction systems fit one curve to every day of the year. We fit one curve per weather regime, predict the regime from the forecast itself, and only then correct — so the correction sharpens on the events that cost the most: heavy and very heavy rainfall.**

## Why this problem statement, in one breath

MoES/NCMRWF wrote a PS that names its own scorecard — RMSE, ETS, CSI, POD, FAR, FSS. That's rare among the 240 statements on the portal. It tells you exactly what the judges (atmospheric scientists) will ask for: real skill numbers against a named baseline, not a dashboard on made-up data. This is the PS where showing up with six real metrics, honestly reported, beats a flashier idea with no verification behind it.

## The problem, for a slide with no jargon

Weather forecasts for rainfall are wrong in different ways on different kinds of days:
- During an **active monsoon spell**, the model errs one way.
- During a **break spell** (rainfall dries up), it errs another way.
- During a **depression** (a tracked low-pressure storm system), it badly under- or mis-places heavy rain.
- Near mountains (**orographic** rain, e.g. Western Ghats) and near the **coast**, the model has its own standing blind spots.

Today's forecast correction tools apply one fix, everywhere, all the time — which means it's never quite right for the day that matters most. We tell the system what kind of day it's forecasting *first*, then apply the fix built for that kind of day.

## The three claims (deck spine — one slide each)

1. **Classify before you correct.** A single global bias-correction curve washes out exactly the structure — regime differences — that determines whether a correction helps or hurts. We predict the regime from forecast-time information only (so it works operationally, not just in hindsight), then apply a correction fitted specifically to that regime.
2. **We report the scorecard the problem statement asked for, not the one that flatters us.** RMSE, ETS, CSI, POD, FAR, FSS — all six, for both the raw forecast and our corrected output, under a leave-one-monsoon-out test (the only split that doesn't let one season's rainfall leak into its own training data). Where correction doesn't help, the report says so.
3. **The output is a district table an official can act on**, not just a scientist's plot — corrected rainfall and a heavy-rain probability, per district, on a map.

## What NOT to oversell

This is, by the team's own admission, the least novel of the candidates that were shortlisted (see `../../extra/problem-statements/SLOT2_CANDIDATES.md` §1: "least novel of the top three: bias correction by regime is a known idea"). Regime-conditioned bias correction is a known technique in the meteorology literature. **The win is rigour, not invention.** Do not write a slide that claims a "novel AI breakthrough." Write one that says: most teams will not build all six named metrics under a leaky-proof split, and we did.

Typical bias-correction skill gains are small — a few percent in RMSE, not a dramatic before/after. **Do not headline a big number that isn't real.** Lean the pitch on:
- the regime-conditioning story (a judge can ask "what regime is today?" and get a real, falsifiable answer),
- the FSS and reliability-diagram results (reward near-right forecasts, which is the honest way to show skill on rare heavy-rain events),
- and an explicit "here's where it didn't help" moment — that is what separates a credible team from one presenting cherry-picked numbers.

## Data credibility slide — what to say when asked "where's your data from"

| Claim | Source | Say this |
|---|---|---|
| Raw forecast being corrected | ECMWF HRES via WeatherBench2 (public zarr) | "A real operational-grade global forecast, not a toy dataset." |
| Ground truth for verification | CHIRPS 2.0, 5 km daily, satellite+gauge blended | "The same product used in operational rainfall verification research; upgrading to IMD gridded rainfall if reachable." |
| Depression tracking | IBTrACS (WMO-affiliated best-track archive) | "The standard historical record for tropical/monsoon low-pressure systems." |
| MJO index | BOM/NOAA RMM index | "The standard intraseasonal oscillation index used operationally by forecasters worldwide." |
| Live demo forecast | NOAA GFS open data (AWS) | "Today's actual forecast, pulled live, not pre-recorded." |

**What we don't have, and say plainly:** NCMRWF's own operational model output (NCUM/NEPS-G) is not public. We validate against open models and describe an adapter for NCUM rather than pretending to have run on it.

## Demo script (for the live segment)

1. Show today's date, pull the live GFS/HRES forecast for India on stage.
2. Show the regime map: "here's what the model thinks is happening today — active monsoon over X, a depression flagged near Y."
3. Toggle raw vs corrected rainfall on the map.
4. Toggle to the heavy-rain exceedance layer; click a district; show the table row.
5. Show the scorecard panel: six metrics, baseline vs corrected, from a real historical backtest — not from today's single run (today's run has no truth yet to score against; say this explicitly if asked).

## Judging-criteria mapping (for a "why should this place" slide if wanted)

- **Technical depth:** regime classifier + per-regime quantile mapping + calibrated exceedance model — three real, connected ML components, not one model doing everything.
- **Rigour:** the PS's own six-metric scorecard, computed under leave-one-monsoon-out CV, against a named baseline.
- **Usability:** district-level table/map output — the stated downstream user (a district disaster-management officer) can read a number and act.
- **Honesty:** disclosed limitations (small gains typical of bias correction, sparse-regime noise, no NCUM access) presented up front, not extracted under questioning.

## Design direction for the slides and any live UI

Reuse the **Field Atlas** visual language established for SatQuery (PS26167): light theme throughout, map/globe-first hero framing, no dark dashboard chrome. Not the editorial/"Zara" look — this is an operational tool for forecasters and district officials, and the deck should read that way: clean, data-forward, credible, not stylised. If the live demo reuses SatQuery's MapLibre frontend scaffolding (`../167/`), keep the same colour system so the deck and the demo don't visually clash.

## Team / roles slide

- PS26080 (this one) — built by the team excluding Mridul, who is building PS26081 (Hybrid AI–NWP forecast blending) in parallel. Both share the same India-domain open-data pipeline (WeatherBench2, CHIRPS) but are independent builds and independent PS submissions — don't conflate them on a slide, they answer different PS numbers.
- If asked why two weather PS at once: both were selected from the same live-submission-count ranking exercise (`../../extra/problem-statements/SLOT2_CANDIDATES.md`) after the team's original slot 1 (SatQuery/PS26167) and slot 2 (Dark Transit/PS26143) both closed to new registration.

## What's still open (don't promise these on a slide until resolved)

- Whether IMD gridded rainfall (better truth than CHIRPS) is reachable from the team's network — if not confirmed by build day, the deck should say CHIRPS throughout, not IMD.
- Exact district-boundary source/licence for the map — resolve before showing a district map with an uncleared data source's watermark or terms.
- Whether the probability-weighted regime blend (PRD §10.2b) makes it into the build, or the simpler single-regime version is what's shown — say only what actually shipped.
