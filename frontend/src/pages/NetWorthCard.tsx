import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { api } from '../api/client'
import { Card, Err, pct, usd } from '../components/ui'
import { useAsync } from '../hooks'

const label = (k: string) => k.replaceAll('_', ' ').toLowerCase()

export default function NetWorthCard() {
  const nw = useAsync(api.netWorth, [])
  if (nw.error) return <Err error={nw.error} />
  if (!nw.data) return null
  const d = nw.data
  const last = d.drift[d.drift.length - 1]
  const assets = Object.entries(d.latest?.breakdown.assets ?? {}).filter(([, v]) => v > 0)
  const debts = Object.entries(d.latest?.breakdown.liabilities ?? {}).filter(([, v]) => v > 0)
  return (
    <Card title="Net worth over time" className="md:col-span-2">
      {d.series.length < 2 ? (
        <p className="text-sm text-slate-400">History builds up from daily snapshots and each import. Check back after a couple of days.</p>
      ) : (
        <div className="h-48">
          <ResponsiveContainer>
            <AreaChart data={d.series.map((r) => ({ ...r, day: r.taken_at.slice(0, 10) }))}>
              <CartesianGrid stroke="#1e293b" vertical={false} />
              <XAxis dataKey="day" tick={{ fontSize: 10 }} stroke="#475569" minTickGap={32} />
              <YAxis tick={{ fontSize: 10 }} stroke="#475569" width={56} tickFormatter={(v) => `$${Math.round(Number(v) / 1000)}k`} />
              <Tooltip formatter={(v) => [usd(Number(v)), 'Net worth']} contentStyle={{ background: '#0f172a', border: '1px solid #334155' }} />
              <Area dataKey="total" stroke="#3987e5" fill="#3987e5" fillOpacity={0.2} strokeWidth={2} />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      )}
      <div className="mt-3 grid gap-4 text-sm md:grid-cols-3">
        <div>
          <h3 className="font-medium text-slate-300">Assets</h3>
          {assets.map(([k, v]) => (
            <div key={k} className="flex justify-between text-xs">
              <span className="capitalize">{label(k)}</span>
              <span>{usd(v)}</span>
            </div>
          ))}
          {debts.length > 0 && <h3 className="mt-2 font-medium text-slate-300">Debts</h3>}
          {debts.map(([k, v]) => (
            <div key={k} className="flex justify-between text-xs">
              <span className="capitalize">{label(k)}</span>
              <span>−{usd(v)}</span>
            </div>
          ))}
        </div>
        <div>
          <h3 className="font-medium text-slate-300">Milestones</h3>
          {d.milestones.reached.slice(-3).map((m) => (
            <p key={m.level} className="text-xs">
              {m.is_fi ? 'FI number ' : ''}
              {usd(m.level)} · {m.reached_on}
            </p>
          ))}
          {d.milestones.next && (
            <p className="mt-1 text-xs text-slate-400">
              Next: {d.milestones.next.is_fi ? 'FI number ' : ''}
              {usd(d.milestones.next.level)} ({usd(d.milestones.next.remaining)} to go)
            </p>
          )}
        </div>
        <div>
          <h3 className="font-medium text-slate-300">Plan vs actual</h3>
          {last ? (
            <p className="text-xs">
              {last.month}: {usd(last.actual)} vs {usd(last.planned)} planned (
              <span className={last.drift >= 0 ? 'text-emerald-400' : 'text-amber-400'}>
                {last.drift >= 0 ? '+' : '−'}
                {usd(Math.abs(last.drift))}
                {last.drift_pct != null ? `, ${pct(Math.abs(last.drift_pct), 1)}` : ''}
              </span>
              )
            </p>
          ) : (
            <p className="text-xs text-slate-400">No snapshots yet.</p>
          )}
          <p className="mt-1 text-xs text-slate-500">
            Projected from {d.assumptions.baseline ?? 'the first snapshot'} at {pct(d.assumptions.annual_return, 1)}/yr plus{' '}
            {usd(d.assumptions.monthly_contribution)}/mo.
          </p>
        </div>
      </div>
    </Card>
  )
}
