# Backend runbook

Everything runs from the repo root with the venv: `source .venv/bin/activate` (`pip install -e '.[ml,api,live,dev]'`).

## 1. Bring in the trained model (Kaggle)

1. Kaggle notebook `STAGE = "final"` finishes → *Output* → download and unzip (or the `ps26080-models` dataset).
2. `regimerain import-kaggle ~/Downloads/ps26080-models`
   - copies `models/<model_set_id>/` (sha256-verified; a tampered set is refused), `reports/<backtest_id>/`,
     and the small files of each `cache/fold=Y/` (predictions, experts, fold model). Existing items are skipped unless `--force`.
3. `regimerain preflight` → every line PASS or WARN.

## 2. Produce runs

| Command | What | Needs |
|---|---|---|
| `regimerain run --source replay --pick wettest\|depression\|active\|break` | held-out hindcast, real IMD truth | fold caches |
| `regimerain run --source hres --init 2021-08-02 [--model-set ID]` | model set on a historical HRES init; IMD shown only if that season was held out | feature table + model set |
| `regimerain run --source gfs [--init today\|cached\|YYYY-MM-DD]` | live forecast, ~26 GRIB subsets from NOAA S3, cached under `data/raw/gfs/<date>/` | model set, internet (or cache) |
| `regimerain run --source samanvay [--init 2020-08-04]` | **interim** run from real data (Samanvay sister project): raw = ECMWF HRES member, corrected = Samanvay's out-of-sample skill-weighted blend (stand-in), regime = the day's observed label + depression around the forecast MSLP low. No --init = every June–September hindcast | internet |
| `regimerain run --source mock` | synthetic sample (not deployed) | nothing |

Add `--publish NAME` to copy a run into `mvp/web/public/run/NAME` for static hosting.

## 3. Serve the demo

```bash
cd mvp/web && npm run build && cd ../..
regimerain serve --live            # API + web on http://127.0.0.1:8000, POST /api/runs/live enabled
```

`latest` prefers model runs, then replay, then interim, then mock. Live run from the API: `curl -X POST :8000/api/runs/live`, poll `GET /api/runs/live`.

## 4. Venue fallback

- No internet: `regimerain run --source gfs --init cached` (download once the day before), or show replay runs.
- Port busy: `--port 8080`. Preflight says which.
- Model set missing/corrupt: preflight WARNs; replay runs still work (they need no model set).

## 5. Fitting locally instead of Kaggle

`regimerain backtest` → `report` → `fit-final` writes `models/<id>/` (classifier rounds = 1.1 × median fold best
iteration, T = median fold temperature, MODEL_SPEC 17). Parity of a saved fold model with its backtest is
checked by `tests/test_model.py::test_model_parity`.

## 6. Public deployment (Modal)

Live at **https://shreyashsri79--regimerain.modal.run** (web + API, `/api/docs`). App: `deploy/modal_app.py`.

- **Code or web change:** `cd mvp/web && npm run build && cd ../.. && modal deploy deploy/modal_app.py` (same URL).
- **New runs, reports or a model set:** produce them locally, then `deploy/sync.sh` (or `deploy/sync.sh runs/<run_id>`).
  They go into the `regimerain-data` Volume and appear within 30 s, with no redeploy. `latest` prefers model > replay > mock,
  so the first real run replaces the sample on the landing page automatically.
- **Live GFS runs from the site:** after a model set is synced, `modal secret create regimerain-live LIVE=1 LIVE_TOKEN=<token> --force`,
  then redeploy. Trigger with `curl -X POST -H "X-Live-Token: <token>" <url>/api/runs/live`; poll `GET /api/runs/live`.
  Without the token the endpoint returns 401, and while LIVE=0 it returns 503.
- **Check it:** `BASE=https://shreyashsri79--regimerain.modal.run CHROME=/usr/bin/google-chrome node mvp/web/tests/smoke.mjs`.
