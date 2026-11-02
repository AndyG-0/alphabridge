import { Markdown } from './Markdown'
import type { ReactNode } from 'react'
import { Line, LineChart, ResponsiveContainer, Tooltip, YAxis } from 'recharts'
import { api, type SymbolDetail as Detail } from '../api/client'
import { useAsync } from '../hooks'
import DcfGrid from './DcfGrid'
import { Badge, Bar, Err, Hint, pct, usd } from './ui'

const num = (n: unknown, d = 1) => (typeof n === 'number' ? n.toFixed(d) : '—')
const big = (n: unknown) => {
  if (typeof n !== 'number') return '—'
  const a = Math.abs(n)
  return a >= 1e12 ? `$${(n / 1e12).toFixed(2)}T` : a >= 1e9 ? `$${(n / 1e9).toFixed(1)}B` : a >= 1e6 ? `$${(n / 1e6).toFixed(0)}M` : usd(n)
}

function Stat({ label, hint, children }: { label: string; hint: ReactNode; children: ReactNode }) {
  return (
    <div>
      <div className="flex items-center gap-1 text-xs text-slate-500">
        {label}
        <Hint>{hint}</Hint>
      </div>
      <div className="text-sm text-slate-100">{children}</div>
    </div>
  )
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div>
      <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-400">{title}</h3>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">{children}</div>
    </div>
  )
}

const BREAKDOWN: Record<string, [string, string]> = {
  growth: ['Revenue growth', 'Full marks at 40%+ year-over-year revenue growth.'],
  margin: ['Margin expansion', 'Operating margin higher than the prior year.'],
  leverage: ['Low leverage', 'Debt/equity of 0 earns full marks; 1.5 or more earns none.'],
  fcf: ['Free cash flow', 'Positive free cash flow.'],
  rsi: ['RSI near 50', 'Neutral momentum scores best; overbought or oversold scores less.'],
  trend: ['Trend', 'Price between 5% below and 25% above its 200-day average.'],
}

export default function SymbolDetail({ symbol, onClose }: { symbol: string; onClose?: () => void }) {
  const { data: d, error, loading } = useAsync<Detail>(() => api.symbolDetail(symbol), [symbol])
  if (loading) return <p className="p-3 text-sm text-slate-400">Loading {symbol}…</p>
  if (error || !d) return <Err error={error ?? new Error('No data')} />
  const f = d.fundamentals,
    t = d.technicals,
    sc = d.screen
  const chart = d.price_series.map((p, i) => ({ i, p }))
  const range = t.high_52w > t.low_52w ? ((d.price - t.low_52w) / (t.high_52w - t.low_52w)) * 100 : 0
  return (
    <div className="space-y-5 rounded-xl border border-slate-800 bg-slate-950/60 p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-lg font-semibold">{d.symbol}</span>
            <span className="text-slate-300">{f.name}</span>
            <Badge>{usd(d.price)}</Badge>
          </div>
          <p className="text-xs text-slate-500">
            {[f.sector, f.industry].filter(Boolean).join(' · ')}
            {f.employees ? ` · ${Number(f.employees).toLocaleString()} employees` : ''}
          </p>
        </div>
        {onClose && (
          <button className="text-xs text-slate-400 hover:text-slate-200" onClick={onClose}>
            Close ✕
          </button>
        )}
      </div>
      {typeof f.summary === 'string' && <p className="line-clamp-4 text-sm text-slate-300">{f.summary}</p>}

      <div>
        <div className="mb-1 flex items-center gap-1 text-xs text-slate-500">
          1-year price<Hint>Weekly closing prices for the last year.</Hint>
        </div>
        <div className="h-32">
          <ResponsiveContainer>
            <LineChart data={chart}>
              <YAxis domain={['auto', 'auto']} hide />
              <Tooltip formatter={(v) => usd(Number(v))} labelFormatter={() => ''} contentStyle={{ background: '#0f172a', border: '1px solid #334155' }} />
              <Line type="monotone" dataKey="p" stroke="#34d399" dot={false} strokeWidth={2} />
            </LineChart>
          </ResponsiveContainer>
        </div>
        <div className="mt-1 flex items-center gap-2 text-xs text-slate-500">
          <span>{usd(t.low_52w)}</span>
          <div className="flex-1">
            <Bar value={range} tone="bg-sky-500" />
          </div>
          <span>{usd(t.high_52w)}</span>
        </div>
      </div>

      <DcfGrid symbol={symbol} />

      <Section title="Price & momentum">
        <Stat label="RSI (14)" hint="Relative Strength Index, 0–100. Above 70 is overbought, below 30 oversold, around 50 neutral.">
          {num(sc.rsi14, 0)}
        </Stat>
        <Stat label="vs 200-day avg" hint="How far the price sits above or below its 200-day moving average, a common long-term trend gauge.">
          {pct(sc.sma200_dist)}
        </Stat>
        <Stat label="Return 1M / 3M / 1Y" hint="Price change over roughly 21, 63 and 252 trading days.">
          {pct(t.ret_1m, 0)} / {pct(t.ret_3m, 0)} / {pct(t.ret_1y, 0)}
        </Stat>
        <Stat label="Volatility" hint="Annualized standard deviation of daily returns.">
          {pct(t.volatility, 0)}
        </Stat>
        <Stat label="Max drawdown (1Y)" hint="Largest peak-to-trough fall in the last year.">
          {pct(t.max_drawdown_1y, 0)}
        </Stat>
        <Stat label="Beta vs SPY" hint="Sensitivity to the S&P 500. 1.0 moves with the market; above 1 amplifies it.">
          {num(t.beta, 2)}
        </Stat>
      </Section>

      <Section title="Valuation">
        <Stat label="P/E (TTM)" hint="Price divided by trailing 12-month earnings per share.">
          {num(f.trailing_pe)}
        </Stat>
        <Stat label="Forward P/E" hint="Price divided by analysts' expected next-12-month earnings.">
          {num(f.forward_pe)}
        </Stat>
        <Stat label="PEG" hint="P/E divided by earnings growth. Around 1 or below suggests growth is not expensive.">
          {num(f.peg, 2)}
        </Stat>
        <Stat label="Price / sales" hint="Market cap divided by trailing revenue; useful when earnings are thin.">
          {num(f.price_to_sales)}
        </Stat>
        <Stat
          label="DCF value"
          hint="Per-share value from a 10-year discounted free-cash-flow model (10% discount rate, growth fading to 2.5%, growth capped at 30%). A rough anchor, not a target."
        >
          {d.dcf_value ? `${usd(d.dcf_value)} (${pct(d.dcf_upside, 0)})` : '—'}
        </Stat>
        <Stat label="Analyst target" hint="Mean Wall Street 12-month price target and consensus rating.">
          {f.target_price ? `${usd(Number(f.target_price))} · ${f.analyst_rating ?? ''}` : '—'}
        </Stat>
        <Stat label="Market cap" hint="Share price times shares outstanding.">
          {big(f.market_cap)}
        </Stat>
        <Stat label="Dividend yield" hint="Annual dividend divided by price.">
          {f.dividend_yield != null ? `${num(f.dividend_yield)}%` : '—'}
        </Stat>
      </Section>

      <Section title="Quality & growth">
        <Stat label="Revenue growth" hint="Year-over-year revenue growth. The screener requires more than 12%.">
          {pct(sc.revenue_growth)}
        </Stat>
        <Stat label="Operating margin" hint="Operating income as a share of revenue.">
          {pct(sc.operating_margin)}
        </Stat>
        <Stat label="Gross / net margin" hint="Gross profit and net income as a share of revenue.">
          {pct(f.gross_margin as number, 0)} / {pct(f.profit_margin as number, 0)}
        </Stat>
        <Stat label="ROE" hint="Return on equity: net income relative to shareholder equity.">
          {pct(f.roe as number, 0)}
        </Stat>
        <Stat label="Debt / equity" hint="Total debt relative to equity. The screener requires under 1.5.">
          {num(f.debt_to_equity, 2)}
        </Stat>
        <Stat label="Current ratio" hint="Current assets divided by current liabilities. Above 1 means near-term bills are covered.">
          {num(f.current_ratio, 2)}
        </Stat>
        <Stat label="Free cash flow" hint="Cash from operations minus capex. The screener requires it to be positive.">
          {big(f.free_cash_flow)}
        </Stat>
        <Stat label="Short % of float" hint="Share of tradable shares sold short; high values signal bearish positioning or squeeze risk.">
          {f.short_pct_float != null ? pct(f.short_pct_float as number) : '—'}
        </Stat>
      </Section>

      <div>
        <h3 className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-slate-400">
          Quant score {sc.score}/100 {sc.passed ? <Badge tone="green">passes</Badge> : <Badge tone="amber">fails a filter</Badge>}
        </h3>
        <div className="space-y-1.5">
          {Object.entries(sc.score_breakdown).map(([k, v]) => (
            <div key={k} className="grid grid-cols-[8.5rem_1fr_3.5rem] items-center gap-2 text-xs text-slate-400">
              <span className="flex items-center gap-1">
                {BREAKDOWN[k]?.[0] ?? k}
                <Hint>{BREAKDOWN[k]?.[1] ?? ''}</Hint>
              </span>
              <Bar value={(v.points / v.max) * 100} />
              <span className="text-right">
                {v.points}/{v.max}
              </span>
            </div>
          ))}
        </div>
      </div>

      <p className="text-xs text-amber-300">
        Portfolio: {pct(d.held_weight)} held in this name · {pct(d.sector_weight)} in {f.sector ?? 'its sector'}.
      </p>

      {d.report ? (
        <div className="space-y-2 text-sm">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs font-semibold uppercase tracking-wide text-slate-400">Latest AI report ({d.report.created_at.slice(0, 10)})</span>
            <Badge>{d.report.recommended_action.replace('_', ' ')}</Badge>
            <Badge>Val {d.report.valuation_grade}</Badge>
            <Badge>Growth {d.report.growth_grade}</Badge>
            <Badge>Moat {d.report.moat_grade}</Badge>
          </div>
          <div className="grid gap-3 md:grid-cols-2">
            <div>
              <h4 className="font-medium text-emerald-400">Bull case</h4>
              <Markdown className="text-slate-300">{d.report.bull_case_md}</Markdown>
            </div>
            <div>
              <h4 className="font-medium text-red-400">Bear case</h4>
              <Markdown className="text-slate-300">{d.report.bear_case_md}</Markdown>
            </div>
          </div>
          {d.report.red_flags.length > 0 && (
            <ul className="list-disc pl-5 text-xs text-red-300">
              {d.report.red_flags.map((r) => (
                <li key={r}>{r}</li>
              ))}
            </ul>
          )}
        </div>
      ) : (
        <p className="text-xs text-slate-500">No AI report yet. Use “AI deep dive” above to read the latest 10-K/10-Q.</p>
      )}
    </div>
  )
}
