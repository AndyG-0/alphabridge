import { useState } from 'react'
import { api, type LotSale } from '../api/client'
import { Card, Err, pct, usd } from '../components/ui'
import { useAsync } from '../hooks'

export default function TaxLotsCard() {
  const [tick, setTick] = useState(0)
  const rep = useAsync(api.taxLots, [tick])
  const pf = useAsync(api.portfolio, [])
  const [acct, setAcct] = useState('')
  const [msg, setMsg] = useState('')
  const [err, setErr] = useState<unknown>(null)
  const [sym, setSym] = useState('')
  const [amt, setAmt] = useState('')
  const [sale, setSale] = useState<LotSale | null>(null)

  if (rep.error) return <Err error={rep.error} />
  if (!rep.data) return null
  const d = rep.data
  const taxable = (pf.data?.accounts ?? []).filter((a) => a.tax_bucket === 'TAXABLE_BROKERAGE')

  async function upload(f: File | undefined) {
    if (!f || !acct) return
    try {
      const r = await api.importLots(f, Number(acct))
      setMsg(`Imported ${r.lots} lots${r.row_errors.length ? `; skipped ${r.row_errors.length} bad rows` : ''}.`)
      setErr(null)
      setTick((t) => t + 1)
    } catch (e) {
      setErr(e)
    }
  }

  async function plan() {
    try {
      setSale(await api.lotSale(sym.trim(), Number(amt)))
      setErr(null)
    } catch (e) {
      setErr(e)
    }
  }

  return (
    <Card title="Tax lots & harvesting">
      {d.lots === 0 ? (
        <p className="text-sm text-slate-400">{d.notes[0]}</p>
      ) : (
        <div className="space-y-3 text-sm">
          {d.harvest && (
            <div>
              <h3 className="font-medium text-slate-300">
                Loss harvest · {usd(d.harvest.total_loss)} of losses · ~{usd(d.harvest.total_est_savings)} federal tax saved
              </h3>
              {d.harvest.candidates.length === 0 && <p className="text-xs text-slate-400">No taxable lots with a harvestable loss right now.</p>}
              {d.harvest.candidates.slice(0, 6).map((c) => (
                <p key={c.id} className="text-xs">
                  {c.symbol} lot from {c.acquired} ({c.term === 'LONG' ? 'long' : 'short'}-term) · loss {usd(c.loss)} · saves ~{usd(c.est_tax_savings)} at{' '}
                  {pct(c.rate, 0)}
                  {c.alternatives.length > 0 && <span className="text-slate-400"> · swap into {c.alternatives.slice(0, 3).join(' / ')}</span>}
                </p>
              ))}
              {d.harvest.blocked_by_wash_sale.map((c) => (
                <p key={c.id} className="text-xs text-amber-300">
                  {c.symbol} loss {usd(c.loss)} blocked: {c.wash_conflicts[0].symbol} bought {c.wash_conflicts[0].acquired} in {c.wash_conflicts[0].account}
                </p>
              ))}
              <p className="mt-1 text-xs text-slate-500">{d.harvest.note}</p>
            </div>
          )}
          {d.gain_harvest && (
            <div>
              <h3 className="font-medium text-slate-300">0% gain harvest · {usd(d.gain_harvest.headroom)} of headroom</h3>
              {d.gain_harvest.picks.slice(0, 4).map((p) => (
                <p key={p.lot_id} className="text-xs">
                  Sell {p.shares.toFixed(2)} {p.symbol} to realize {usd(p.gain)}
                </p>
              ))}
              <p className="mt-1 text-xs text-slate-500">{d.gain_harvest.note}</p>
            </div>
          )}
          {d.upcoming_long_term && d.upcoming_long_term.length > 0 && (
            <p className="text-xs text-slate-400">
              Turning long-term soon:{' '}
              {d.upcoming_long_term
                .slice(0, 4)
                .map((l) => `${l.symbol} in ${l.days_to_long_term}d (${usd(l.gain)} gain)`)
                .join(', ')}
            </p>
          )}
        </div>
      )}
      {d.missing_lots.length > 0 && <p className="mt-2 text-xs text-slate-500">No lot data yet for: {d.missing_lots.join(', ')}</p>}

      <div className="mt-4 flex flex-wrap items-end gap-2 text-sm">
        <label className="text-xs text-slate-400">
          Import lots into
          <select value={acct} onChange={(e) => setAcct(e.target.value)} className="mt-1 block rounded bg-slate-800 px-2 py-1">
            <option value="">choose account</option>
            {taxable.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
              </option>
            ))}
          </select>
        </label>
        <input type="file" accept=".csv" aria-label="Lot export" disabled={!acct} onChange={(e) => upload(e.target.files?.[0])} className="text-xs" />
        {msg && <span className="text-xs text-emerald-400">{msg}</span>}
      </div>

      <div className="mt-3 flex flex-wrap items-end gap-2 text-sm">
        <label className="text-xs text-slate-400">
          Symbol
          <input value={sym} onChange={(e) => setSym(e.target.value)} className="mt-1 block w-24 rounded bg-slate-800 px-2 py-1" />
        </label>
        <label className="text-xs text-slate-400">
          Raise ($)
          <input value={amt} onChange={(e) => setAmt(e.target.value)} inputMode="decimal" className="mt-1 block w-28 rounded bg-slate-800 px-2 py-1" />
        </label>
        <button onClick={plan} disabled={!sym.trim() || !Number(amt)} className="rounded bg-sky-600 text-white px-3 py-1 disabled:opacity-40">
          Which lots to sell?
        </button>
      </div>
      {sale && (
        <div className="mt-2 text-xs">
          {sale.picks.map((p) => (
            <p key={p.lot_id}>
              {p.shares.toFixed(2)} sh from {p.acquired} ({p.term.toLowerCase()}) · {usd(p.proceeds)} · gain {usd(p.gain)}
            </p>
          ))}
          <p className="text-slate-400">
            Raises {usd(sale.raised)} · realized gain {usd(sale.total_gain)} · est. tax {usd(sale.est_tax)}
            {sale.shortfall > 0 && ` · ${usd(sale.shortfall)} short (not enough taxable lots)`}
          </p>
        </div>
      )}
      {err != null && <Err error={err} />}
    </Card>
  )
}
