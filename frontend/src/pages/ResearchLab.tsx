import { Markdown } from '../components/Markdown'
import { Fragment, useState } from 'react'
import type { ReactNode } from 'react'
import { api, type Report, type WhatIf } from '../api/client'
import SymbolDetail from '../components/SymbolDetail'
import WatchlistCard from './WatchlistCard'
import { Badge, Button, Card, Err, Hint, Input, pct } from '../components/ui'
import { useAsync } from '../hooks'

function Th({ children, hint }: { children: ReactNode; hint: ReactNode }) {
  return (
    <th className="pb-1 pr-3 font-medium">
      <span className="inline-flex items-center gap-1">
        {children}
        <Hint>{hint}</Hint>
      </span>
    </th>
  )
}

function SymbolButton({ symbol, onOpen }: { symbol: string; onOpen: (s: string) => void }) {
  return (
    <button className="font-mono text-sky-400 hover:underline" title="Show full company detail" onClick={() => onOpen(symbol)}>
      {symbol}
    </button>
  )
}

function ReportCard({ r, onOpen }: { r: Report; onOpen: (s: string) => void }) {
  const tone = r.recommended_action === 'BUY_SATELLITE' ? 'green' : r.recommended_action === 'AVOID' ? 'red' : 'amber'
  return (
    <Card>
      <div className="flex flex-wrap items-center gap-2">
        <button className="text-lg font-semibold text-sky-400 hover:underline" onClick={() => onOpen(r.symbol)}>
          {r.symbol}
        </button>
        <Badge tone={tone}>{r.recommended_action.replace('_', ' ')}</Badge>
        <Badge>Quant {r.quant_score.toFixed(0)}</Badge>
        <Hint>0–100 score from growth, margins, leverage, free cash flow, RSI and trend. Click the symbol for the breakdown.</Hint>
        <Badge>Val {r.valuation_grade}</Badge>
        <Badge>Growth {r.growth_grade}</Badge>
        <Badge>Moat {r.moat_grade}</Badge>
        <Hint>
          AI-assigned A–F grades from the latest SEC filing: valuation (A = attractive), growth outlook, and moat (durability of competitive advantage).
        </Hint>
      </div>
      <div className="mt-3 grid gap-3 text-sm md:grid-cols-2">
        <div>
          <h3 className="font-medium text-emerald-400">Bull case</h3>
          <Markdown className="text-slate-300">{r.bull_case_md}</Markdown>
        </div>
        <div>
          <h3 className="font-medium text-red-400">Bear case</h3>
          <Markdown className="text-slate-300">{r.bear_case_md}</Markdown>
        </div>
      </div>
      <p className="mt-2 text-xs text-amber-300">Portfolio fit: {r.portfolio_fit_notes}</p>
      {r.sec_filing_citations_json.length > 0 && (
        <ul className="mt-2 space-y-1 text-xs text-slate-500">
          {r.sec_filing_citations_json.map((c, i) => (
            <li key={i}>
              {c.form} {c.filing_date}
              {c.section ? ` · ${c.section}` : ''}
              {c.quote ? ` — “${c.quote}”` : ''}{' '}
              {c.url && (
                <a className="text-sky-400" href={c.url} target="_blank" rel="noreferrer">
                  source
                </a>
              )}
            </li>
          ))}
        </ul>
      )}
    </Card>
  )
}

export default function ResearchLab() {
  const reports = useAsync(api.reports)
  const screen = useAsync(api.screener)
  const [sym, setSym] = useState('')
  const [amt, setAmt] = useState('5000')
  const [wi, setWi] = useState<WhatIf | null>(null)
  const [open, setOpen] = useState<string | null>(null)
  const [busy, setBusy] = useState('')
  const [err, setErr] = useState<unknown>(null)
  const run = async (name: string, fn: () => Promise<unknown>) => {
    setBusy(name)
    setErr(null)
    try {
      await fn()
    } catch (e) {
      setErr(e)
    } finally {
      setBusy('')
    }
  }
  return (
    <div className="space-y-4">
      <WatchlistCard />
      <Card title="What-if lab">
        <div className="grid gap-3 md:grid-cols-[1fr_1fr_auto_auto_auto] md:items-end">
          <Input label="Ticker" value={sym} onChange={(e) => setSym(e.target.value.toUpperCase())} placeholder="NVDA" />
          <Input label="Amount ($)" type="number" value={amt} onChange={(e) => setAmt(e.target.value)} />
          <Button disabled={!sym || !!busy} onClick={() => run('wi', async () => setWi(await api.whatIf(sym, Number(amt))))}>
            {busy === 'wi' ? 'Running…' : 'Simulate'}
          </Button>
          <Button variant="ghost" disabled={!sym} onClick={() => setOpen(sym)}>
            Details
          </Button>
          <Button
            variant="ghost"
            disabled={!sym || !!busy}
            onClick={() =>
              run('dd', async () => {
                await api.deepDive(sym)
                reports.reload()
              })
            }
          >
            {busy === 'dd' ? 'Reading filings…' : 'AI deep dive'}
          </Button>
        </div>
        <Err error={err} />
        {wi && (
          <div className="mt-3 space-y-2 text-sm">
            <p>
              Beta of {wi.symbol}: <b>{wi.asset_beta?.toFixed(2) ?? '—'}</b> · Portfolio beta {wi.portfolio_beta_before?.toFixed(2) ?? '—'} →{' '}
              <b>{wi.portfolio_beta_after?.toFixed(2) ?? '—'}</b>
            </p>
            {wi.warnings.map((w) => (
              <p key={w} className="text-amber-300">
                ⚠ {w}
              </p>
            ))}
            <div className="flex flex-wrap gap-2">
              {Object.entries(wi.sector_after)
                .filter(([, v]) => v > 0.01)
                .map(([k, v]) => (
                  <Badge key={k}>
                    {k} {pct(v, 0)}
                  </Badge>
                ))}
            </div>
          </div>
        )}
      </Card>
      <Card title="Weekly picks (quant screener)">
        <Button
          variant="ghost"
          disabled={!!busy}
          onClick={() =>
            run('sc', async () => {
              await api.runScreener()
              screen.reload()
            })
          }
        >
          {busy === 'sc' ? 'Screening (can take a few minutes)…' : 'Run screener now'}
        </Button>
        <div tabIndex={0} role="region" aria-label="Scrollable table" className="mt-3 overflow-x-auto md:overflow-visible">
          <table className="w-full text-sm">
            <thead className="text-left text-xs text-slate-500">
              <tr>
                <Th hint="Click a symbol for full company detail: price chart, valuation, quality metrics, score breakdown and any AI report.">Symbol</Th>
                <Th hint="0–100 quant score: revenue growth 30, margin expansion 20, low leverage 15, positive free cash flow 15, RSI near 50 10, price within -5% to +25% of its 200-day average 10. Then nudged up to 10% by sector strength.">
                  Score
                </Th>
                <Th hint="Year-over-year revenue growth. The screener requires more than 12%.">Rev growth</Th>
                <Th hint="14-day Relative Strength Index, a 0–100 momentum gauge. Above 70 is overbought, below 30 oversold, around 50 neutral. The score favors readings near 50, so strong stocks that have pulled back rank well.">
                  RSI
                </Th>
                <Th hint="Company sector. Used for the sector-strength overlay and your portfolio concentration checks.">Sector</Th>
                <Th hint="Passes all four hard filters: revenue growth above 12%, expanding operating margin, debt/equity under 1.5, and positive free cash flow.">
                  Status
                </Th>
              </tr>
            </thead>
            <tbody>
              {screen.data?.map((s) => (
                <Fragment key={s.symbol}>
                  <tr className="border-t border-slate-800">
                    <td className="py-1 pr-3">
                      <SymbolButton symbol={s.symbol} onOpen={(x) => setOpen(open === x ? null : x)} />
                    </td>
                    <td className="pr-3">{s.score}</td>
                    <td className="pr-3">{pct(s.revenue_growth, 0)}</td>
                    <td className="pr-3">{s.rsi14?.toFixed(0) ?? '—'}</td>
                    <td className="pr-3 text-slate-400">{s.sector}</td>
                    <td>{s.passed && <Badge tone="green">passes</Badge>}</td>
                  </tr>
                  {open === s.symbol && (
                    <tr>
                      <td colSpan={6} className="pb-3">
                        <SymbolDetail symbol={s.symbol} onClose={() => setOpen(null)} />
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
      {open && !screen.data?.some((x) => x.symbol === open) && <SymbolDetail symbol={open} onClose={() => setOpen(null)} />}
      {reports.data?.map((r) => (
        <ReportCard key={r.id} r={r} onOpen={setOpen} />
      ))}
    </div>
  )
}
