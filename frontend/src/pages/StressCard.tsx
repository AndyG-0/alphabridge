import { Bar as RBar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { api } from '../api/client'
import { Card, Err, usd } from '../components/ui'
import { useAsync } from '../hooks'

const pct = (v: number | null | undefined) => (v == null ? 'n/a' : `${Math.round(v * 100)}%`)

export default function StressCard() {
  const r = useAsync(api.stress)
  const d = r.data
  if (r.error) return <Err error={r.error} />
  if (!d || d.inputs.portfolio <= 0) return null
  const boot = d.simulated.find((m) => m.method === 'bootstrap')
  const chart = (boot?.by_first5 ?? []).map((b) => ({ name: `Q${b.bucket}`, success: Math.round((b.success_rate ?? 0) * 100) }))
  return (
    <Card title="Stress tests: bad early returns">
      <p className="mb-2 text-sm text-slate-400">
        Spending {usd(d.inputs.initial_spend)}/yr (today&apos;s dollars) from {usd(d.inputs.portfolio)} for {d.inputs.years} years.
      </p>
      <ul className="mb-3 text-sm">
        {d.historical.map((h) => (
          <li key={h.start_year}>
            Retire {h.start_year}: <b>{h.complete ? (h.success ? 'survives' : 'runs out') : `only ${h.years_covered} years of data`}</b>
          </li>
        ))}
        <li>
          Every historical start ({d.rolling.windows} windows): <b>{pct(d.rolling.success_rate)}</b> succeed
        </li>
        {d.simulated.map((m) => (
          <li key={m.method} title={m.description}>
            {m.method.replace('_', ' ')}: <b>{pct(m.success_rate)}</b>
          </li>
        ))}
        <li>
          Cash bucket ({d.bucket.bucket_years} yrs): {pct(d.bucket.plain.success_rate)} → {pct(d.bucket.bucket.success_rate)}
        </li>
      </ul>
      <div className="h-40">
        <ResponsiveContainer>
          <BarChart data={chart}>
            <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
            <XAxis dataKey="name" />
            <YAxis unit="%" domain={[0, 100]} />
            <Tooltip />
            <RBar dataKey="success" fill="#38bdf8" name="Success %" />
          </BarChart>
        </ResponsiveContainer>
      </div>
      <p className="mt-1 text-xs text-slate-500">
        Success by first-five-year return (Q1 = worst fifth). Data: Damodaran / NYU Stern, {d.data.first_year}-{d.data.last_year}. The past is not a forecast.
      </p>
    </Card>
  )
}
