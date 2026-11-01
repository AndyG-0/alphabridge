import { useState } from 'react'
import { api } from '../api/client'
import { Card, Err, usd } from '../components/ui'
import { useAsync } from '../hooks'

export default function AssumptionsCard() {
  const [tick, setTick] = useState(0)
  const list = useAsync(api.assumptions, [tick])
  const health = useAsync(api.planHealth, [tick])
  const [draft, setDraft] = useState<Record<string, string>>({})
  const [err, setErr] = useState<unknown>(null)
  const [fee, setFee] = useState<{ cost: number; cost_pct: number } | null>(null)

  if (list.error) return <Err error={list.error} />
  if (!list.data) return null
  const save = async (reset?: string) => {
    const overrides: Record<string, number | null> = reset ? { [reset]: null } : Object.fromEntries(Object.entries(draft).map(([k, v]) => [k, Number(v)]))
    try {
      await api.saveAssumptions(overrides)
      setDraft({})
      setErr(null)
      setTick((n) => n + 1)
    } catch (e) {
      setErr(e)
    }
  }
  const h = health.data
  return (
    <Card title="Assumptions and plan health">
      {h && (
        <div className="text-sm">
          <p>
            Plan health <b>{h.health.score}/100</b> ({h.health.grade})
          </p>
          <ul className="list-disc pl-5">
            {h.health.parts.map((p) => (
              <li key={p.name}>
                {p.name}: {p.points}/{p.weight} — {p.why}
              </li>
            ))}
          </ul>
          <p className="mt-1 text-slate-400">
            {h.diff.has_previous
              ? `Since the last saved run: ${h.diff.metrics.length} result change(s), ${h.diff.assumptions.length} assumption change(s).`
              : 'No saved run to compare with yet.'}
          </p>
          <button
            className="mt-1 rounded-lg border border-slate-600 px-3 py-1"
            onClick={async () => {
              await api.saveHealthSnapshot()
              setTick((n) => n + 1)
            }}
          >
            Save this run as the reference
          </button>
        </div>
      )}
      <Err error={err} />
      <table className="mt-3 w-full text-sm">
        <tbody>
          {list.data.assumptions.map((a) => (
            <tr key={a.key} title={a.source}>
              <td>{a.label}</td>
              <td className="text-right text-slate-400">default {a.default}</td>
              <td className="text-right">
                <input
                  className="w-20 border-b bg-transparent text-right"
                  type="number"
                  step="0.005"
                  aria-label={a.label}
                  value={draft[a.key] ?? a.value}
                  onChange={(e) => setDraft({ ...draft, [a.key]: e.target.value })}
                />
              </td>
              <td className="w-12 text-right">{a.overridden && <button onClick={() => save(a.key)}>reset</button>}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <button className="mt-2 rounded-lg border border-slate-600 px-3 py-1 text-sm" disabled={!Object.keys(draft).length} onClick={() => save()}>
        Save changes
      </button>
      <div className="mt-3 text-sm">
        <button className="rounded-lg border border-slate-600 px-3 py-1" onClick={async () => setFee(await api.feeDrag(100000, 10000, 30, 0.07, 0.01))}>
          Fee drag: 1% on $100k + $10k/yr for 30 years
        </button>
        {fee && (
          <span className="ml-2">
            costs {usd(fee.cost)} ({(fee.cost_pct * 100).toFixed(0)}% of the ending balance)
          </span>
        )}
      </div>
    </Card>
  )
}
