import { api } from '../api/client'
import { Card, Err, pct, usd } from '../components/ui'
import { useAsync } from '../hooks'

function Bars({ title, data }: { title: string; data: Record<string, number> }) {
  const rows = Object.entries(data).slice(0, 8)
  if (!rows.length) return null
  return (
    <div>
      <h3 className="text-sm font-medium text-slate-300">{title}</h3>
      {rows.map(([k, v]) => (
        <div key={k} className="mt-1 text-xs">
          <div className="flex justify-between">
            <span className={k === 'Unclassified' ? 'text-amber-400' : ''}>{k}</span>
            <span>{pct(v, 1)}</span>
          </div>
          <div className="h-1.5 rounded bg-slate-800">
            <div className="h-1.5 rounded bg-emerald-500" style={{ width: `${Math.min(v, 1) * 100}%` }} />
          </div>
        </div>
      ))}
    </div>
  )
}

export default function XRayCard() {
  const x = useAsync(api.xray, [])
  if (x.error) return <Err error={x.error} />
  if (!x.data) return null
  const d = x.data
  const c = d.concentration
  return (
    <Card title="Portfolio X-Ray (look-through)">
      <p className="text-sm text-slate-400">{usd(d.total)} looked through to what it actually owns. Market-cap tiers are shares of your stock dollars.</p>
      {c.warnings.map((w) => (
        <p key={w} className="mt-2 rounded-lg border border-amber-600 p-2 text-sm text-amber-300">
          {w}
        </p>
      ))}
      <div className="mt-3 grid gap-4 md:grid-cols-2">
        <Bars title="Asset class" data={d.asset_class} />
        <Bars title="Sector" data={d.sector} />
        <Bars title="Region" data={d.region} />
        <Bars title="Market cap" data={d.market_cap} />
      </div>
      <h3 className="mt-4 text-sm font-medium text-slate-300">Top underlying names</h3>
      <p className="text-xs text-slate-400">{c.top_names.map((n) => `${n.symbol} ${pct(n.weight, 1)}`).join(' · ') || 'No holdings data.'}</p>
      {c.employer_symbol && (
        <p className="mt-1 text-xs">
          Employer stock {c.employer_symbol}: {pct(c.employer_weight, 1)} of the portfolio
        </p>
      )}
      {d.overlap.length > 0 && (
        <>
          <h3 className="mt-4 text-sm font-medium text-slate-300">Fund overlap (top holdings)</h3>
          <table className="w-full text-xs">
            <tbody>
              {d.overlap.map((o) => (
                <tr key={o.a + o.b}>
                  <td>
                    {o.a} / {o.b}
                  </td>
                  <td className="text-right">{pct(o.overlap, 1)}</td>
                  <td className="text-right text-slate-400">{o.shared} shared</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
      {d.coverage.length > 0 && (
        <p className="mt-3 text-xs text-amber-400">
          Missing look-through data: {d.coverage.map((f) => `${f.symbol} (${f.missing.join(', ')})`).join('; ')}. Shown as Unclassified.
        </p>
      )}
    </Card>
  )
}
