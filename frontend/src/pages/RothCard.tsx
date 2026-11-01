import { useState } from 'react'
import { api } from '../api/client'
import StackedYears from '../components/charts/StackedYears'
import { Badge, Card, Err, usd } from '../components/ui'
import { useAsync } from '../hooks'

export default function RothCard() {
  const r = useAsync(api.roth)
  const [pick, setPick] = useState<string | null>(null)
  const d = r.data
  if (r.error) return <Err error={r.error} />
  if (!d) return null
  const shown = d.plans.find((p) => p.strategy === (pick ?? d.best)) ?? d.plans.find((p) => p.total_converted > 0)
  const conversions = (shown?.years ?? []).filter((y) => y.conversion > 1)
  return (
    <Card title="Roth conversion ladder">
      <p className="mb-3 text-sm text-slate-400">
        Converts pre-tax money in low-income years, pays the tax from taxable savings, and compares lifetime tax, ending wealth and the first RMD against doing
        nothing ({d.rules_year} brackets).{' '}
        {d.best ? (
          <>
            Lowest lifetime cost: <b>{d.plans.find((p) => p.strategy === d.best)?.label}</b>.
          </>
        ) : (
          'No mode beats skipping conversions with these inputs.'
        )}
      </p>
      <div tabIndex={0} role="region" aria-label="Scrollable table" className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="text-left text-slate-400">
            <tr>
              <th>Plan</th>
              <th className="text-right">Converted</th>
              <th className="text-right">Lifetime tax + premiums</th>
              <th className="text-right">Ending (after tax)</th>
              <th className="text-right">First RMD</th>
            </tr>
          </thead>
          <tbody>
            {d.plans.map((p) => (
              <tr key={p.strategy} className={p.strategy === shown?.strategy ? 'bg-slate-800/60' : ''}>
                <td>
                  <button className="text-left underline-offset-2 hover:underline" onClick={() => setPick(p.strategy)}>
                    {p.label}
                  </button>{' '}
                  {p.strategy === d.best && <Badge tone="green">best</Badge>}
                  {!p.bridge_ok && <Badge tone="red">bridge short</Badge>}
                </td>
                <td className="text-right">{usd(p.total_converted)}</td>
                <td className="text-right">{usd(p.lifetime_cost)}</td>
                <td className="text-right">{usd(p.ending_after_tax)}</td>
                <td className="text-right">{usd(p.first_rmd)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {shown && shown.total_converted > 0 && (
        <div className="mt-3">
          <StackedYears
            title="Roth conversions by year"
            rows={conversions as unknown as Record<string, number>[]}
            series={[
              { key: 'conversion', label: 'Converted to Roth' },
              { key: 'conversion_tax', label: 'Extra tax' },
            ]}
          />
        </div>
      )}
      {shown && shown.total_converted > 0 && (
        <div tabIndex={0} role="region" aria-label="Roth ladder by year" className="mt-3 max-h-64 overflow-auto text-sm">
          <table className="w-full">
            <thead className="text-left text-slate-400">
              <tr>
                <th>Age</th>
                <th className="text-right">Conversion</th>
                <th className="text-right">Extra tax</th>
                <th className="text-right">Penalty-free from</th>
              </tr>
            </thead>
            <tbody>
              {(shown.years ?? [])
                .filter((y) => y.conversion > 1)
                .map((y) => (
                  <tr key={y.year}>
                    <td>{y.age}</td>
                    <td className="text-right">{usd(y.conversion)}</td>
                    <td className="text-right">{usd(y.conversion_tax)}</td>
                    <td className="text-right">{y.year + 5}</td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
      )}
      <ul className="mt-2 list-disc pl-5 text-xs text-slate-500">
        {d.assumptions.map((a) => (
          <li key={a}>{a}</li>
        ))}
      </ul>
    </Card>
  )
}
