import { useState } from 'react'
import { api } from '../api/client'
import { Badge, Card, Err, usd } from '../components/ui'
import { useAsync } from '../hooks'

export default function WithdrawalsCard() {
  const w = useAsync(api.withdrawals)
  const [pick, setPick] = useState<string | null>(null)
  const d = w.data
  if (w.error) return <Err error={w.error} />
  if (!d) return null
  const shown = d.strategies.find((s) => s.strategy === (pick ?? d.best)) ?? d.strategies[0]
  if (!shown) return null
  return (
    <Card title="Which account to draw from">
      <p className="mb-3 text-sm text-slate-400">
        Each strategy is run year by year through the {d.rules_year} federal tax brackets and the {d.aca_rules_year} ACA subsidy schedule
        {d.aca_enhanced ? ' (enhanced credits)' : ' (400% FPL cliff)'}. Lowest lifetime cost: <b>{d.strategies.find((s) => s.strategy === d.best)?.label}</b>.
      </p>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="text-left text-slate-400">
            <tr>
              <th>Strategy</th>
              <th className="text-right">Lifetime tax</th>
              <th className="text-right">ACA premiums</th>
              <th className="text-right">Ending (after tax)</th>
              <th className="text-right">Years over cliff</th>
            </tr>
          </thead>
          <tbody>
            {d.strategies.map((s) => (
              <tr key={s.strategy} className={s.strategy === shown.strategy ? 'bg-slate-800/60' : ''}>
                <td>
                  <button className="text-left underline-offset-2 hover:underline" onClick={() => setPick(s.strategy)}>
                    {s.label}
                  </button>{' '}
                  {s.strategy === d.best && <Badge tone="green">best</Badge>}
                  {s.shortfall_years > 0 && <Badge tone="red">{s.shortfall_years} short years</Badge>}
                </td>
                <td className="text-right">{usd(s.lifetime_tax)}</td>
                <td className="text-right">{usd(s.lifetime_aca_premiums)}</td>
                <td className="text-right">{usd(s.ending_after_tax)}</td>
                <td className="text-right">{s.years_over_aca_cliff}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {shown.years && (
        <div className="mt-4 max-h-80 overflow-auto">
          <table className="w-full text-xs">
            <thead className="sticky top-0 bg-slate-900 text-left text-slate-400">
              <tr>
                <th>Year</th>
                <th>Age</th>
                <th className="text-right">Taxable</th>
                <th className="text-right">Pre-tax</th>
                <th className="text-right">Roth</th>
                <th className="text-right">MAGI</th>
                <th className="text-right">Tax</th>
                <th className="text-right">ACA</th>
              </tr>
            </thead>
            <tbody>
              {shown.years.map((r) => (
                <tr key={r.year} className={r.shortfall > 1 ? 'text-red-400' : ''}>
                  <td>{r.year}</td>
                  <td>{r.age}</td>
                  <td className="text-right">{usd(r.draw_taxable)}</td>
                  <td className="text-right">{usd(r.draw_pretax)}</td>
                  <td className="text-right">{usd(r.draw_roth)}</td>
                  <td className={`text-right ${r.aca_over_cliff ? 'text-amber-400' : ''}`}>{usd(r.magi)}</td>
                  <td className="text-right">{usd(r.tax)}</td>
                  <td className="text-right">{usd(r.aca_premium)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <ul className="mt-3 list-disc pl-5 text-xs text-slate-500">
        {d.assumptions.map((a) => (
          <li key={a}>{a}</li>
        ))}
      </ul>
    </Card>
  )
}
