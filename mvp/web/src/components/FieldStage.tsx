import { useEffect, useRef } from 'react'
import { makeParticles, mercY, prefersReducedMotion, renderField, gridBounds, traceLand } from '../lib/field'
import type { FieldLayer, Run } from '../lib/types'

interface Props {
  run: Run
  layer: FieldLayer
  lead: number
  /** fraction of width where 82.5°E sits (0..1) */
  anchorX?: number
  /** fraction of height where India's middle latitude sits (0..1) */
  anchorY?: number
  /** latitude span to fit into the height */
  latSpan?: [number, number]
  reveal?: boolean
  particles?: boolean
  mark?: { lat: number; lon: number } | null
  track?: boolean
  className?: string
}

/** Full-bleed static map for story pages: sea, land, the run's field, coastline, wind particles. */
const SPAN: [number, number] = [5.5, 37.5]

export function FieldStage({ run, layer, lead, anchorX = 0.5, anchorY = 0.5, latSpan = SPAN, reveal = false, particles = true, mark, track, className }: Props) {
  const base = useRef<HTMLCanvasElement>(null)
  const top = useRef<HTMLCanvasElement>(null)
  const state = useRef({ layer, lead, prev: null as HTMLCanvasElement | null, cur: null as HTMLCanvasElement | null, fade: 1, sweep: reveal ? 0 : 1 })
  const leadRef = useRef(lead)
  leadRef.current = lead

  useEffect(() => {
    const s = state.current
    const next = renderField(run.grid, run.land, layer, lead)
    if (next !== s.cur) {
      s.prev = s.cur
      s.cur = next
      s.fade = s.prev && !prefersReducedMotion() ? 0 : 1
    }
    s.layer = layer
    s.lead = lead
  }, [run, layer, lead])

  useEffect(() => {
    const cb = base.current!, ct = top.current!
    const bctx = cb.getContext('2d')!, tctx = ct.getContext('2d')!
    const reduce = prefersReducedMotion()
    const s = state.current
    if (reduce) s.sweep = 1
    const parts = makeParticles(run.grid, () => leadRef.current, 1500)
    const gb = gridBounds(run.grid)
    let W = 0, H = 0, dpr = 1, raf = 0, dirty = true, last = -1
    let proj: (lon: number, lat: number) => [number, number] = () => [0, 0]

    const resize = () => {
      const r = cb.parentElement!.getBoundingClientRect()
      dpr = Math.min(2, window.devicePixelRatio || 1)
      W = r.width; H = r.height
      for (const c of [cb, ct]) { c.width = W * dpr; c.height = H * dpr }
      const [la0, la1] = latSpan
      // fit India's height, but never wider than the screen on narrow layouts
      const kk = Math.min((H * 0.94) / (mercY(la1) - mercY(la0)), (W * 1.05) / ((33 * Math.PI) / 180))
      const yc = (mercY(la0) + mercY(la1)) / 2
      const cx = W * anchorX
      proj = (lon, lat) => [cx + ((lon - 82.5) * Math.PI / 180) * kk, H * anchorY - (mercY(lat) - yc) * kk]
      parts.reset()
      dirty = true
    }

    const drawBase = () => {
      if (W < 2 || H < 2) return
      bctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      bctx.fillStyle = '#dce5e6'
      bctx.fillRect(0, 0, W, H)
      bctx.fillStyle = '#eef0ea'
      traceLand(bctx, run.land, proj)
      bctx.fill('evenodd')
      const [x0, y0] = proj(gb.west, gb.north), [x1, y1] = proj(gb.east, gb.south)
      const drawImg = (img: HTMLCanvasElement | null, a: number) => {
        if (!img || a <= 0) return
        bctx.globalAlpha = a
        bctx.drawImage(img, x0, y0, x1 - x0, y1 - y0)
        bctx.globalAlpha = 1
      }
      if (s.sweep < 1) {
        // monsoon-style develop: the field arrives from the south-west and advances north-east
        const off = document.createElement('canvas')
        off.width = W; off.height = H
        const o = off.getContext('2d')!
        o.drawImage(s.cur!, x0, y0, x1 - x0, y1 - y0)
        const [sx, sy] = proj(70, 6), [ex, ey] = proj(96, 34)
        const gr = o.createLinearGradient(sx, sy, ex, ey)
        const p = s.sweep * 1.25
        gr.addColorStop(Math.max(0, Math.min(1, p - 0.25)), 'rgba(0,0,0,1)')
        gr.addColorStop(Math.max(0, Math.min(1, p)), 'rgba(0,0,0,0)')
        o.globalCompositeOperation = 'destination-in'
        o.fillStyle = gr
        o.fillRect(0, 0, W, H)
        bctx.drawImage(off, 0, 0, W, H)
      } else {
        drawImg(s.prev, 1 - s.fade)
        drawImg(s.cur, s.fade)
      }
      bctx.strokeStyle = 'rgba(14,26,31,0.7)'
      bctx.lineWidth = 0.8
      traceLand(bctx, run.land, proj)
      bctx.stroke()
      if (track) {
        const pts = run.manifest.depression_track
        bctx.strokeStyle = '#0e1a1f'
        bctx.setLineDash([4, 4])
        bctx.beginPath()
        pts.forEach((p, i) => { const [x, y] = proj(p.lon, p.lat); if (i) bctx.lineTo(x, y); else bctx.moveTo(x, y) })
        bctx.stroke()
        bctx.setLineDash([])
        pts.forEach((p) => {
          const [x, y] = proj(p.lon, p.lat)
          bctx.beginPath(); bctx.arc(x, y, p.lead === s.lead ? 6 : 3, 0, Math.PI * 2)
          bctx.fillStyle = p.lead === s.lead ? '#0e1a1f' : '#fff'; bctx.fill(); bctx.stroke()
        })
      }
      if (mark) {
        const [x, y] = proj(mark.lon, mark.lat)
        bctx.strokeStyle = '#0e1a1f'; bctx.lineWidth = 1.5
        bctx.beginPath(); bctx.arc(x, y, 14, 0, Math.PI * 2); bctx.stroke()
        bctx.beginPath()
        bctx.moveTo(x - 24, y); bctx.lineTo(x - 17, y); bctx.moveTo(x + 17, y); bctx.lineTo(x + 24, y)
        bctx.moveTo(x, y - 24); bctx.lineTo(x, y - 17); bctx.moveTo(x, y + 17); bctx.lineTo(x, y + 24)
        bctx.stroke()
      }
    }

    const loop = (t: number) => {
      const dt = last < 0 ? 0 : Math.max(0, Math.min(400, t - last))
      last = t
      if (s.sweep < 1) { s.sweep = Math.min(1, s.sweep + dt / 2600); dirty = true }
      if (s.fade < 1) { s.fade = Math.min(1, s.fade + dt / 450); dirty = true }
      if (dirty && s.cur && W > 1) { drawBase(); dirty = false }
      if (particles && !reduce) {
        tctx.setTransform(dpr, 0, 0, dpr, 0, 0)
        parts.step(tctx, proj, W, H)
      }
      raf = requestAnimationFrame(loop)
    }
    const ro = new ResizeObserver(resize)
    ro.observe(cb.parentElement!)
    resize()
    raf = requestAnimationFrame(loop)
    const kick = () => { dirty = true }
    const iv = setInterval(kick, 250)
    return () => { cancelAnimationFrame(raf); ro.disconnect(); clearInterval(iv) }
  }, [run, anchorX, anchorY, latSpan, particles, mark?.lat, mark?.lon, track])

  return (
    <div className={`overflow-hidden ${className ?? 'relative'}`}>
      <canvas ref={base} className="absolute inset-0 h-full w-full" aria-hidden="true" />
      <canvas ref={top} className="pointer-events-none absolute inset-0 h-full w-full" aria-hidden="true" />
    </div>
  )
}
