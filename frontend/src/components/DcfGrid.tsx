import { api } from '../api/client'
import { pct, usd } from './ui'
import { useAsync } from '../hooks'

export default function DcfGrid({ symbol }: { symbol: string }) {
  const g = useAsync(() => api.dcf(symbol), [symbol])
  if (!g.data) return null
  const d = g.data
  return (
    <div className="mt-3 overflow-x-auto text-xs">
      <div className="mb-1 text-slate-400">
        DCF range {usd(d.low)}–{usd(d.high)} across growth × discount rate
        {d.share_of_cells_above_price != null && ` · ${pct(d.share_of_cells_above_price, 0)} of cases are above today’s price`}
      </div>
      <table>
        <thead>
          <tr>
            <th className="pr-2 text-left font-normal text-slate-400">growth \ discount</th>
            {d.discounts.map((x) => (
              <th key={x} className="px-2 font-normal text-slate-400">
                {pct(x, 0)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {d.rows.map((r) => (
            <tr key={r.growth}>
              <th className="pr-2 text-left font-normal text-slate-400">{pct(r.growth, 0)}</th>
              {r.values.map((v, i) => (
                <td key={i} className={`px-2 py-0.5 text-right ${d.price != null && v != null && v > d.price ? 'text-emerald-400' : 'text-slate-300'}`}>
                  {v == null ? '—' : usd(v)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
