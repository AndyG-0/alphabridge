import { useState } from 'react'
import { api } from '../api/client'
import { Card, Err, usd } from '../components/ui'
import { useAsync } from '../hooks'

const pct = (x: number) => `${(x * 100).toFixed(0)}%`
const dpts = (x: number | null) => (x === null ? '' : `${x >= 0 ? '+' : ''}${(x * 100).toFixed(1)} pts`)

export default function ScenarioCard() {
  const list = useAsync(api.scenarios, [])
  const [picked, setPicked] = useState<string[]>([])
  const [run, setRun] = useState(0)
  const cmp = useAsync(
    () =>
      run === 0
        ? Promise.resolve(null)
        : api.compareScenarios(
            picked.filter((p) => p.startsWith('#')).map((p) => Number(p.slice(1))),
            picked.filter((p) => !p.startsWith('#')),
          ),
    [run],
  )
  const tor = useAsync(() => (run === 0 ? Promise.resolve(null) : api.tornado()), [run])
  const [kind, setKind] = useState('max_spend')
  const [solveRun, setSolveRun] = useState(0)
  const sol = useAsync(() => (solveRun === 0 ? Promise.resolve(null) : api.solve(kind)), [solveRun])
  if (list.error) return <Err error={list.error} />
  if (!list.data) return null
  const options = [...list.data.presets.map((p) => ({ id: p.name, label: p.label })), ...list.data.saved.map((s) => ({ id: `#${s.id}`, label: s.name }))]
  const toggle = (id: string) => setPicked((cur) => (cur.includes(id) ? cur.filter((x) => x !== id) : [...cur, id]))
  return (
    <Card title="What-if scenarios">
      <div className="flex flex-wrap gap-3 text-sm">
        {options.map((o) => (
          <label key={o.id}>
            <input type="checkbox" checked={picked.includes(o.id)} onChange={() => toggle(o.id)} /> {o.label}
          </label>
        ))}
      </div>
      <button className="mt-2 rounded-lg border border-slate-600 px-3 py-1 text-sm" onClick={() => setRun((n) => n + 1)}>
        Compare and rank sensitivities
      </button>
      <Err error={cmp.error} />
      {cmp.data && (
        <table className="mt-2 w-full text-sm">
          <thead className="text-left text-slate-400">
            <tr>
              <th>Scenario</th>
              <th className="text-right">Success</th>
              <th className="text-right">vs base</th>
              <th className="text-right">Median ending</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>Baseline</td>
              <td className="text-right">{pct(cmp.data.base.success_rate)}</td>
              <td />
              <td className="text-right">{usd(cmp.data.base.median_final_real)}</td>
            </tr>
            {cmp.data.scenarios.map((s) => (
              <tr key={`${s.kind}-${s.name}`}>
                <td>{s.name}</td>
                <td className="text-right">{pct(s.metrics.success_rate)}</td>
                <td className="text-right">{dpts(s.vs_base.success_rate)}</td>
                <td className="text-right">{usd(s.metrics.median_final_real)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {tor.data && (
        <ul className="mt-3 space-y-1 text-sm">
          {tor.data.bars.map((b) => (
            <li key={b.input}>
              <b>{b.input}</b>: {b.low_label} {dpts(b.low_delta)}, {b.high_label} {dpts(b.high_delta)}
            </li>
          ))}
        </ul>
      )}
      <div className="mt-3 flex items-center gap-3 text-sm">
        <select aria-label="Scenario type" className="border-b bg-transparent" value={kind} onChange={(e) => setKind(e.target.value)}>
          <option value="max_spend">Max monthly spend</option>
          <option value="required_savings">Required monthly savings</option>
          <option value="earliest_age">Earliest retirement age</option>
        </select>
        <button className="rounded-lg border border-slate-600 px-3 py-1" onClick={() => setSolveRun((n) => n + 1)}>
          Solve for target success
        </button>
        {sol.data && (
          <span>
            {sol.data.value === null
              ? (sol.data.note ?? 'not reachable')
              : `${sol.data.kind === 'earliest_age' ? sol.data.value : usd(sol.data.value)} (${sol.data.unit}; now ${sol.data.current})`}
          </span>
        )}
      </div>
    </Card>
  )
}
