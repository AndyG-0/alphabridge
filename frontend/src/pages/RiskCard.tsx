import { api } from '../api/client'
import { Card, Err, pct, usd } from '../components/ui'
import { useAsync } from '../hooks'

const tint = (c: number) => (c >= 0 ? `rgba(56,189,248,${Math.min(c, 1) * 0.5})` : `rgba(248,113,113,${Math.min(-c, 1) * 0.5})`)

export default function RiskCard() {
  const rk = useAsync(api.risk, [])
  if (rk.error) return <Err error={rk.error} />
  if (!rk.data) return null
  const d = rk.data
  const r = d.risk
  const names = d.correlation ? Object.keys(d.correlation) : []
  return (
    <Card title="Risk">
      {d.total <= 0 ? (
        <p className="text-sm text-slate-400">{d.notes[0]}</p>
      ) : (
        <div className="space-y-4 text-sm">
          {r && (
            <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
              <div>
                <div className="text-xs text-slate-400">Volatility (yr)</div>
                <div className="text-lg">{pct(r.volatility)}</div>
              </div>
              <div>
                <div className="text-xs text-slate-400">Max drawdown</div>
                <div className="text-lg">{pct(r.max_drawdown)}</div>
              </div>
              <div>
                <div className="text-xs text-slate-400">1-day VaR {pct(r.confidence, 0)}</div>
                <div className="text-lg">{usd(r.var_1d_dollars)}</div>
              </div>
              <div>
                <div className="text-xs text-slate-400">1-day CVaR</div>
                <div className="text-lg">{usd(r.cvar_1d_dollars)}</div>
              </div>
              <div>
                <div className="text-xs text-slate-400">Beta vs SPY</div>
                <div className="text-lg">{r.beta == null ? '—' : r.beta.toFixed(2)}</div>
              </div>
            </div>
          )}
          {d.coverage && (d.coverage.unpriced.length > 0 || d.coverage.proxied.length > 0) && (
            <p className="text-xs text-slate-500">
              {pct(d.coverage.priced_pct, 0)} of the portfolio priced
              {d.coverage.proxied.length > 0 && ` · proxies: ${d.coverage.proxied.join(', ')}`}
              {d.coverage.unpriced.length > 0 && ` · no history for ${d.coverage.unpriced.join(', ')}`}
            </p>
          )}

          {d.contribution && d.contribution.length > 0 && (
            <div>
              <h3 className="font-medium text-slate-300">Where the risk comes from</h3>
              {d.contribution.slice(0, 8).map((c) => (
                <div key={c.symbol} className="flex items-center gap-2 text-xs">
                  <span className="w-16">{c.symbol}</span>
                  <div className="h-2 flex-1 rounded bg-slate-800">
                    <div className="h-2 rounded bg-sky-500" style={{ width: `${Math.max(0, Math.min(c.risk_share, 1)) * 100}%` }} />
                  </div>
                  <span className="w-24 text-right">
                    {pct(c.risk_share, 0)} of risk · {pct(c.weight, 0)} weight
                  </span>
                </div>
              ))}
            </div>
          )}

          {names.length >= 2 && d.correlation && (
            <div tabIndex={0} role="region" aria-label="Scrollable table" className="overflow-x-auto">
              <h3 className="font-medium text-slate-300">Correlation</h3>
              <table className="text-xs">
                <thead>
                  <tr>
                    <th />
                    {names.map((n) => (
                      <th key={n} className="px-2 font-normal text-slate-400">
                        {n}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {names.map((a) => (
                    <tr key={a}>
                      <th className="pr-2 text-left font-normal text-slate-400">{a}</th>
                      {names.map((b) => (
                        <td key={b} className="px-2 py-0.5 text-center" style={{ background: tint(d.correlation![a][b]) }}>
                          {d.correlation![a][b].toFixed(2)}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          <div>
            <h3 className="font-medium text-slate-300">Historical stress tests on your holdings</h3>
            <table className="w-full text-xs">
              <thead className="text-left text-slate-400">
                <tr>
                  <th>Scenario</th>
                  <th className="text-right">Your portfolio</th>
                  <th className="text-right">S&amp;P 500</th>
                  <th className="text-right">Bonds</th>
                </tr>
              </thead>
              <tbody>
                {d.stress.map((s) => (
                  <tr key={s.id}>
                    <td>{s.label}</td>
                    <td className="text-right">
                      {pct(s.portfolio_return)} ({usd(s.portfolio_change)})
                    </td>
                    <td className="text-right">{pct(s.benchmark.stocks)}</td>
                    <td className="text-right">{pct(s.benchmark.bonds)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="mt-1 text-xs text-slate-500">
              Calendar-year index returns applied to each asset class (sectors and single stocks scaled up). Real drawdowns inside a year were deeper.
            </p>
          </div>
          {d.notes.map((n) => (
            <p key={n} className="text-xs text-slate-500">
              {n}
            </p>
          ))}
        </div>
      )}
    </Card>
  )
}
