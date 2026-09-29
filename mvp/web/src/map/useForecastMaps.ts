import * as maplibregl from 'maplibre-gl'
type MLMap = maplibregl.Map
import 'maplibre-gl/dist/maplibre-gl.css'
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url'
import { useEffect, useRef, useState } from 'react'
import { gridBounds, renderField } from '../lib/field'
import type { FieldLayer, Run } from '../lib/types'

maplibregl.setWorkerUrl(workerUrl)

const urlCache = new WeakMap<HTMLCanvasElement, string>()
const toUrl = (c: HTMLCanvasElement) => {
  let u = urlCache.get(c)
  if (!u) urlCache.set(c, (u = c.toDataURL()))
  return u
}
const FIELD_OPACITY = 0.9
const INDIA: [[number, number], [number, number]] = [[67.5, 6], [97.5, 36.5]]

function trackGeo(run: Run): GeoJSON.FeatureCollection {
  const pts = run.manifest.depression_track
  return {
    type: 'FeatureCollection',
    features: [
      { type: 'Feature', properties: {}, geometry: { type: 'LineString', coordinates: pts.map((p) => [p.lon, p.lat]) } },
      ...pts.map((p) => ({ type: 'Feature' as const, properties: { lead: p.lead }, geometry: { type: 'Point' as const, coordinates: [p.lon, p.lat] } })),
    ],
  }
}

export function createMap(container: HTMLElement, run: Run, first: FieldLayer, lead: number): MLMap {
  const b = gridBounds(run.grid)
  const coords: [[number, number], [number, number], [number, number], [number, number]] = [[b.west, b.north], [b.east, b.north], [b.east, b.south], [b.west, b.south]]
  const url = toUrl(renderField(run.grid, run.land, first, lead))
  const map = new maplibregl.Map({
    container,
    bounds: INDIA,
    fitBoundsOptions: { padding: { top: 70, bottom: 110, left: 90, right: 40 } },
    minZoom: 2.8,
    maxZoom: 8.5,
    maxBounds: [[40, -8], [112, 46]],
    dragRotate: false,
    pitchWithRotate: false,
    renderWorldCopies: false,
    attributionControl: { compact: true, customAttribution: 'Coastline: Natural Earth (public domain)' },
    style: {
      version: 8,
      sources: {
        land: { type: 'geojson', data: run.land },
        fieldA: { type: 'image', url, coordinates: coords },
        fieldB: { type: 'image', url, coordinates: coords },
        track: { type: 'geojson', data: trackGeo(run) },
      },
      layers: [
        { id: 'sea', type: 'background', paint: { 'background-color': '#dce5e6' } },
        { id: 'land', type: 'fill', source: 'land', paint: { 'fill-color': '#eef0ea' } },
        { id: 'fieldA', type: 'raster', source: 'fieldA', paint: { 'raster-opacity': FIELD_OPACITY, 'raster-fade-duration': 0, 'raster-resampling': 'linear', 'raster-opacity-transition': { duration: 420, delay: 0 } } },
        { id: 'fieldB', type: 'raster', source: 'fieldB', paint: { 'raster-opacity': 0, 'raster-fade-duration': 0, 'raster-resampling': 'linear', 'raster-opacity-transition': { duration: 420, delay: 0 } } },
        { id: 'coast', type: 'line', source: 'land', paint: { 'line-color': '#0e1a1f', 'line-width': ['interpolate', ['linear'], ['zoom'], 3, 0.6, 7, 1.4], 'line-opacity': 0.75 } },
        { id: 'track-line', type: 'line', source: 'track', filter: ['==', ['geometry-type'], 'LineString'], paint: { 'line-color': '#0e1a1f', 'line-width': 1.5, 'line-dasharray': [2, 2] } },
        { id: 'track-pt', type: 'circle', source: 'track', filter: ['==', ['geometry-type'], 'Point'], paint: { 'circle-radius': 4, 'circle-color': '#ffffff', 'circle-stroke-color': '#0e1a1f', 'circle-stroke-width': 1.5 } },
      ],
    },
  })
  map.touchZoomRotate.disableRotation()
  ;(map as MLMap & { _field?: { active: 'A' | 'B'; key: string } })._field = { active: 'A', key: `${first}:${lead}` }
  return map
}

/** Crossfades the field to a new layer/lead using the two image sources. */
export function setField(map: MLMap, run: Run, layer: FieldLayer, lead: number) {
  const st = (map as MLMap & { _field?: { active: 'A' | 'B'; key: string } })._field!
  const key = `${layer}:${lead}`
  if (st.key === key || !map.isStyleLoaded()) return
  st.key = key
  const next = st.active === 'A' ? 'B' : 'A'
  const url = toUrl(renderField(run.grid, run.land, layer, lead))
  const img = new Image()
  img.src = url
  img.decode().then(() => {
    if (st.key !== key) return
    const b = gridBounds(run.grid)
    ;(map.getSource(`field${next}`) as maplibregl.ImageSource).updateImage({ url, coordinates: [[b.west, b.north], [b.east, b.north], [b.east, b.south], [b.west, b.south]] })
    requestAnimationFrame(() => requestAnimationFrame(() => {
      if (st.key !== key) return
      map.setPaintProperty(`field${next}`, 'raster-opacity', FIELD_OPACITY)
      map.setPaintProperty(`field${st.active}`, 'raster-opacity', 0)
      st.active = next
    }))
  })
}

export function setTrack(map: MLMap, lead: number, visible: boolean) {
  if (!map.isStyleLoaded()) return
  for (const id of ['track-line', 'track-pt']) map.setLayoutProperty(id, 'visibility', visible ? 'visible' : 'none')
  map.setPaintProperty('track-pt', 'circle-radius', ['case', ['==', ['get', 'lead'], lead], 7, 3.5])
  map.setPaintProperty('track-pt', 'circle-color', ['case', ['==', ['get', 'lead'], lead], '#0e1a1f', '#ffffff'])
}

/** Two synced maps (main + compare). Returns refs and a ready flag. */
export function useForecastMaps(run: Run, a: React.RefObject<HTMLDivElement | null>, b: React.RefObject<HTMLDivElement | null>, first: FieldLayer, lead: number) {
  const maps = useRef<{ A: MLMap | null; B: MLMap | null }>({ A: null, B: null })
  const [ready, setReady] = useState(false)
  useEffect(() => {
    const A = createMap(a.current!, run, first, lead)
    const B = createMap(b.current!, run, 'corrected', lead)
    maps.current = { A, B }
    let syncing = false
    const link = (from: MLMap, to: MLMap) => from.on('move', () => {
      if (syncing) return
      syncing = true
      to.jumpTo({ center: from.getCenter(), zoom: from.getZoom() })
      syncing = false
    })
    link(A, B)
    link(B, A)
    let n = 0
    const done = () => { if (++n === 2) setReady(true) }
    A.once('load', done)
    B.once('load', done)
    return () => { A.remove(); B.remove(); maps.current = { A: null, B: null }; setReady(false) }
    // maps are created once per run; layer/lead changes go through setField
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [run])
  return { maps, ready }
}
