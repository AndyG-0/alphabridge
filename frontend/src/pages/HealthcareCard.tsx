import { useState } from 'react'
import { api } from '../api/client'
import { Card, Err, usd } from '../components/ui'
import { useAsync } from '../hooks'

export default function HealthcareCard() {
  const [magi, setMagi] = useState(120000)
  const [people, setPeople] = useState(2)
  const r = useAsync(() => api.healthcare(magi, people), [magi, people])
  const d = r.data
  if (r.error) return <Err error={r.error} />
  if (!d) return null
  const m = d.medicare
  return (
    <Card title="Health care and long-term care (today's $)">
      <div className="mb-2 flex gap-4 text-sm">
        <label>
          Retirement MAGI <input type="number" className="w-28 bg-transparent border-b" value={magi} onChange={(e) => setMagi(Number(e.target.value))} />
        </label>
        <label>
          People on Medicare{' '}
          <input type="number" min={1} max={2} className="w-12 bg-transparent border-b" value={people} onChange={(e) => setPeople(Number(e.target.value))} />
        </label>
      </div>
      <p className="text-sm">
        Medicare {usd(m.annual)}/yr (Part B {usd(m.part_b_monthly)}/mo, Part D {usd(m.part_d_monthly)}/mo, Medigap {usd(m.medigap_monthly)}/mo).{' '}
        {m.irmaa_tier > 0 ? `IRMAA tier ${m.irmaa_tier} adds ${usd(m.irmaa_monthly)}/mo each.` : 'No IRMAA surcharge.'}
      </p>
      <table className="mt-2 w-full text-sm">
        <thead className="text-left text-slate-400">
          <tr>
            <th>Pre-65 age</th>
            <th className="text-right">Benchmark</th>
            <th className="text-right">Net after credit</th>
          </tr>
        </thead>
        <tbody>
          {d.pre65.map((x) => (
            <tr key={x.age}>
              <td>{x.age}</td>
              <td className="text-right">{usd(x.benchmark)}</td>
              <td className="text-right">{usd(x.net)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {d.coverage_options?.some((c) => c.options.length > 0) && (
        <div className="mt-2 text-sm">
          <div className="text-slate-400">Your coverage options (annual per person, at current age)</div>
          {d.coverage_options
            .filter((c) => c.options.length > 0)
            .map((c) => (
              <div key={c.person}>
                {c.person === 'SELF' ? 'You' : 'Spouse'} ({c.age}):{c.aca_net != null ? ` ACA ${usd(c.aca_net)} · ` : ' '}
                {c.options.map((o) => `${o.name} ${usd(o.annual)}`).join(' · ')}
              </div>
            ))}
        </div>
      )}
      <p className="mt-2 text-sm">{d.ltc.map((x) => `${x.mode === 'EXPECTED' ? 'Expected' : 'Stress'} LTC: ${usd(x.total)}`).join(' · ')}</p>
      <p className="mt-1 text-xs text-slate-400">
        {d.magi_basis}. {d.assumptions.verified ? '' : 'Part D and Medigap figures are unverified estimates.'}
      </p>
    </Card>
  )
}
