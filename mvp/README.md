# RegimeRain MVP

Frontend first. It renders a run folder; it never computes a forecast or a metric. Plan: `../docs/FRONTEND_BUILD_PLAN.md`.

```
mvp/
  tools/make_sample_run.py     writes a SYNTHETIC run + coastline for UI work (numpy only)
  web/                         React + TS + Vite app
    public/run/<run_id>/       manifest.json, grid.json, places.json, qm_curves.json, verification.json
    public/geo/land.json       Natural Earth land, coastline only
    src/pages/                 Landing, Forecast (map workstation), Scorecard, Method, Bulletin
    tests/smoke.mjs            headless checks via data-testid
```

## Run

```bash
cd mvp/web
npm install
npm run sample            # writes the synthetic run (once, or after editing the generator)
npm run dev               # http://localhost:5173
```

Production check:

```bash
npm run build && npm run preview &     # http://localhost:4173
CHROME=/usr/bin/google-chrome npm run smoke
```

Works offline after `npm install`: fonts, MapLibre and data are all local. `?run=<run_id>` loads another run folder.

## Pages

| Route | What it shows |
|---|---|
| `/` | Hero rainfall field with 850 hPa wind particles, the run's wettest point at display scale, pipeline story on a pinned map, where correction did not help, headline scores |
| `/forecast` | Ventusky-style map: layer rail (rain, regime, heavy, very heavy, wind), raw / corrected / compare swipe, lead-day timeline with play, legend, hover value, place labels, depression track, point panel with correction trace |
| `/scorecard` | Six metrics raw vs corrected, per season, per regime (worse in red), QM curves, reliability |
| `/method` | Models, data sources and access state, known limits |
| `/bulletin` | Print-styled place table for a lead day |

Keyboard on the map: Shift+←/→ changes lead day, Esc closes the point panel, arrows move the compare handle.

## Contract with the pipeline

The `regimerain` pipeline writes the same files per run into `web/public/run/<run_id>/` (later served by the API, PRD §12). Types are in `web/src/lib/types.ts`.

- `manifest.json`: run metadata, thresholds, `depression_track`, `wettest` point. `synthetic: true` shows the banner; real runs set `false`.
- `grid.json`: regular lat/lon grid, rows south to north. Per lead day: `raw`, `corrected`, `p_heavy`, `p_very_heavy` (null over sea), `regime` (index, −1 over sea), `u850`, `v850`, `wind850`; plus `regime_probs_pct` (6 per cell).
- `places.json`: named places, nearest land cell, values per lead day, QM curve id and its sample count.
- `qm_curves.json`: per-regime and global quantile curves with `n_days`.
- `verification.json`: `entries` per fold × threshold (pooled, per season, per regime) and `reliability` bins.

## Known gaps

- Sample values, including every score, are invented. The banner, bulletin and footer say so.
- The sample grid is 0.5°; the spec's working grid is 0.25°. The UI reads the step from the run.
- District polygons wait on the boundary licence (PRD §20). Places stand in.
- No backend yet (`POST /runs/live`).
