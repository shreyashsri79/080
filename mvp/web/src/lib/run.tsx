import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'
import { configureThresholds } from './color'
import { configureMetrics } from './format'
import { heroWind } from './heroWind'
import type { Run, RunKind } from './types'

/** One row of GET /api/runs. */
export interface RunSummary {
  run_id: string; kind: RunKind; synthetic: boolean; forecast_source: string; forecast_issue_date: string
  created_utc: string; layers: string[]; held_out_season?: number
}

/**
 * Where runs come from. With `regimerain serve` the API answers /api/health and serves every run;
 * on a static host (or `npm run dev` without a backend) runs are files under public/run/<id>/.
 * VITE_API_BASE overrides the API location.
 */
const API = (import.meta.env.VITE_API_BASE as string | undefined) ?? `${import.meta.env.BASE_URL}api`

async function apiUp(): Promise<boolean> {
  try {
    const r = await fetch(`${API}/health`, { headers: { Accept: 'application/json' } })
    // a static host answers unknown paths with index.html: that is not an API
    if (!r.ok || !(r.headers.get('content-type') ?? '').includes('json')) return false
    return (await r.json()).ok === true
  } catch {
    return false
  }
}

const get = async <T,>(url: string): Promise<T> => {
  const r = await fetch(url)
  if (!r.ok) throw new Error(`${url} returned HTTP ${r.status}`)
  return r.json() as Promise<T>
}

/** Loads one run. The UI only reads these files; it never computes a forecast or a score. */
async function loadRun(base: string, id: string): Promise<Run> {
  const geo = `${import.meta.env.BASE_URL}geo/`
  const manifest = await get<Run['manifest']>(base + 'manifest.json')
  if (manifest.contract_version !== 2)
    throw new Error(`run ${id} uses web contract v${manifest.contract_version ?? 1}; this app reads v2. Re-export it: regimerain run ... --publish ${id}`)
  // optional files are fetched only when the manifest lists them (older exports have no list: try them)
  const has = (f: string) => !manifest.files || manifest.files.includes(f)
  const [grid, places, curves, verification, land, india] = await Promise.all([
    get<Run['grid']>(base + 'grid.json'),
    get<{ places: Run['places'] }>(base + 'places.json'),
    has('qm_curves.json') ? get<{ curves: Run['curves'] }>(base + 'qm_curves.json').catch(() => ({ curves: [] })) : { curves: [] },
    has('verification.json') ? get<Run['verification']>(base + 'verification.json').catch(() => null) : null,
    get<Run['land']>(geo + 'land.json'),
    get<Run['india']>(geo + 'india.json'),
  ])
  // colour breaks, threshold labels and FSS names follow the run, never literals in the code
  configureThresholds(manifest.thresholds_mm)
  configureMetrics(verification?.fss_windows ?? [])
  // runs without their own 850 hPa wind animate a decorative flow, labelled as such on the page
  const displayWind = manifest.layers.includes('wind850') ? undefined : { label: 'decorative monsoon-season flow, not forecast data', at: heroWind }
  return { manifest, grid, places: places.places, curves: curves.curves, land, india, verification, displayWind }
}

type State = { run: Run | null; error: string | null; api: boolean; runs: RunSummary[] }
const Ctx = createContext<State>({ run: null, error: null, api: false, runs: [] })

export function RunProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<State>({ run: null, error: null, api: false, runs: [] })
  useEffect(() => {
    const asked = new URLSearchParams(location.search).get('run')
    ;(async () => {
      if (await apiUp()) {
        const runs = await get<RunSummary[]>(`${API}/runs`)
        // an API with no runs yet (fresh checkout) falls through to the bundled sample
        if (asked || runs.length) {
          const id = asked ?? (await get<{ run_id: string }>(`${API}/runs/latest`)).run_id
          return { run: await loadRun(`${API}/runs/${encodeURIComponent(id)}/`, id), api: true, runs }
        }
      }
      const id = asked ?? 'sample'
      return { run: await loadRun(`${import.meta.env.BASE_URL}run/${encodeURIComponent(id)}/`, id), api: false, runs: [] }
    })().then(
      ({ run, api, runs }) => setState({ run, error: null, api, runs }),
      (e: Error) => setState((s) => ({ ...s, run: null, error: e.message })),
    )
  }, [])
  return <Ctx.Provider value={state}>{children}</Ctx.Provider>
}

export const useRunState = () => useContext(Ctx)
export function useRun(): Run {
  const { run } = useContext(Ctx)
  if (!run) throw new Error('useRun called before the run loaded')
  return run
}
