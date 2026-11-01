import { api } from '../api/client'
import { Card, Err, usd } from '../components/ui'
import { useAsync } from '../hooks'

export default function StrategiesCard() {
  const r = useAsync(api.strategies)
  const d = r.data
  if (r.error) return <Err error={r.error} />
  if (!d || d.portfolio <= 0) return null
  return (
    <Card title="How much can I spend? Withdrawal policies">
      <p className="mb-3 text-sm text-slate-400">
        Highest starting spend (today&apos;s dollars, before tax) from {usd(d.portfolio)} at {d.retire_age} for {d.years} years. Your plan spends{' '}
        {usd(d.current_plan_spend_after_tax)} after tax.
      </p>
      <div tabIndex={0} role="region" aria-label="Scrollable table" className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="text-left text-slate-400">
            <tr>
              <th>Policy</th>
              <th className="text-right">At 90%</th>
              <th className="text-right">At 95%</th>
              <th className="text-right">Worst-year (p10)</th>
            </tr>
          </thead>
          <tbody>
            {d.policies.map((p) => (
              <tr key={p.policy}>
                <td>{p.label}</td>
                <td className="text-right">{usd(p.safe_spend['90'])}</td>
                <td className="text-right">{usd(p.safe_spend['95'])}</td>
                <td className="text-right">{usd(p.worst_year_spend_p10)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-2 text-xs text-slate-500">
        Flexible policies start higher but may cut spending to half the target. Seeded Monte Carlo with real returns; not a guarantee.
      </p>
    </Card>
  )
}
