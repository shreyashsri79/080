import type { Regime } from './types'

export type Stop = [number, string]

/** Rain ramp, mm/day. 64.5 and 124.5 are IMD's heavy and very-heavy thresholds: the colour class changes there. */
export const RAIN: Stop[] = [
  [0, '#eef0ea'], [1, '#dfeaf8'], [5, '#b7d3f6'], [15, '#86b6ef'], [35, '#3987e5'],
  [64.5, '#1c5cab'], [124.5, '#4a3aa7'], [200, '#2a1c6e'],
]
export const PROB: Stop[] = [
  [0, '#f6efe8'], [0.1, '#fde4d6'], [0.3, '#f9c0a2'], [0.5, '#f39866'], [0.7, '#eb6834'], [0.85, '#c24f1f'], [1, '#8f3712'],
]
export const WIND: Stop[] = [[0, '#eef0ea'], [4, '#d5e7df'], [8, '#9fd1bd'], [12, '#4fb08c'], [16, '#1b8a67'], [22, '#0d5a43']]

/** Validated with the dataviz palette validator (adjacent pairs pass; labels always accompany colour). */
export const REGIME: Record<Regime, { color: string; label: string; desc: string }> = {
  active: { color: '#1baf7a', label: 'Active', desc: 'Above-normal rain over the core monsoon zone' },
  break: { color: '#eda100', label: 'Break', desc: 'Rain dries up over the core monsoon zone' },
  depression: { color: '#e34948', label: 'Depression', desc: 'Low-pressure system, concentrated heavy rain' },
  coastal: { color: '#2a78d6', label: 'Coastal', desc: 'Near-coast convection, its own error pattern' },
  orographic: { color: '#4a3aa7', label: 'Orographic', desc: 'Terrain-forced rain: Ghats, Himalayan foothills' },
  other: { color: '#9aa5a6', label: 'Other', desc: 'No specific regime flagged' },
}
export const REGIME_ORDER: Regime[] = ['active', 'break', 'depression', 'coastal', 'orographic', 'other']

const hex = (h: string) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16))
const cache = new Map<Stop[], number[][]>()

export function rampRGB(stops: Stop[], v: number): number[] {
  let rgb = cache.get(stops)
  if (!rgb) cache.set(stops, (rgb = stops.map((s) => hex(s[1]))))
  if (v <= stops[0][0]) return rgb[0]
  for (let i = 1; i < stops.length; i++) {
    if (v <= stops[i][0]) {
      const t = (v - stops[i - 1][0]) / (stops[i][0] - stops[i - 1][0])
      const a = rgb[i - 1], b = rgb[i]
      return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t]
    }
  }
  return rgb[rgb.length - 1]
}
export const regimeRGB = (i: number) => hex(REGIME[REGIME_ORDER[i]].color)
