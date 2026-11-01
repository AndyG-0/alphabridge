import { api } from '../api/client'
import { Card, Err, usd } from '../components/ui'
import { useAsync } from '../hooks'

export default function SocialSecurityCard() {
  const r = useAsync(api.socialSecurity)
  const d = r.data
  if (r.error) return <Err error={r.error} />
  if (!d || d.people.every((p) => p.pia <= 0)) return null
  const who = (i: number) => d.people[i]?.name ?? ''
  return (
    <Card title="When to claim Social Security">
      <p className="mb-3 text-sm text-slate-400">
        Best household claim ages (longevity-weighted, with spousal and survivor benefits): {who(0)} at <b>{d.best.claim_a}</b>
        {d.best.claim_b != null && (
          <>
            , {who(1)} at <b>{d.best.claim_b}</b>
          </>
        )}
        . {d.gain_vs_current > 1 ? `That is worth about ${usd(d.gain_vs_current)} more than your current choice.` : 'That matches your current choice.'}
      </p>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="text-left text-slate-400">
            <tr>
              <th>Claim age</th>
              {d.people.map((p) => (
                <th key={p.name} className="text-right">
                  {p.name} / month
                </th>
              ))}
              <th className="text-right">Break-even vs 62</th>
            </tr>
          </thead>
          <tbody>
            {d.people[0].rows.map((row, i) => (
              <tr key={row.claim_age}>
                <td>{row.claim_age}</td>
                {d.people.map((p) => (
                  <td key={p.name} className="text-right">
                    {usd(p.rows[i].monthly)}
                  </td>
                ))}
                <td className="text-right">{row.breakeven_vs_62 ? `age ${row.breakeven_vs_62.toFixed(1)}` : '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <ul className="mt-2 list-disc pl-5 text-xs text-slate-500">
        {d.assumptions.map((a) => (
          <li key={a}>{a}</li>
        ))}
      </ul>
    </Card>
  )
}
