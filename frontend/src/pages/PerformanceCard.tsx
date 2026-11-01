import { useState } from 'react'
import { api } from '../api/client'
import { Card, Err, pct, usd } from '../components/ui'
import { useAsync } from '../hooks'

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

export default function PerformanceCard() {
  const [assume, setAssume] = useState(false)
  const [tick, setTick] = useState(0)
  const perf = useAsync(() => api.performance(assume), [assume, tick])
  const [on, setOn] = useState('')
  const [amount, setAmount] = useState('')
  const [err, setErr] = useState<unknown>(null)

  if (perf.error) return <Err error={perf.error} />
  if (!perf.data) return null
  const d = perf.data
  const r = d.returns
  const max = Math.max(1, ...d.income.months.map((m) => m.amount))

  async function add() {
    try {
      await api.addCashFlow({ on, amount: Number(amount) })
      setOn('')
      setAmount('')
      setTick((t) => t + 1)
    } catch (e) {
      setErr(e)
    }
  }

  return (
    <Card title="Performance & benchmarks">
      {!r ? (
        <p className="text-sm text-slate-400">{d.notes[0]}</p>
      ) : (
        <div className="space-y-3 text-sm">
          <div className="grid gap-3 md:grid-cols-4">
            <div>
              <div className="text-xs text-slate-400">Time-weighted return</div>
              <div className="text-lg">{pct(r.twr.total)}</div>
              <div className="text-xs text-slate-400">{r.twr.annualized != null ? `${pct(r.twr.annualized)} / yr` : `${r.twr.days} days`}</div>
            </div>
            <div>
              <div className="text-xs text-slate-400">Money-weighted (IRR)</div>
              <div className="text-lg">{pct(r.mwr)}</div>
            </div>
            {d.benchmarks && (
              <>
                <div>
                  <div className="text-xs text-slate-400">vs {d.benchmarks.market.name}</div>
                  <div className="text-lg">{pct(d.benchmarks.market.return)}</div>
                  <div className="text-xs text-slate-400">excess {pct(d.benchmarks.market.excess)}</div>
                </div>
                <div>
                  <div className="text-xs text-slate-400">{d.benchmarks.target ? d.benchmarks.target.name : 'Target allocation'}</div>
                  <div className="text-lg">{pct(d.benchmarks.target?.return)}</div>
                  <div className="text-xs text-slate-400">{d.benchmarks.target ? `excess ${pct(d.benchmarks.target.excess)}` : 'not set'}</div>
                </div>
              </>
            )}
          </div>
          {d.notes.map((n) => (
            <p key={n} className="text-xs text-amber-300">
              {n}
            </p>
          ))}
        </div>
      )}

      <div className="mt-4 grid gap-4 text-sm md:grid-cols-2">
        <div>
          <h3 className="font-medium text-slate-300">Fee drag</h3>
          <p className="text-xs">
            {usd(d.fees.annual_fee)} / yr · {pct(d.fees.weighted_expense_ratio, 2)} weighted · {pct(d.fees.covered_pct, 0)} of holdings priced
          </p>
          {Object.entries(d.fees.drag).map(([y, v]) => (
            <p key={y} className="text-xs text-slate-400">
              Over {y} years: costs {usd(v.cost)} ({pct(v.cost_pct)} of ending balance)
            </p>
          ))}
          {d.fees.unknown.length > 0 && <p className="text-xs text-slate-500">No expense ratio for: {d.fees.unknown.join(', ')}</p>}
        </div>
        <div>
          <h3 className="font-medium text-slate-300">Income calendar · {usd(d.income.annual_income)} / yr</h3>
          <div className="flex h-16 items-end gap-1">
            {d.income.months.map((m) => (
              <div key={m.month} className="flex-1" title={`${MONTHS[m.month - 1]}: ${usd(m.amount)}`}>
                <div className="rounded-sm bg-sky-500/70" style={{ height: `${(m.amount / max) * 100}%` }} />
              </div>
            ))}
          </div>
          <div className="flex gap-1 text-[10px] text-slate-500">
            {MONTHS.map((m) => (
              <span key={m} className="flex-1 text-center">
                {m[0]}
              </span>
            ))}
          </div>
          <p className="mt-1 text-xs text-slate-500">{d.income.assumption}</p>
        </div>
      </div>

      <div className="mt-4 flex flex-wrap items-end gap-2 text-sm">
        <label className="text-xs text-slate-400">
          Deposit / withdrawal date
          <input type="date" value={on} onChange={(e) => setOn(e.target.value)} className="mt-1 block rounded bg-slate-800 px-2 py-1" />
        </label>
        <label className="text-xs text-slate-400">
          Amount (− for withdrawal)
          <input value={amount} onChange={(e) => setAmount(e.target.value)} inputMode="decimal" className="mt-1 block w-32 rounded bg-slate-800 px-2 py-1" />
        </label>
        <button onClick={add} disabled={!on || !Number(amount)} className="rounded bg-sky-600 text-white px-3 py-1 disabled:opacity-40">
          Record cash flow
        </button>
        {d.flow_mode === 'none' && (
          <label className="flex items-center gap-1 text-xs text-slate-400">
            <input type="checkbox" checked={assume} onChange={(e) => setAssume(e.target.checked)} /> assume monthly contribution
          </label>
        )}
      </div>
      {err != null && <Err error={err} />}
    </Card>
  )
}
