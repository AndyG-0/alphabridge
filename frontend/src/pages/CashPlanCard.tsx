import { useState } from 'react'
import { api } from '../api/client'
import { Card, Err, pct, usd } from '../components/ui'
import { useAsync } from '../hooks'

export default function CashPlanCard() {
  const [tick, setTick] = useState(0)
  const cp = useAsync(api.cashPlan, [tick])
  const [err, setErr] = useState<unknown>(null)
  if (cp.error) return <Err error={cp.error} />
  if (!cp.data) return null
  const d = cp.data
  const tc = d.tax_comparison
  const active = d.dca_active && d.dca_active.schedule?.length ? d.dca_active : null

  async function run(fn: () => Promise<unknown>) {
    try {
      await fn()
      setErr(null)
      setTick((t) => t + 1)
    } catch (e) {
      setErr(e)
    }
  }

  return (
    <Card title="Cash plan">
      <div className="space-y-4 text-sm">
        <Err error={err} />
        <div>
          <h3 className="font-medium text-slate-300">Reserves</h3>
          <p>
            Emergency fund target <b>{usd(d.emergency_fund.target)}</b> ({d.emergency_fund.months} months of essentials)
            {d.emergency_fund.gap > 0 ? (
              <span className="text-amber-300"> — {usd(d.emergency_fund.gap)} short</span>
            ) : (
              <span className="text-emerald-400"> — covered</span>
            )}
          </p>
          <p>
            Bridge reserve <b>{usd(d.bridge_reserve.total)}</b> for the first {d.bridge_reserve.years} retirement years (age {d.bridge_reserve.retire_age}), so
            early downturns never force stock sales. Total cash target <b>{usd(d.total_reserve_target)}</b>.
          </p>
        </div>

        <div>
          <h3 className="font-medium text-slate-300">T-bill vs money market ({tc.state})</h3>
          <p>
            After tax, T-bills keep {usd(tc.tbill_after_tax)} vs {usd(tc.mmf_after_tax)} in your money market per year —{' '}
            <b className={tc.winner === 'TBILL' ? 'text-emerald-400' : 'text-slate-300'}>
              {tc.winner === 'TBILL' ? `T-bills ahead by ${usd(tc.advantage)}` : 'money market ahead'}
            </b>
            . State rate {pct(tc.state_rate)}
            {tc.state_rate_known ? '' : ' (planning default)'}; T-bill interest is exempt from state tax.
          </p>
        </div>

        <div>
          <h3 className="font-medium text-slate-300">Ladder</h3>
          {d.ladder.rungs.length === 0 ? (
            <p className="text-slate-400">No cash beyond the emergency fund and one month of float to ladder yet.</p>
          ) : (
            <table className="w-full text-xs">
              <thead className="text-left text-slate-400">
                <tr>
                  <th>Term</th>
                  <th className="text-right">Amount</th>
                  <th className="text-right">Yield</th>
                  <th className="text-right">Matures</th>
                </tr>
              </thead>
              <tbody>
                {d.ladder.rungs.map((r) => (
                  <tr key={r.months}>
                    <td>{r.months} mo</td>
                    <td className="text-right">{usd(r.amount)}</td>
                    <td className="text-right">{pct(r.yield, 2)}</td>
                    <td className="text-right">{r.matures_on}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {d.ladder.rungs.length > 0 && (
            <p className="mt-1 text-xs text-slate-500">
              Blended {pct(d.ladder.blended_yield, 2)} ≈ {usd(d.ladder.annual_interest)}/yr. I-bond cap {usd(d.i_bond.annual_purchase_cap)}/yr;{' '}
              {d.i_bond.verdict}.
            </p>
          )}
        </div>

        <div>
          <h3 className="font-medium text-slate-300">DCA</h3>
          {active ? (
            <>
              <ul className="text-xs text-slate-400">
                {active.schedule.map((t) => (
                  <li key={t.on}>
                    {t.on} — {usd(t.amount)}
                    {active.notified.includes(t.on) ? ' (reminded)' : ''}
                  </li>
                ))}
              </ul>
              <button className="mt-1 rounded bg-slate-800 px-2 py-1 text-xs" onClick={() => run(() => api.clearDca())}>
                Clear schedule
              </button>
            </>
          ) : d.dca ? (
            <>
              <p>
                Today’s signal suggests {usd(d.dca.amount)} in {d.dca.tranches} tranches ({usd(d.dca.schedule[0].amount)} each, monthly).
              </p>
              <button
                className="mt-1 rounded bg-sky-600 text-white px-2 py-1 text-xs"
                onClick={() => run(() => api.saveDca({ amount: d.dca!.amount, tranches: d.dca!.tranches }))}
              >
                Save schedule &amp; remind me
              </button>
            </>
          ) : (
            <p className="text-slate-400">No deployment suggested right now ({d.signal.replaceAll('_', ' ').toLowerCase()}).</p>
          )}
        </div>
        {d.notes.map((n) => (
          <p key={n} className="text-xs text-slate-500">
            {n}
          </p>
        ))}
      </div>
    </Card>
  )
}
