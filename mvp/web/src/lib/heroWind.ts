/**
 * Decorative wind for the particles while a run carries no 850 hPa wind of its own (interim runs, until
 * the model set is plugged in). Hand-built from the sister project's hero map: Gaussian patches of flow
 * that resemble the south-west monsoon season (Somali jet, Arabian Sea and Bay of Bengal monsoon flow,
 * the subtropical jet, trades), drifting vortices and a trig texture.
 *
 * NOT forecast or observed data: the page labels it as decorative wherever it is drawn.
 * Input: longitude, latitude (deg), time (s). Output: [u east, v north] in rough m/s.
 * Designed for about 40-120 E, 10 S-50 N.
 */
const g = (x: number, y: number, cx: number, cy: number, sx: number, sy: number) =>
  Math.exp(-(((x - cx) / sx) ** 2) - ((y - cy) / sy) ** 2)
const sig = (x: number) => 1 / (1 + Math.exp(-x))

type Vortex = { cx: number; cy: number; r: number; s: number; ax: number; ay: number; w: number }

// s > 0: anticlockwise
const VORTICES: Vortex[] = [
  { cx: 58, cy: 14, r: 5, s: -8, ax: 1.2, ay: 0.8, w: 0.035 },    // arcs over the Arabian Sea
  { cx: 52, cy: -3, r: 6.5, s: 10, ax: 1.5, ay: 1.0, w: 0.03 },    // Seychelles gyre
  { cx: 69, cy: 0, r: 5.5, s: -8, ax: 1.2, ay: 1.0, w: 0.04 },     // Maldives eddy
  { cx: 79, cy: -6, r: 6, s: 8, ax: 1.4, ay: 1.0, w: 0.03 },       // south of Sri Lanka
  { cx: 87.5, cy: 8, r: 4.5, s: 8, ax: 1.0, ay: 0.8, w: 0.05 },    // southern Bay swirl
  { cx: 93, cy: 14, r: 3.5, s: 6, ax: 0.8, ay: 0.6, w: 0.05 },     // Andaman Sea
  { cx: 100, cy: 1, r: 4, s: 6, ax: 0.8, ay: 0.6, w: 0.045 },      // off Sumatra
  { cx: 113, cy: 12, r: 5, s: -8, ax: 1.2, ay: 0.9, w: 0.035 },    // South China Sea
  { cx: 110, cy: -8, r: 5, s: -6, ax: 1.0, ay: 0.8, w: 0.04 },     // Java Sea
  { cx: 62, cy: 31, r: 5, s: -5, ax: 1.0, ay: 0.8, w: 0.03 },      // Iran / Afghan high
  { cx: 53, cy: 43, r: 6, s: 7, ax: 1.5, ay: 1.0, w: 0.025 },      // Caspian low
  { cx: 100, cy: 46, r: 6, s: -6, ax: 1.5, ay: 1.0, w: 0.025 },    // Mongolian high
]

// Smooth scalar "weather" texture so streak speed and direction vary like a real field.
function texture(lon: number, lat: number, t: number) {
  return (
    Math.sin(lon * 0.21 + t * 0.03) * Math.cos(lat * 0.27 - t * 0.02) +
    0.6 * Math.sin(lon * 0.47 - lat * 0.33 + t * 0.05) +
    0.35 * Math.cos(lon * 0.9 + lat * 0.7 - t * 0.07)
  )
}

export function heroWind(lon: number, lat: number, t: number): [number, number] {
  let u = 0, v = 0

  // westerlies and waves north of ~40° N
  const north = sig((lat - 40) * 0.6)
  u += 9 * north
  v += 4 * north * Math.sin((lon - 50) * 0.09 + t * 0.01)

  // sharp jet along the Kunlun / northern Tibet (~36° N), strongest 78-100° E
  const jet = g(lon, lat, 90, 36.3, 14, 1.6)
  u += 16 * jet
  v += -1.5 * jet

  // shamal: north-westerly down the Gulf and over Iran
  const shamal = g(lon, lat, 52, 27, 8, 6)
  u += 4 * shamal; v += -5 * shamal

  // Somali jet: southerly up the African coast, turning north-east into the Arabian Sea
  const coast = g(lon, lat, 47 + Math.max(0, lat) * 0.35, 4, 3.5, 8)
  u += 3 * coast; v += 12 * coast
  const turn = g(lon, lat, 56, 11, 7, 4)
  u += 10 * turn; v += 4 * turn

  // south-west monsoon: Arabian Sea into the west coast, Bay of Bengal converging on Myanmar
  const arab = g(lon, lat, 64, 13, 11, 6)
  u += 9 * arab; v += 4 * arab
  const bay = g(lon, lat, 89, 12, 8, 6)
  u += 6 * bay; v += 6 * bay
  const yangon = g(lon, lat, 95, 16, 3, 3)
  u += -2 * yangon; v += 8 * yangon

  // near-equatorial westerlies, south-east trades beyond
  const eq = g(lon, lat, 80, 2, 30, 4)
  u += 6 * eq
  const trades = sig(-(lat + 6) * 0.7) * g(lon, 0, 80, 0, 40, 1)
  u += -6 * trades; v += 3 * trades

  // South China Sea south-westerlies
  const scs = g(lon, lat, 112, 14, 7, 6)
  u += 4 * scs; v += 4 * scs

  // calm air over the Indian landmass, the Tibetan plateau interior and eastern China
  const calm = Math.min(1,
    g(lon, lat, 78.5, 21.5, 8, 9) + 0.8 * g(lon, lat, 83, 26, 9, 3) + g(lon, lat, 112, 30, 8, 6) + 0.6 * g(lon, lat, 88, 31, 7, 2))
  const damp = 1 - 0.8 * calm
  u *= damp; v *= damp
  u += calm * (-1.2 + 1.3 * texture(lon, lat, t))
  v += calm * (0.9 * texture(lat, lon, t + 40))

  // drifting vortices
  for (const k of VORTICES) {
    const cx = k.cx + k.ax * Math.sin(t * k.w), cy = k.cy + k.ay * Math.cos(t * k.w * 1.3)
    const dx = lon - cx, dy = lat - cy
    const f = (k.s * Math.exp(-(dx * dx + dy * dy) / (k.r * k.r))) / k.r
    u += -dy * f
    v += dx * f
  }

  // small-scale texture on everything
  const n = texture(lon, lat, t)
  const rot = 0.22 * n, c = Math.cos(rot), s = Math.sin(rot), m = 1 + 0.22 * n
  const speed = Math.hypot(u, v)
  return [(u * c - v * s) * m + (speed < 1 ? 0.6 * n : 0), (u * s + v * c) * m]
}
