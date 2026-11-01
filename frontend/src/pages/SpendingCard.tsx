import { useState } from 'react'
import { api } from '../api/client'
import { Card, Err, usd } from '../components/ui'
import { useAsync } from '../hooks'

export default function SpendingCard() {
  const [nominal, setNominal] = useState(false)
  const [smile, setSmile] = useState(false)
  const r = useAsync(() => api.spending(nominal, smile), [nominal, smile])
  const d = r.data
  if (r.error) return <Err error={r.error} />
  if (!d || d.base_annual <= 0) return null
  const rows = d.rows.filter((_, i) => i % 5 === 0)
  return (
    <Card title="Retirement spending shape">
      <div className="mb-2 flex gap-4 text-sm">
        <label>
          <input type="checkbox" checked={smile} onChange={(e) => setSmile(e.target.checked)} /> Spending smile (slow down with age)
        </label>
        <label>
          <input type="checkbox" checked={nominal} onChange={(e) => setNominal(e.target.checked)} /> Nominal dollars
        </label>
      </div>
      <table className="w-full text-sm">
        <thead className="text-left text-slate-400">
          <tr>
            <th>Age</th>
            <th>Phase</th>
            <th className="text-right">{nominal ? 'Nominal' : "Today's $"} / yr</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((x) => (
            <tr key={x.age}>
              <td>{x.age}</td>
              <td>{x.phase}</td>
              <td className="text-right">{usd(x.total)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mt-2 text-xs text-slate-500">
        Base spending only; health care is modeled separately. Smile multipliers are illustrative defaults, not research findings.
      </p>
    </Card>
  )
}
