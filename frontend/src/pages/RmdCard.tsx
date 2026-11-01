import { api } from '../api/client'
import { Badge, Card, Err, usd } from '../components/ui'
import { useAsync } from '../hooks'

export default function RmdCard() {
  const r = useAsync(api.rmd)
  const d = r.data
  if (r.error) return <Err error={r.error} />
  if (!d || d.household_by_year.length === 0) return null
  const b = d.peak_year_bracket
  return (
    <Card title="Required minimum distributions">
      <p className="mb-3 text-sm text-slate-400">
        Pre-tax balances must start paying out at {d.people.map((p) => `${p.owner === 'SELF' ? 'you' : 'spouse'}: ${p.start_age}`).join(', ')} (SECURE 2.0). A
        qualified charitable distribution can satisfy up to {usd(d.qcd_limit)} a year of it tax-free.
      </p>
      {b && (
        <p className="mb-3 text-sm">
          In {b.year} the household RMD is {usd(b.rmd)}, adding about {usd(b.extra_tax)} of tax; marginal rate {Math.round(b.marginal_without * 100)}% →{' '}
          {Math.round(b.marginal_with * 100)}% {b.bracket_jump && <Badge tone="amber">bracket jump</Badge>}{' '}
          {b.irmaa_jump && <Badge tone="red">IRMAA tier up</Badge>}
        </p>
      )}
      <div tabIndex={0} role="region" aria-label="RMD schedule" className="max-h-64 overflow-auto">
        <table className="w-full text-sm">
          <thead className="text-left text-slate-400">
            <tr>
              <th>Year</th>
              <th className="text-right">RMD</th>
            </tr>
          </thead>
          <tbody>
            {d.household_by_year.slice(0, 15).map((y) => (
              <tr key={y.year}>
                <td>{y.year}</td>
                <td className="text-right">{usd(y.rmd)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-2 text-xs text-slate-500">Uniform Lifetime Table (IRS Pub 590-B, retrieved {d.retrieved_on}). Joint-life divisors are not tabulated.</p>
    </Card>
  )
}
