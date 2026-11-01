import { api } from '../api/client'
import { Card, Err, usd } from '../components/ui'
import { useAsync } from '../hooks'

const LABELS: Record<string, string> = { lean: 'Lean FI', fi: 'FI', fat: 'Fat FI', barista: 'Barista FI' }

export default function SavingsCard() {
  const r = useAsync(api.savings)
  const d = r.data
  if (r.error) return <Err error={r.error} />
  if (!d) return null
  const w = d.waterfall
  return (
    <Card title="Savings and financial independence">
      <p className="mb-2 text-sm text-slate-400">
        {w.limits.rules_year} limits: 401(k) up to {usd(w.limits.k401_max)}, IRA {usd(w.limits.ira_base)}. Where your {usd(d.inputs.annual_saving)}/yr goes, in
        order:
      </p>
      <ol className="mb-4 list-decimal pl-5 text-sm">
        {w.steps
          .filter((s) => s.amount > 0)
          .map((s) => (
            <li key={s.step}>
              {s.step}: <b>{usd(s.amount)}</b>
            </li>
          ))}
      </ol>
      <table className="w-full text-sm">
        <thead className="text-left text-slate-400">
          <tr>
            <th>Target</th>
            <th className="text-right">Number</th>
            <th className="text-right">Progress</th>
            <th className="text-right">Years</th>
          </tr>
        </thead>
        <tbody>
          {Object.entries(LABELS).map(([k, label]) => (
            <tr key={k}>
              <td>{label}</td>
              <td className="text-right">{usd(d.fi.numbers[k as 'fi'])}</td>
              <td className="text-right">{Math.round((d.fi.progress[k] ?? 0) * 100)}%</td>
              <td className="text-right">{d.fi.years_to[k] == null ? 'n/a' : d.fi.years_to[k]!.toFixed(1)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mt-2 text-xs text-slate-500">
        Coast FI needs {usd(d.fi.coast.needed_now)} today ({d.fi.coast.reached ? 'reached' : 'not yet'}). Assumes a 5% real return and a 4% withdrawal rate.
        General education, not tax advice.
      </p>
    </Card>
  )
}
