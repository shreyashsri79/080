export type Regime = 'active' | 'break' | 'depression' | 'coastal' | 'orographic' | 'other'
export type Threshold = 'heavy' | 'very_heavy'
export type MetricKey = 'rmse' | 'ets' | 'csi' | 'pod' | 'far' | 'fss_25km' | 'fss_50km'
export type FieldLayer = 'raw' | 'corrected' | 'p_heavy' | 'p_very_heavy' | 'regime' | 'wind850'

export interface Manifest {
  synthetic: boolean
  run_id: string
  forecast_issue_date: string
  forecast_source: string
  truth_source: string
  grid_step_deg: number
  unit: string
  thresholds_mm: Record<Threshold, number>
  fss_radii_km: number[]
  regime_days: Record<Regime, number>
  depression_track: { lead: number; lat: number; lon: number }[]
  wettest: {
    lead: number; valid_date: string; lat: number; lon: number
    raw_mm: number; corrected_mm: number; p_heavy: number; p_very_heavy: number; regime: Regime
  }
}

export interface Grid {
  synthetic: boolean
  lat0: number; lon0: number; step: number; nlat: number; nlon: number
  regimes: Regime[]
  leads: { index: number; valid_date: string; lead_hours: number }[]
  layers: {
    raw: (number | null)[][]; corrected: (number | null)[][]
    p_heavy: (number | null)[][]; p_very_heavy: (number | null)[][]
    regime: number[][]; u850: number[][]; v850: number[][]; wind850: number[][]
  }
  regime_probs_pct: number[][]
}

export interface PlaceLead {
  raw_mm: number; corrected_mm: number; p_heavy: number; p_very_heavy: number
  regime: Regime; regime_probs: Record<Regime, number>; qm_curve: string; qm_curve_days: number
}
export interface Place { name: string; lat: number; lon: number; cell: { lat: number; lon: number }; leads: PlaceLead[] }

export type Scores = Record<MetricKey, number>
export interface VerificationEntry {
  fold: string; threshold: Threshold; regime?: Regime
  baseline: Scores; corrected: Scores; n_samples: number
  regime_sample_counts?: Record<Regime, number>
}
export interface Verification {
  synthetic: boolean; cv: string
  entries: VerificationEntry[]
  reliability: Record<Threshold, { p_forecast: number; p_observed: number; n: number }[]>
}

export interface QmCurve {
  regime: Regime | 'global'; id: string; n_days: number
  quantiles: number[]; forecast_mm: number[]; truth_mm: number[]
}

export interface Run {
  manifest: Manifest; grid: Grid; places: Place[]; verification: Verification | null
  curves: QmCurve[]; land: GeoJSON.FeatureCollection
}
