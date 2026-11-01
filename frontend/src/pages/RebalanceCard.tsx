import { useState } from 'react'
import { api } from '../api/client'
import { Card, Err, pct, usd } from '../components/ui'
import { useAsync } from '../hooks'

const CLASSES = ['US_EQUITY', 'INTL_EQUITY', 'SECTOR_ETF', 'INDIVIDUAL_STOCK', 'BOND', 'MONEY_MARKET']
const label = (k: string) => k.replaceAll('_', ' ').toLowerCase()

export default function RebalanceCard() {
  const [tick, setTick] = useState(0)
  const rb = useAsync(api.rebalance, [tick])
  const [edit, setEdit] = useState<Record<string, string> | null>(null)
  const [err, setErr] = useState<unknown>(null)

  if (rb.error) return <Err error={rb.error} />
  if (!rb.data) return null
  const d = rb.data
  const sum = edit ? Object.values(edit).reduce((a, v) => a + (Number(v) || 0), 0) : 0

  async function save() {
    if (!edit) return
    try {
      const alloc: Record<string, number> = {}
      for (const [k, v] of Object.entries(edit)) if (Number(v) > 0) alloc[k] = Number(v) / 100
      await api.saveProfile({ target_allocation: alloc })
      setEdit(null)
      setErr(null)
      setTick((t) => t + 1)
    } catch (e) {
      setErr(e)
    }
  }

  return (
    <Card title="Rebalance & asset location">
      {!d.has_target || !d.drift ? (
        <p className="text-sm text-slate-400">{d.notes[0]}</p>
      ) : (
        <div className="space-y-3 text-sm">
          <p className={d.drift.breached ? 'text-amber-300' : 'text-emerald-400'}>
            {d.drift.breached
              ? `Drift is past ${pct(d.drift.threshold, 0)} on at least one class; ${pct(d.drift.total_drift)} of the portfolio needs to move.`
              : `Within ${pct(d.drift.threshold, 0)} of target everywhere.`}
          </p>
          <table className="w-full text-xs">
            <thead className="text-left text-slate-400">
              <tr>
                <th>Class</th>
                <th className="text-right">Now</th>
                <th className="text-right">Target</th>
                <th className="text-right">Move</th>
              </tr>
            </thead>
            <tbody>
              {d.drift.rows.map((r) => (
                <tr key={r.asset_class} className={r.breach ? 'text-amber-300' : ''}>
                  <td className="capitalize">{label(r.asset_class)}</td>
                  <td className="text-right">{pct(r.current)}</td>
                  <td className="text-right">{pct(r.target)}</td>
                  <td className="text-right">
                    {r.dollars >= 0 ? '+' : '−'}
                    {usd(Math.abs(r.dollars))}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {d.trades && d.trades.length > 0 && (
            <div>
              <h3 className="font-medium text-slate-300">Trades (each account funds its own buys)</h3>
              {d.trades.map((t, i) => (
                <div key={i} className="flex justify-between text-xs">
                  <span>
                    <span className={t.action === 'BUY' ? 'text-emerald-400' : 'text-rose-400'}>{t.action}</span> {t.symbol} · {t.account}
                  </span>
                  <span>
                    {usd(t.amount)}
                    {t.realized_gain !== 0 && <span className="text-slate-400"> (gain {usd(t.realized_gain)})</span>}
                  </span>
                </div>
              ))}
              <p className="mt-1 text-xs text-slate-400">
                Realized gains {usd(d.realized_gains ?? 0)} · est. federal tax {usd(d.est_tax ?? 0)} · drift after trades {pct(d.after?.total_drift)}
              </p>
            </div>
          )}
          {d.unresolved && (Object.keys(d.unresolved.sell).length > 0 || Object.keys(d.unresolved.buy).length > 0) && (
            <p className="text-xs text-slate-400">
              Left over (no account can trade it without moving cash):{' '}
              {Object.entries({ ...d.unresolved.sell, ...d.unresolved.buy })
                .map(([k, v]) => `${label(k)} ${usd(v)}`)
                .join(', ')}
              . Direct new contributions there.
            </p>
          )}
        </div>
      )}

      {d.asset_location.suggestions.length > 0 && (
        <div className="mt-4 text-sm">
          <h3 className="font-medium text-slate-300">Asset location</h3>
          {d.asset_location.suggestions.slice(0, 5).map((s) => (
            <p key={`${s.account}-${s.symbol}`} className="text-xs">
              {s.symbol} ({usd(s.value)}) in {s.account} fits better in {s.to_bucket.replaceAll('_', ' ').toLowerCase()}
              {s.est_annual_tax_drag > 0 && <span className="text-slate-400"> · ~{usd(s.est_annual_tax_drag)}/yr tax drag</span>}
            </p>
          ))}
          <p className="mt-1 text-xs text-slate-500">{d.asset_location.note}</p>
        </div>
      )}

      <div className="mt-4 text-sm">
        {edit ? (
          <div className="space-y-2">
            <div className="grid grid-cols-2 gap-2 md:grid-cols-3">
              {CLASSES.map((c) => (
                <label key={c} className="text-xs capitalize text-slate-400">
                  {label(c)} %
                  <input
                    value={edit[c] ?? ''}
                    onChange={(e) => setEdit({ ...edit, [c]: e.target.value })}
                    inputMode="decimal"
                    className="mt-1 block w-full rounded bg-slate-800 px-2 py-1"
                  />
                </label>
              ))}
            </div>
            <div className="flex items-center gap-3">
              <button onClick={save} disabled={Math.abs(sum - 100) > 1} className="rounded bg-sky-600 text-white px-3 py-1 disabled:opacity-40">
                Save target
              </button>
              <button onClick={() => setEdit(null)} className="text-xs text-slate-400">
                Cancel
              </button>
              <span className={`text-xs ${Math.abs(sum - 100) > 1 ? 'text-amber-300' : 'text-slate-400'}`}>Total {sum.toFixed(0)}% (must be 100%)</span>
            </div>
          </div>
        ) : (
          <button
            onClick={() =>
              setEdit(
                Object.fromEntries(
                  CLASSES.map((c) => [c, d.drift ? String(Math.round((d.drift.rows.find((r) => r.asset_class === c)?.target ?? 0) * 100)) : '']),
                ),
              )
            }
            className="text-xs text-sky-400"
          >
            {d.has_target ? 'Edit target allocation' : 'Set target allocation'}
          </button>
        )}
        {err != null && <Err error={err} />}
      </div>
    </Card>
  )
}
