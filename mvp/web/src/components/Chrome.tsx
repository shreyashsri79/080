import { NavLink, Link } from 'react-router-dom'
import { useRun, useRunState } from '../lib/run'
import type { Run } from '../lib/types'

/** Whether a run gets the thin strip above the page (the forecast map subtracts its height). */
export const hasRunStrip = (m: Run['manifest']) => m.kind === 'replay' || m.kind === 'interim'

/** Says what kind of run is on screen: replay and interim runs get a strip; model and sample runs don't
 * (a sample run is still marked "sample values" beside its scores, in the method state and the bulletin). */
export function RunBanner() {
  const { manifest } = useRun()
  const { api, runs } = useRunState()
  if (!hasRunStrip(manifest)) return null
  const picker = api && runs.length > 1 && (
    <select aria-label="Run" value={manifest.run_id} onChange={(e) => { location.search = `?run=${encodeURIComponent(e.target.value)}` }}
      className="ml-3 max-w-[40vw] cursor-pointer rounded-[3px] border border-current/30 bg-transparent px-1 py-0.5 font-mono text-[11px]">
      {runs.map((r) => <option key={r.run_id} value={r.run_id}>{r.kind === 'interim' ? 'forecast' : r.kind} · {r.forecast_issue_date}{r.held_out_season ? ` · held out ${r.held_out_season}` : ''}</option>)}
    </select>
  )
  if (manifest.kind === 'interim')
    return (
      <div data-testid="interim-banner" className="no-print relative z-50 flex h-[30px] items-center justify-center overflow-hidden whitespace-nowrap bg-[#dfeaec] px-4 text-center font-mono text-[11.5px] tracking-wide text-ink">
        <span className="truncate sm:hidden">Forecast of {manifest.forecast_issue_date} · interim correction</span>
        <span className="hidden truncate sm:inline">
          Forecast issued {manifest.forecast_issue_date} · ECMWF HRES, corrected by a skill-weighted multi-model blend until the regime-aware model is trained
        </span>
        {picker}
      </div>
    )
  const season = manifest.provenance.held_out_season
  return (
    <div data-testid="replay-banner" className="no-print relative z-50 flex h-[30px] items-center justify-center overflow-hidden whitespace-nowrap bg-[#dfeaec] px-4 text-center font-mono text-[11.5px] tracking-wide text-ink">
      <span className="truncate sm:hidden">Hindcast · {manifest.forecast_issue_date}{season ? ` · ${season} held out` : ''}</span>
      <span className="hidden truncate sm:inline">
        Hindcast issued {manifest.forecast_issue_date}{season ? `. The ${season} season was held out of training` : ''}; compared with {manifest.truth_source ?? 'observed rain'}.
      </span>
      {picker}
    </div>
  )
}

const LINKS = [
  ['/forecast', 'Forecast map'],
  ['/scorecard', 'Scorecard'],
  ['/method', 'Method'],
  ['/bulletin', 'Bulletin'],
] as const

export function Nav({ over = false }: { over?: boolean }) {
  return (
    <header className={`no-print z-40 flex items-center gap-6 px-5 py-3 md:px-8 ${over ? 'absolute inset-x-0 top-0' : 'sticky top-0 border-b border-rule bg-paper/90 backdrop-blur'}`}>
      <Link to="/" className="flex items-center gap-2 bg-paper px-1.5 py-0.5 text-ink no-underline">
        <Drop />
        <span className="font-display text-[19px] font-extrabold tracking-[-0.03em]">RegimeRain</span>
      </Link>
      <nav className="ml-auto flex flex-wrap items-center gap-1" aria-label="Main">
        {LINKS.map(([to, label]) => (
          <NavLink key={to} to={to}
            className={({ isActive }) => `tape rounded-[3px] px-2.5 py-1 text-[13.5px] font-medium no-underline transition-colors ${isActive ? 'tape-ink' : 'text-ink hover:text-accent'}`}>
            {label}
          </NavLink>
        ))}
      </nav>
    </header>
  )
}

export function Drop({ size = 18 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden="true">
      <circle cx="16" cy="16" r="14" fill="none" stroke="#0e1a1f" strokeWidth="2.5" />
      <path d="M16 6c-4 6-7 9.5-7 13a7 7 0 0 0 14 0c0-3.5-3-7-7-13z" fill="#1c5cab" />
    </svg>
  )
}

export function Footer() {
  const { manifest } = useRun()
  return (
    <footer className="no-print border-t border-rule px-5 py-8 text-[13px] text-ink-2 md:px-8">
      <div className="flex flex-wrap items-baseline gap-x-8 gap-y-2">
        <span className="font-display text-[15px] font-extrabold tracking-tight text-ink">RegimeRain · SIH26080</span>
        <span>MoES / NCMRWF · Regime-aware post-processing of monsoon rainfall forecasts</span>
        <span className="ml-auto font-mono text-[11.5px]">run {manifest.run_id} · coastline © Natural Earth (public domain)</span>
      </div>
      {manifest.synthetic && <p className="mt-3 font-mono text-[11.5px]">Every number on this site comes from the loaded run. This run is synthetic sample data.</p>}
    </footer>
  )
}
