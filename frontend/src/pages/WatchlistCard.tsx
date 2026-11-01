import { useState } from 'react'
import { api, type Criterion } from '../api/client'
import { Badge, Button, Card, Err, Input, usd } from '../components/ui'
import { useAsync } from '../hooks'

const METRICS = ['price', 'revenue_growth', 'operating_margin', 'debt_to_equity', 'free_cash_flow', 'trailing_pe', 'drawdown_from_high']

export default function WatchlistCard() {
  const [tick, setTick] = useState(0)
  const wl = useAsync(api.watchlist, [tick])
  const th = useAsync(api.theses, [tick])
  const [err, setErr] = useState<unknown>(null)
  const [w, setW] = useState({ symbol: '', buy_below: '' })
  const [t, setT] = useState({ symbol: '', thesis: '', metric: 'revenue_growth', op: '<', value: '', text: '' })

  async function run(fn: () => Promise<unknown>) {
    try {
      await fn()
      setErr(null)
      setTick((x) => x + 1)
    } catch (e) {
      setErr(e)
    }
  }

  return (
    <Card title="Watchlist & theses">
      <div className="space-y-4 text-sm">
        <Err error={err} />
        <Err error={wl.error} />
        <div className="grid gap-2 md:grid-cols-[1fr_1fr_auto] md:items-end">
          <Input label="Watch ticker" value={w.symbol} onChange={(e) => setW({ ...w, symbol: e.target.value.toUpperCase() })} />
          <Input label="Alert when price ≤" type="number" value={w.buy_below} onChange={(e) => setW({ ...w, buy_below: e.target.value })} />
          <Button
            disabled={!w.symbol}
            onClick={() =>
              run(async () => {
                await api.addWatch({ symbol: w.symbol, buy_below: w.buy_below ? Number(w.buy_below) : null })
                setW({ symbol: '', buy_below: '' })
              })
            }
          >
            Add
          </Button>
        </div>
        {wl.data && wl.data.length === 0 && <p className="text-slate-400">Nothing on the watchlist yet.</p>}
        {wl.data?.map((r) => (
          <div key={r.id} className="flex flex-wrap items-center gap-2 border-t border-slate-800 pt-2">
            <b className="font-mono">{r.symbol}</b>
            <span>{r.price ? usd(r.price) : '—'}</span>
            <span className="text-slate-400">DCF {r.dcf_value ? usd(r.dcf_value) : '—'}</span>
            {r.buy_below && <span className="text-slate-400">buy ≤ {usd(r.buy_below)}</span>}
            {r.alerts.map((a) => (
              <Badge key={a} tone="green">
                {a}
              </Badge>
            ))}
            <button className="ml-auto text-xs text-slate-400 hover:text-slate-200" onClick={() => run(() => api.deleteWatch(r.id))}>
              Remove
            </button>
          </div>
        ))}

        <div className="border-t border-slate-800 pt-3">
          <h3 className="font-medium text-slate-300">Thesis tracker</h3>
          <div className="grid gap-2 md:grid-cols-2">
            <Input label="Ticker" value={t.symbol} onChange={(e) => setT({ ...t, symbol: e.target.value.toUpperCase() })} />
            <Input label="Why you own / watch it" value={t.thesis} onChange={(e) => setT({ ...t, thesis: e.target.value })} />
            <label className="block text-sm text-slate-300">
              Invalidated if
              <div className="mt-1 flex gap-2">
                <select aria-label="Metric" className="rounded-xl bg-slate-900 p-2" value={t.metric} onChange={(e) => setT({ ...t, metric: e.target.value })}>
                  {METRICS.map((m) => (
                    <option key={m}>{m}</option>
                  ))}
                </select>
                <select aria-label="Operator" className="rounded-xl bg-slate-900 p-2" value={t.op} onChange={(e) => setT({ ...t, op: e.target.value })}>
                  {['<', '<=', '>', '>='].map((o) => (
                    <option key={o}>{o}</option>
                  ))}
                </select>
                <input
                  aria-label="Value"
                  type="number"
                  step="any"
                  className="w-24 rounded-xl bg-slate-900 p-2"
                  value={t.value}
                  onChange={(e) => setT({ ...t, value: e.target.value })}
                />
              </div>
            </label>
            <Input label="Plain-English reason" value={t.text} onChange={(e) => setT({ ...t, text: e.target.value })} />
          </div>
          <Button
            className="mt-2"
            disabled={!t.symbol || !t.thesis || t.value === ''}
            onClick={() =>
              run(async () => {
                const c: Criterion = { metric: t.metric, op: t.op, value: Number(t.value), text: t.text }
                await api.addThesis({ symbol: t.symbol, thesis: t.thesis, criteria: [c] })
                setT({ ...t, symbol: '', thesis: '', value: '', text: '' })
              })
            }
          >
            Track thesis
          </Button>
          {th.data?.map((r) => (
            <div key={r.id} className="mt-3 border-t border-slate-800 pt-2">
              <div className="flex flex-wrap items-center gap-2">
                <b className="font-mono">{r.symbol}</b>
                <Badge tone={r.status === 'INVALIDATED' || r.broken.length ? 'red' : 'green'}>
                  {r.broken.length && r.status === 'ACTIVE' ? 'BROKEN' : r.status}
                </Badge>
                <span className="text-slate-300">{r.thesis}</span>
                {r.status === 'ACTIVE' && (
                  <button className="ml-auto text-xs text-slate-400 hover:text-slate-200" onClick={() => run(() => api.closeThesis(r.id))}>
                    Close
                  </button>
                )}
              </div>
              <ul className="text-xs text-slate-400">
                {r.criteria.map((c, i) => (
                  <li key={i} className={c.triggered ? 'text-red-300' : ''}>
                    {c.text || c.metric} — {c.metric} {c.op} {c.value}
                    {c.current != null && ` (now ${Number(c.current).toLocaleString('en-US', { maximumFractionDigits: 3 })})`}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      </div>
    </Card>
  )
}
