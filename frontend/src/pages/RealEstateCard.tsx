import { useState } from 'react'
import { api } from '../api/client'
import { Card, Err, usd } from '../components/ui'
import { useAsync } from '../hooks'

export default function RealEstateCard() {
  const [newHome, setNewHome] = useState(0)
  const [col, setCol] = useState(0)
  const q = `?${newHome > 0 ? `new_home_price=${newHome}&` : ''}${col > 0 ? `target_col_index=${col}` : ''}`
  const r = useAsync(() => api.realEstate(q), [q])
  const d = r.data
  if (r.error) return <Err error={r.error} />
  if (!d) return null
  if (d.home_value <= 0 && d.paydown_vs_invest.length === 0) return null
  const rows = d.projection.filter((_, i) => i % 5 === 4)
  return (
    <Card title="Home and debt">
      <p className="text-sm">
        Home {usd(d.home_value)} · mortgage {usd(d.mortgage_balance)} · equity {usd(d.equity)} (appreciation {(d.defaults.appreciation * 100).toFixed(1)}%/yr
        assumed)
      </p>
      {rows.length > 0 && (
        <table className="mt-2 w-full text-sm">
          <thead className="text-left text-slate-400">
            <tr>
              <th>Year</th>
              <th className="text-right">Value</th>
              <th className="text-right">Mortgage</th>
              <th className="text-right">Equity</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((x) => (
              <tr key={x.year}>
                <td>{x.year}</td>
                <td className="text-right">{usd(x.value)}</td>
                <td className="text-right">{usd(x.mortgage)}</td>
                <td className="text-right">{usd(x.equity)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {d.paydown_vs_invest.length > 0 && (
        <ul className="mt-3 space-y-1 text-sm">
          {d.paydown_vs_invest.map((x) => (
            <li key={x.id}>
              <b>{x.name}</b> ({(x.apr * 100).toFixed(2)}%): {x.action.replace('_', ' ').toLowerCase()}
              {x.pay_down_amount > 0 ? ` ${usd(x.pay_down_amount)}` : ''} — {x.reason}
            </li>
          ))}
        </ul>
      )}
      <div className="mt-3 flex flex-wrap gap-4 text-sm">
        <label>
          Downsize to a home costing{' '}
          <input type="number" className="w-28 border-b bg-transparent" value={newHome || ''} onChange={(e) => setNewHome(Number(e.target.value))} />
        </label>
        <label>
          Cost-of-living index there (current = 100){' '}
          <input type="number" className="w-20 border-b bg-transparent" value={col || ''} onChange={(e) => setCol(Number(e.target.value))} />
        </label>
      </div>
      {d.downsize && (
        <p className="mt-2 text-sm">
          Sale nets {usd(d.downsize.net_proceeds)} after {usd(d.downsize.selling_costs)} costs and {usd(d.downsize.tax)} tax (taxable gain{' '}
          {usd(d.downsize.taxable_gain)} over the {usd(d.downsize.exclusion)} exclusion). Cash freed after buying: <b>{usd(d.downsize.cash_freed)}</b>; upkeep{' '}
          {d.downsize.upkeep_change_annual >= 0 ? '+' : ''}
          {usd(d.downsize.upkeep_change_annual)}/yr.
        </p>
      )}
      {d.relocation && (
        <p className="mt-2 text-sm">
          Relocating changes spending by {usd(d.relocation.spend_change)}/yr and state tax by {usd(d.relocation.state_tax_change)}/yr: net saving{' '}
          {usd(d.relocation.annual_saving)}/yr.
        </p>
      )}
    </Card>
  )
}
