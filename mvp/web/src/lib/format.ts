export const fmtLat = (v: number) => `${Math.abs(v).toFixed(2)}°${v >= 0 ? 'N' : 'S'}`
export const fmtLon = (v: number) => `${Math.abs(v).toFixed(2)}°${v >= 0 ? 'E' : 'W'}`
export const fmtMm = (v: number | null | undefined) => (v == null ? '—' : v.toFixed(1))
export const fmtPct = (v: number | null | undefined) => (v == null ? '—' : `${Math.round(v * 100)}%`)
export const fmtDay = (iso: string) =>
  new Date(iso + 'T00:00:00Z').toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short', timeZone: 'UTC' })
export const METRIC_META = {
  rmse: { name: 'RMSE', low: true, unit: 'mm', long: 'Root-mean-square error' },
  ets: { name: 'ETS', low: false, unit: '', long: 'Equitable threat score' },
  csi: { name: 'CSI', low: false, unit: '', long: 'Critical success index' },
  pod: { name: 'POD', low: false, unit: '', long: 'Probability of detection' },
  far: { name: 'FAR', low: true, unit: '', long: 'False alarm ratio' },
  fss_25km: { name: 'FSS 25 km', low: false, unit: '', long: 'Fractions skill score, 25 km' },
  fss_50km: { name: 'FSS 50 km', low: false, unit: '', long: 'Fractions skill score, 50 km' },
} as const
export const METRIC_KEYS = Object.keys(METRIC_META) as (keyof typeof METRIC_META)[]
export const fmtMetric = (k: keyof typeof METRIC_META, v: number) => (k === 'rmse' ? v.toFixed(1) : v.toFixed(2))
/** Display-only comparison of two report values. Returns 'better' | 'worse' | 'same'. */
export function verdict(k: keyof typeof METRIC_META, raw: number, cor: number) {
  const eps = k === 'rmse' ? 0.05 : 0.005
  const d = cor - raw
  const low = METRIC_META[k].low
  if (Math.abs(d) <= eps) return 'same' as const
  return (low ? d < 0 : d > 0) ? ('better' as const) : ('worse' as const)
}
