import { useInView } from 'motion/react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { Footer, Nav } from '../components/Chrome'
import { FieldStage } from '../components/FieldStage'
import { Marquee } from '../components/Marquee'
import { NumberTicker } from '../components/NumberTicker'
import { FadeUp, RevealLines } from '../components/Reveal'
import { MetricBars, QmChart, VerdictTag } from '../components/charts'
import { REGIME, REGIME_ORDER } from '../lib/color'
import { METRIC_KEYS, METRIC_META, fmtDay, fmtLat, fmtLon, fmtMetric, verdict } from '../lib/format'
import { useRun } from '../lib/run'
import type { FieldLayer, MetricKey, Regime } from '../lib/types'

const VOCAB = ['RMSE', 'ETS', 'CSI', 'POD', 'FAR', 'FSS 25 km', 'FSS 50 km', 'heavy ≥ 64.5 mm/day', 'very heavy ≥ 124.5 mm/day',
  '0.25° grid', 'CHIRPS 2.0 · 0.05°', 'IFS HRES', 'ERA5', 'IBTrACS', 'MJO RMM', 'leave-one-monsoon-out', 'EPSG:4326', 'June–September']

export default function Landing() {
  const run = useRun()
  const { manifest: m, verification: ver, grid } = run
  const w = m.wettest
  const [wide, setWide] = useState(() => matchMedia('(min-width: 900px)').matches)
  useEffect(() => {
    const q = matchMedia('(min-width: 900px)')
    const f = () => setWide(q.matches)
    q.addEventListener('change', f)
    return () => q.removeEventListener('change', f)
  }, [])
  const mark = useMemo(() => ({ lat: w.lat, lon: w.lon }), [w.lat, w.lon])
  const heavy = ver?.entries.find((e) => e.fold === 'pooled' && e.threshold === 'heavy' && !e.regime)

  return (
    <main data-testid="landing">
      {/* ---------------------------------------------------------------- hero: the forecast is the headline */}
      <section className="relative h-[calc(100svh_-_30px)] min-h-[640px] overflow-hidden">
        <FieldStage run={run} layer="corrected" lead={w.lead} anchorX={wide ? 0.7 : 0.5} anchorY={wide ? 0.5 : 0.3} reveal particles mark={mark} className="absolute inset-0" />
        <Nav over />
        <div className="pointer-events-none absolute inset-x-0 bottom-0 grid gap-6 px-5 pb-8 md:px-8 lg:grid-cols-[1.25fr_1fr] lg:items-end">
          <div>
            <p className="eyebrow mb-4"><span className="tape">SIH26080 · MoES / NCMRWF · Regime-aware rainfall post-processing</span></p>
            <h1 className="display text-[length:clamp(56px,9.5vw,172px)]">
              <RevealLines lines={['Classify', 'first.', 'Correct', 'second.'].map((w) => <span className="tape">{w}</span>)} delay={0.3} />
            </h1>
          </div>
          <div className="lg:justify-self-end lg:text-right" data-testid="hero-telemetry">
            <p className="eyebrow mb-2"><span className="tape">Wettest point in this run · corrected</span></p>
            <div className="num text-[length:clamp(56px,9vw,168px)] font-medium leading-[0.9] tracking-[-0.05em]">
              <span className="tape tape-ink"><NumberTicker value={w.corrected_mm} decimals={1} duration={2.2} /></span>
            </div>
            <div className="num mt-2 flex flex-wrap gap-1.5 text-[clamp(14px,1.4vw,20px)] lg:justify-end">
              <span className="tape">mm/day</span>
              <span className="tape">raw {w.raw_mm.toFixed(1)}</span>
              <span className="tape">{fmtLat(w.lat)} {fmtLon(w.lon)}</span>
              <span className="tape">P(heavy) {Math.round(w.p_heavy * 100)}%</span>
              <span className="tape" style={{ boxShadow: `inset 4px 0 0 ${REGIME[w.regime].color}`, paddingLeft: '0.5em' }}>{REGIME[w.regime].label}</span>
              <span className="tape">{fmtDay(w.valid_date)} · +{grid.leads[w.lead].lead_hours} h</span>
            </div>
          </div>
        </div>
        <Link to="/forecast" className="tape tape-ink absolute right-5 top-16 hidden rounded-[3px] md:inline-block px-3 py-2 text-[14px] font-medium no-underline md:right-8">Open the forecast map →</Link>
      </section>

      {/* ---------------------------------------------------------------- vocabulary strip */}
      <div className="border-y border-ink bg-ink py-3 font-mono text-[13px] tracking-wide text-paper">
        <Marquee seconds={55}>
          {VOCAB.map((v) => <span key={v} className="flex items-center gap-10 whitespace-nowrap">{v}<span className="text-[#5d7077]">/</span></span>)}
        </Marquee>
      </div>

      {/* ---------------------------------------------------------------- the problem */}
      <section className="px-5 py-24 md:px-8 md:py-32">
        <div className="grid gap-12 lg:grid-cols-[1fr_1.1fr]">
          <h2 className="display text-[length:var(--section)]">
            <RevealLines lines={['Rain forecasts', 'go wrong in', 'different ways', 'on different days.']} />
          </h2>
          <FadeUp className="self-end">
            <p className="max-w-[46ch] text-[18px] leading-[1.55] text-ink-2">
              Most correction tools fit one curve to every day of the year. That curve is never right for the day that matters. We name the kind of day first, from the forecast itself, then apply the curve built for it.
            </p>
          </FadeUp>
        </div>
        <ul className="mt-16 border-t border-ink">
          {REGIME_ORDER.filter((r) => r !== 'other').map((r, i) => (
            <FadeUp key={r} delay={i * 0.05}>
              <li className="grid items-baseline gap-x-8 gap-y-1 border-b border-rule py-5 md:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)_auto]">
                <span className="flex items-baseline gap-4">
                  <span className="inline-block h-[0.55em] w-[0.55em] shrink-0 rounded-[3px] text-[length:clamp(32px,5vw,72px)]" style={{ background: REGIME[r].color }} aria-hidden="true" />
                  <span className="display text-[length:clamp(32px,5vw,72px)]">{REGIME[r].label}</span>
                </span>
                <span className="text-[16px] text-ink-2">{REGIME[r].desc}</span>
                <span className="num text-[13px] text-ink-2">{m.regime_days[r].toLocaleString()} training days</span>
              </li>
            </FadeUp>
          ))}
        </ul>
      </section>

      {/* ---------------------------------------------------------------- the pipeline, on a pinned map */}
      <Pipeline />

      {/* ---------------------------------------------------------------- honesty */}
      {ver && <WhereItDidNotHelp />}

      {/* ---------------------------------------------------------------- numbers band */}
      {heavy && (
        <section className="border-t border-ink px-5 py-24 md:px-8">
          <div className="flex flex-wrap items-baseline justify-between gap-4">
            <h2 className="display text-[length:var(--section)]"><RevealLines lines={['Six scores, raw', 'against corrected.']} /></h2>
            <p className="eyebrow">Heavy rain · pooled over held-out seasons{m.synthetic && ' · sample values'}</p>
          </div>
          <div className="mt-14 grid gap-x-8 gap-y-12 sm:grid-cols-2 lg:grid-cols-4">
            {(['fss_50km', 'pod', 'ets', 'rmse'] as MetricKey[]).map((k) => {
              const a = heavy.baseline[k], b = heavy.corrected[k]
              return (
                <FadeUp key={k}>
                  <div className="border-t-2 border-ink pt-3">
                    <div className="flex items-baseline justify-between"><span className="font-display text-[22px] font-extrabold tracking-tight">{METRIC_META[k].name}</span><VerdictTag v={verdict(k, a, b)} /></div>
                    <div className="num mt-4 text-[length:clamp(56px,6.5vw,104px)] font-medium leading-none tracking-[-0.05em]">
                      <NumberTicker value={b} from={a} decimals={k === 'rmse' ? 1 : 2} duration={1.8} />
                    </div>
                    <div className="num mt-2 text-[13px] text-ink-2">from {fmtMetric(k, a)} raw · {METRIC_META[k].long.toLowerCase()}</div>
                  </div>
                </FadeUp>
              )
            })}
          </div>
          <Link to="/scorecard" className="mt-14 inline-block text-[15px] font-medium text-accent">All six metrics, per regime and per season →</Link>
        </section>
      )}

      {/* ---------------------------------------------------------------- close */}
      <section className="relative overflow-hidden border-t border-ink">
        <FieldStage run={run} layer="p_heavy" lead={Math.min(grid.leads.length - 1, 2)} anchorX={wide ? 0.72 : 0.5} particles track className="absolute inset-0 opacity-90" />
        <div className="relative px-5 py-28 md:px-8 md:py-40">
          <Link to="/forecast" className="group no-underline" data-testid="cta-forecast">
            <span className="display block text-[length:var(--hero)] text-ink">
              <span className="tape">Open the</span><br /><span className="tape">forecast map</span>{' '}
              <span className="tape tape-ink inline-block transition-transform duration-300 group-hover:translate-x-3">→</span>
            </span>
          </Link>
          <div className="mt-8 flex flex-wrap gap-2 text-[15px]">
            <Link to="/scorecard" className="tape font-medium text-accent">Read the scorecard</Link>
            <Link to="/method" className="tape font-medium text-accent">How it works</Link>
            <Link to="/bulletin" className="tape font-medium text-accent">Print the bulletin</Link>
          </div>
        </div>
      </section>
      <Footer />
    </main>
  )
}

/* ------------------------------------------------------------------ scroll narrative */

const STEPS: { layer: FieldLayer; title: string; body: string }[] = [
  { layer: 'raw', title: 'Start from the raw forecast.', body: 'Daily rainfall from an open global model, clipped to India on a 0.25° grid. This is what forecasters get today.' },
  { layer: 'regime', title: 'Name the kind of day.', body: 'A gradient-boosted classifier reads only what is known when the forecast is issued: the forecast rain, 850 hPa wind, moisture flux, MJO phase, terrain and coast. It gives a probability for each regime, per cell.' },
  { layer: 'corrected', title: 'Correct with that day’s curve.', body: 'Each regime has its own quantile-mapping curve, fitted on past days of that regime only. The tail is extrapolated, not clipped, so heavy rain keeps its size.' },
  { layer: 'p_heavy', title: 'Say how likely heavy rain is.', body: 'A calibrated model gives the chance of reaching IMD’s heavy (64.5 mm) and very heavy (124.5 mm) thresholds.' },
  { layer: 'corrected', title: 'Score it against the truth.', body: 'Every season is held out in turn. RMSE, ETS, CSI, POD, FAR and FSS are reported for raw and corrected, including where correction made things worse.' },
]

function Step({ i, onActive, children }: { i: number; onActive: (i: number) => void; children: React.ReactNode }) {
  const ref = useRef<HTMLDivElement>(null)
  const inView = useInView(ref, { margin: '-45% 0px -45% 0px' })
  useEffect(() => { if (inView) onActive(i) }, [inView, i, onActive])
  return <div ref={ref} className="flex min-h-[80vh] flex-col justify-center py-16">{children}</div>
}

function Pipeline() {
  const run = useRun()
  const [active, setActive] = useState(0)
  const heavy = run.verification?.entries.find((e) => e.fold === 'pooled' && e.threshold === 'heavy' && !e.regime)
  const lead = run.manifest.wettest.lead
  return (
    <section className="relative border-t border-ink" aria-label="How the pipeline works">
      <div className="grid lg:grid-cols-[1.15fr_1fr]">
        <div className="sticky top-0 h-[55vh] lg:h-svh">
          <FieldStage run={run} layer={STEPS[active].layer} lead={lead} anchorX={0.5} particles={active !== 1} className="relative h-full w-full" />
          <div className="absolute left-4 top-4 flex flex-col gap-1">
            <span className="eyebrow"><span className="tape">Layer shown</span></span>
            <span className="num text-[15px]"><span className="tape tape-ink">{STEPS[active].layer === 'p_heavy' ? 'P(heavy)' : STEPS[active].layer}</span></span>
          </div>
          {active === 1 && (
            <ul className="absolute bottom-4 left-4 flex max-w-[90%] flex-wrap gap-1 text-[12.5px]">
              {REGIME_ORDER.map((r) => <li key={r} className="tape flex items-center gap-1.5"><span className="inline-block h-2.5 w-2.5 rounded-[2px]" style={{ background: REGIME[r].color }} />{REGIME[r].label}</li>)}
            </ul>
          )}
        </div>
        <div className="px-5 md:px-10">
          {STEPS.map((s, i) => (
            <Step key={i} i={i} onActive={setActive}>
              <p className="num text-[13px] text-ink-2">Step {i + 1} of {STEPS.length}</p>
              <h3 className="display mt-3 text-[length:clamp(34px,4.2vw,64px)]">{s.title}</h3>
              <p className="mt-5 max-w-[44ch] text-[17px] leading-[1.6] text-ink-2">{s.body}</p>
              {i === 2 && (
                <div className="mt-8 max-w-[480px] rounded-[4px] border border-rule bg-surface p-4">
                  <QmChart curves={run.curves} show={['global', 'depression', 'break']} height={260} />
                </div>
              )}
              {i === 4 && heavy && (
                <div className="mt-8 max-w-[520px] rounded-[4px] border border-rule bg-surface p-4">
                  <MetricBars entry={heavy} keys={['rmse', 'pod', 'far', 'fss_50km']} />
                </div>
              )}
            </Step>
          ))}
        </div>
      </div>
    </section>
  )
}

/* ------------------------------------------------------------------ where it did not help */

function WhereItDidNotHelp() {
  const { verification: ver, manifest } = useRun()
  const worse = ver!.entries
    .filter((e) => e.fold === 'pooled' && e.regime)
    .flatMap((e) => METRIC_KEYS.filter((k) => verdict(k, e.baseline[k], e.corrected[k]) === 'worse').map((k) => ({ e, k, rel: Math.abs(e.corrected[k] - e.baseline[k]) / Math.max(1e-6, Math.abs(e.baseline[k])) })))
    .sort((a, b) => b.rel - a.rel)
  const total = ver!.entries.filter((e) => e.fold === 'pooled' && e.regime).length * METRIC_KEYS.length
  if (!worse.length) return null
  const top = worse[0]
  const reg = top.e.regime as Regime
  return (
    <section className="border-t border-ink bg-surface px-5 py-24 md:px-8" data-testid="did-not-help">
      <p className="eyebrow">Where it did not help{manifest.synthetic && ' · sample values'}</p>
      <div className="mt-6 grid gap-10 lg:grid-cols-[1.3fr_1fr] lg:items-end">
        <h2 className="display text-[length:var(--section)]">
          <RevealLines lines={[`${REGIME[reg].label} spells:`, `${METRIC_META[top.k].name} got worse.`]} />
        </h2>
        <FadeUp>
          <div className="num text-[length:clamp(48px,6vw,96px)] font-medium leading-none tracking-[-0.04em] text-worse">
            {fmtMetric(top.k, top.e.baseline[top.k])} → {fmtMetric(top.k, top.e.corrected[top.k])}
          </div>
          <p className="mt-4 max-w-[46ch] text-[16px] text-ink-2">
            {worse.length} of {total} regime-and-metric results got worse after correction. They stay on the scorecard in red, not in a footnote.
          </p>
          <Link to="/scorecard" className="mt-4 inline-block font-medium text-accent">See every regime →</Link>
        </FadeUp>
      </div>
    </section>
  )
}
