import { useRef, useState } from 'react'
import { api } from '../api/client'
import { Button, Card, Err } from '../components/ui'
import { useAsync } from '../hooks'

const usd = (n: number) => `$${Math.round(n).toLocaleString()}`

export default function SpendingCard() {
  const actuals = useAsync(api.spendingActuals, [])
  const pending = useAsync(api.spendingUncategorized, [])
  const [err, setErr] = useState<unknown>(null)
  const [msg, setMsg] = useState('')
  const file = useRef<HTMLInputElement>(null)
  const a = actuals.data
  const reloadAll = () => {
    actuals.reload()
    pending.reload()
  }
  const act = async (fn: () => Promise<unknown>, ok: string) => {
    setErr(null)
    try {
      await fn()
      setMsg(ok)
      reloadAll()
    } catch (e) {
      setErr(e)
    }
  }
  const tx = pending.data?.transactions ?? []
  const suggested = tx.filter((t) => t.suggested_category)
  return (
    <Card title="Spending actuals">
      <Err error={err ?? actuals.error} />
      {a && a.months_used.length > 0 ? (
        <div className="space-y-2 text-sm">
          <p>
            Measured <b>{usd(a.measured_monthly_avg)}</b>/mo over {a.months_used.length} full months vs plan <b>{usd(a.plan_monthly)}</b>/mo (
            {a.difference >= 0 ? '+' : ''}
            {usd(a.difference)}).
          </p>
          {a.lifestyle_creep.flag && <p className="text-amber-400">Lifestyle creep: {a.lifestyle_creep.reason ?? 'recent spending is above your baseline'}</p>}
          <ul className="grid grid-cols-2 gap-x-4 text-xs text-slate-400 md:grid-cols-3">
            {Object.entries(a.by_category_monthly_avg).map(([k, v]) => (
              <li key={k}>
                {k}: {usd(v)}
              </li>
            ))}
          </ul>
          <p className="text-xs text-slate-500">{a.note}</p>
        </div>
      ) : (
        <p className="text-sm text-slate-500">Import a bank or budget-app CSV (Chase, Monarch, Mint, YNAB) to compare real spending with your plan.</p>
      )}
      {tx.length > 0 && (
        <div className="mt-3 text-sm">
          <p className="font-medium">{tx.length} uncategorized</p>
          <ul className="max-h-48 divide-y divide-slate-800 overflow-y-auto text-xs">
            {tx.slice(0, 25).map((t) => (
              <li key={t.id} className="flex items-center justify-between gap-2 py-1">
                <span className="truncate">
                  {t.date} {t.description} ({usd(t.amount)})
                </span>
                <select
                  aria-label={`Category for ${t.description}`}
                  className="rounded bg-slate-900 px-1"
                  value={t.suggested_category}
                  onChange={(e) => act(() => api.setSpendingCategory(t.id, e.target.value), 'Category saved')}
                >
                  <option value="">{t.suggested_category ? `suggested: ${t.suggested_category}` : 'choose…'}</option>
                  {pending.data?.categories.map((c) => (
                    <option key={c} value={c}>
                      {c}
                    </option>
                  ))}
                </select>
              </li>
            ))}
          </ul>
        </div>
      )}
      <div className="mt-3 flex flex-wrap gap-2">
        <input
          ref={file}
          type="file"
          accept=".csv"
          hidden
          onChange={(e) => e.target.files?.[0] && act(async () => api.importSpending(e.target.files![0]), 'Imported')}
        />
        <Button variant="ghost" onClick={() => file.current?.click()}>
          Import transactions
        </Button>
        {tx.length > 0 && (
          <Button variant="ghost" onClick={() => act(api.suggestSpending, 'AI suggestions added: review and confirm')}>
            Suggest categories (AI)
          </Button>
        )}
        {suggested.length > 0 && (
          <Button variant="ghost" onClick={() => act(() => api.confirmSpending(suggested.map((t) => t.id)), 'Suggestions confirmed')}>
            Confirm {suggested.length} suggestions
          </Button>
        )}
        {a && a.months_used.length > 0 && (
          <Button variant="ghost" onClick={() => act(api.applySpendingToPlan, 'Plan expenses updated to measured average')}>
            Use measured spend in plan
          </Button>
        )}
      </div>
      {msg && <p className="mt-2 text-xs text-slate-400">{msg}</p>}
    </Card>
  )
}
