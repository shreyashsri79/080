import { PROB, RAIN, REGIME_ORDER, WIND, rampRGB, regimeRGB, type Stop } from './color'
import type { FieldLayer, Grid } from './types'

export const mercY = (lat: number) => Math.log(Math.tan(Math.PI / 4 + (lat * Math.PI) / 360))
export const invMercY = (y: number) => (360 / Math.PI) * Math.atan(Math.exp(y)) - 90

/** Outer edges of the data grid, in degrees. */
export function gridBounds(g: Grid) {
  const h = g.step / 2
  return { west: g.lon0 - h, east: g.lon0 + (g.nlon - 1) * g.step + h, south: g.lat0 - h, north: g.lat0 + (g.nlat - 1) * g.step + h }
}

/** Value of the nearest grid cell (what the hover readout and point panel show: a run value, not an interpolation). */
export function cellAt(g: Grid, lat: number, lon: number) {
  const i = Math.round((lat - g.lat0) / g.step), j = Math.round((lon - g.lon0) / g.step)
  if (i < 0 || j < 0 || i >= g.nlat || j >= g.nlon) return null
  return { i, j, idx: i * g.nlon + j, lat: g.lat0 + i * g.step, lon: g.lon0 + j * g.step }
}

export function stopsFor(layer: FieldLayer): Stop[] {
  if (layer === 'raw' || layer === 'corrected') return RAIN
  if (layer === 'wind850') return WIND
  return PROB
}

/** Bilinear sample for drawing only; ignores null (sea) corners. */
function bilinear(arr: (number | null)[], g: Grid, fi: number, fj: number): number | null {
  const i0 = Math.floor(fi), j0 = Math.floor(fj)
  const ti = fi - i0, tj = fj - j0
  let s = 0, w = 0
  for (const [di, dj, ww] of [[0, 0, (1 - ti) * (1 - tj)], [0, 1, (1 - ti) * tj], [1, 0, ti * (1 - tj)], [1, 1, ti * tj]] as const) {
    const i = Math.min(g.nlat - 1, Math.max(0, i0 + di)), j = Math.min(g.nlon - 1, Math.max(0, j0 + dj))
    const v = arr[i * g.nlon + j]
    if (v != null && ww > 0) { s += v * ww; w += ww }
  }
  return w > 0.05 ? s / w : null
}

export type Land = GeoJSON.FeatureCollection

/** Traces land polygons onto ctx given a lon/lat -> pixel projector. */
export function traceLand(ctx: CanvasRenderingContext2D, land: Land, project: (lon: number, lat: number) => [number, number]) {
  ctx.beginPath()
  for (const f of land.features) {
    const g = f.geometry as GeoJSON.Polygon
    for (const ring of g.coordinates) {
      ring.forEach(([x, y], k) => {
        const [px, py] = project(x, y)
        if (k === 0) ctx.moveTo(px, py)
        else ctx.lineTo(px, py)
      })
      ctx.closePath()
    }
  }
}

const imgCache = new Map<string, HTMLCanvasElement>()

/**
 * Draws one layer of one lead day to a canvas whose rows are linear in Web Mercator Y,
 * so MapLibre can place it as an image source without distortion. Clipped to land.
 */
export function renderField(g: Grid, land: Land, layer: FieldLayer, lead: number, scale = 8): HTMLCanvasElement {
  const key = `${layer}:${lead}:${scale}`
  const hit = imgCache.get(key)
  if (hit) return hit
  const b = gridBounds(g)
  const W = g.nlon * scale
  const y0 = mercY(b.north), y1 = mercY(b.south)
  const H = Math.round(W * ((y0 - y1) / ((b.east - b.west) * Math.PI / 180)))
  const c = document.createElement('canvas')
  c.width = W; c.height = H
  const ctx = c.getContext('2d')!
  const img = ctx.createImageData(W, H)
  const isRegime = layer === 'regime'
  const arr = isRegime ? null : (g.layers[layer][lead] as (number | null)[])
  const reg = g.layers.regime[lead]
  const stops = stopsFor(layer)
  const lowCut = layer === 'raw' || layer === 'corrected' ? 4 : layer === 'wind850' ? 1 : 0.06
  for (let py = 0; py < H; py++) {
    const lat = invMercY(y0 - ((py + 0.5) / H) * (y0 - y1))
    const fi = (lat - g.lat0) / g.step
    for (let px = 0; px < W; px++) {
      const lon = b.west + ((px + 0.5) / W) * (b.east - b.west)
      const fj = (lon - g.lon0) / g.step
      let rgb: number[] | null = null
      let lowV = 1
      if (isRegime) {
        const i = Math.round(fi), j = Math.round(fj)
        if (i >= 0 && j >= 0 && i < g.nlat && j < g.nlon) {
          const r = reg[i * g.nlon + j]
          if (r >= 0) rgb = regimeRGB(r)
          if (r === REGIME_ORDER.indexOf('other')) lowV = 0.18 // "other" is a fold bucket: keep it faint
        }
      } else {
        const v = bilinear(arr!, g, fi, fj)
        if (v != null) { rgb = rampRGB(stops, v); lowV = v }
      }
      if (!rgb) continue
      // dry cells stay unpainted (the land shows through), and the field fades out at the grid edge
      const edge = Math.min(1, Math.min(lon - b.west, b.east - lon, lat - b.south, b.north - lat) / 3)
      const a = edge * (isRegime ? lowV : Math.min(1, lowV / lowCut))
      const o = (py * W + px) * 4
      img.data[o] = rgb[0]; img.data[o + 1] = rgb[1]; img.data[o + 2] = rgb[2]; img.data[o + 3] = Math.round(255 * a)
    }
  }
  ctx.putImageData(img, 0, 0)
  if (layer !== 'wind850') {
    ctx.globalCompositeOperation = 'destination-in'
    ctx.fillStyle = '#000'
    traceLand(ctx, land, (lon, lat) => [((lon - b.west) / (b.east - b.west)) * W, ((y0 - mercY(lat)) / (y0 - y1)) * H])
    ctx.fill('evenodd')
    ctx.globalCompositeOperation = 'source-over'
  }
  imgCache.set(key, c)
  return c
}

/* ------------------------------------------------------------ wind particles */

export interface Particles {
  step(ctx: CanvasRenderingContext2D, project: (lon: number, lat: number) => [number, number], w: number, h: number): void
  reset(): void
}

/** Particles advected by the run's 850 hPa wind (u east, v north, m/s). Motion here *is* the data. */
export function makeParticles(g: Grid, lead: () => number, count = 1400, color = 'rgba(14,26,31,0.45)'): Particles {
  const b = gridBounds(g)
  type P = { lon: number; lat: number; age: number; max: number }
  const spawn = (p?: P): P => {
    const q = p ?? ({} as P)
    q.lon = b.west + Math.random() * (b.east - b.west)
    q.lat = b.south + Math.random() * (b.north - b.south)
    q.age = 0
    q.max = 40 + Math.random() * 60
    return q
  }
  let ps: P[] = Array.from({ length: count }, () => { const p = spawn(); p.age = Math.random() * p.max; return p })
  const wind = (lat: number, lon: number): [number, number] => {
    const L = lead()
    const fi = (lat - g.lat0) / g.step, fj = (lon - g.lon0) / g.step
    return [bilinear(g.layers.u850[L], g, fi, fj) ?? 0, bilinear(g.layers.v850[L], g, fi, fj) ?? 0]
  }
  const K = 0.0065
  return {
    reset() { ps = ps.map((p) => spawn(p)) },
    step(ctx, project, w, h) {
      ctx.globalCompositeOperation = 'destination-in'
      ctx.fillStyle = 'rgba(0,0,0,0.9)'
      ctx.fillRect(0, 0, w, h)
      ctx.globalCompositeOperation = 'source-over'
      ctx.strokeStyle = color
      ctx.lineWidth = 1.1
      ctx.lineCap = 'round'
      ctx.beginPath()
      for (const p of ps) {
        const [u, v] = wind(p.lat, p.lon)
        const [x0, y0] = project(p.lon, p.lat)
        p.lon += (u * K) / Math.cos((p.lat * Math.PI) / 180)
        p.lat += v * K
        p.age++
        const [x1, y1] = project(p.lon, p.lat)
        if (p.age > p.max || p.lon < b.west || p.lon > b.east || p.lat < b.south || p.lat > b.north || Math.hypot(u, v) < 0.4) {
          spawn(p)
          continue
        }
        if (x1 < -20 || y1 < -20 || x1 > w + 20 || y1 > h + 20) continue
        ctx.moveTo(x0, y0)
        ctx.lineTo(x1, y1)
      }
      ctx.stroke()
    },
  }
}

export const prefersReducedMotion = () => typeof matchMedia !== 'undefined' && matchMedia('(prefers-reduced-motion: reduce)').matches
