import { useState } from 'react'
import { api, type GoalBasis, type SpendingGoal, type SpendingGoalInput } from '../api/client'
import { Badge, Button, Card, Err, Input, usd } from '../components/ui'
import { useAsync } from '../hooks'

const BLANK: SpendingGoalInput = {
  name: '',
  category: 'other',
  annual_amount: 0,
  start_basis: 'YEARS_AFTER_RETIREMENT',
  start_value: 0,
  end_basis: 'YEARS_AFTER_RETIREMENT',
  end_value: null,
  owner: 'SELF',
  real_inflation: 0,
  smile_applies: true,
  enabled: true,
  note: '',
  sort_order: 0,
}

export const windowText = (g: Pick<SpendingGoalInput, 'start_basis' | 'start_value' | 'end_basis' | 'end_value'>) => {
  const part = (b: GoalBasis, v: number) => (b === 'AGE' ? `age ${v}` : v === 0 ? 'retirement' : `${v} yr after retirement`)
  return g.end_value == null ? `from ${part(g.start_basis, g.start_value)} on` : `${part(g.start_basis, g.start_value)} to ${part(g.end_basis, g.end_value)}`
}

const BasisSelect = ({ label, value, onChange }: { label: string; value: GoalBasis; onChange: (b: GoalBasis) => void }) => (
  <label className="block text-sm text-slate-300">
    {label}
    <select className="block w-full bg-transparent border-b" value={value} onChange={(e) => onChange(e.target.value as GoalBasis)}>
      <option value="YEARS_AFTER_RETIREMENT">Years after retirement</option>
      <option value="AGE">Age</option>
    </select>
  </label>
)

export default function SpendingGoalsCard() {
  const r = useAsync(api.spendingGoals, [])
  const presets = useAsync(api.spendingGoalPresets, [])
  const impact = useAsync(api.spendingGoalsImpact, [])
  const [form, setForm] = useState<(SpendingGoalInput & { id?: number }) | null>(null)
  const [err, setErr] = useState<unknown>(null)
  const goals = r.data?.goals ?? []
  const cost = (g: SpendingGoal) => r.data?.costs.find((c) => c.id === g.id)
  const act = async (fn: () => Promise<unknown>) => {
    setErr(null)
    try {
      await fn()
      r.reload()
      impact.reload()
    } catch (e) {
      setErr(e)
    }
  }
  const set = <K extends keyof SpendingGoalInput>(k: K, v: SpendingGoalInput[K]) => setForm((f) => (f ? { ...f, [k]: v } : f))
  const save = () =>
    form &&
    act(async () => {
      const { id, ...body } = form
      await (id ? api.saveSpendingGoal(id, body) : api.addSpendingGoal(body))
      setForm(null)
    })
  const imp = impact.data

  return (
    <Card title="Retirement goals: travel, hobbies, family, home">
      <Err error={err ?? r.error} />
      <p className="mb-2 text-xs text-slate-400">
        Recurring costs on top of your base retirement budget, in today&apos;s dollars. They run through the Monte Carlo, so the plan shows whether you can
        afford them.
      </p>
      {imp?.has_goals && imp.success_rate_with != null && imp.success_rate_without != null && (
        <p className="mb-2 text-sm">
          Plan success: <b>{Math.round(imp.success_rate_with * 100)}%</b> with these goals vs {Math.round(imp.success_rate_without * 100)}% without
          {imp.target_success_rate != null && imp.success_rate_with < imp.target_success_rate && <> </>}
          {imp.target_success_rate != null && imp.success_rate_with < imp.target_success_rate && (
            <Badge tone="amber">below your {Math.round(imp.target_success_rate * 100)}% target</Badge>
          )}
        </p>
      )}
      <ul className="divide-y divide-slate-800 text-sm">
        {goals.map((g) => {
          const c = cost(g)
          return (
            <li key={g.id} className="flex flex-wrap items-center justify-between gap-2 py-2">
              <div>
                <b>{g.name}</b> {usd(g.annual_amount)}/yr {!g.enabled && <Badge>off</Badge>}
                <div className="text-xs text-slate-400">
                  {windowText(g)}
                  {g.owner !== 'SELF' && ` · ${g.owner === 'SPOUSE' ? 'spouse age' : 'household'}`}
                  {g.smile_applies && ' · tapers with age'}
                  {c && c.enabled && ` · ${usd(c.lifetime_real)} lifetime (today's $)`}
                </div>
              </div>
              <div className="flex gap-2">
                <Button variant="ghost" onClick={() => act(() => api.saveSpendingGoal(g.id, { ...g, enabled: !g.enabled }))}>
                  {g.enabled ? 'Turn off' : 'Turn on'}
                </Button>
                <Button variant="ghost" onClick={() => setForm({ ...g })}>
                  Edit
                </Button>
                <Button variant="ghost" onClick={() => window.confirm(`Delete ${g.name}?`) && act(() => api.deleteSpendingGoal(g.id))}>
                  Delete
                </Button>
              </div>
            </li>
          )
        })}
      </ul>
      {r.data && goals.length > 0 && (
        <p className="mt-2 text-xs text-slate-400">Total lifetime cost of enabled goals: {usd(r.data.lifetime_real)} in today&apos;s dollars.</p>
      )}
      {!form && (
        <div className="mt-3 flex flex-wrap gap-2">
          {Object.entries(presets.data?.presets ?? {}).map(([k, p]) => (
            <Button key={k} variant="ghost" onClick={() => setForm({ ...BLANK, ...p })}>
              Add {p.name}
            </Button>
          ))}
          <Button onClick={() => setForm({ ...BLANK })}>Add custom goal</Button>
        </div>
      )}
      {presets.data && !presets.data.verified && !form && (
        <p className="mt-1 text-xs text-amber-300">Preset amounts are illustrative placeholders; replace them with your own estimates.</p>
      )}
      {form && (
        <div className="mt-3 grid gap-2 md:grid-cols-2">
          <Input label="Name" value={form.name} onChange={(e) => set('name', e.target.value)} />
          <Input label="Amount per year (today's $)" type="number" value={form.annual_amount} onChange={(e) => set('annual_amount', Number(e.target.value))} />
          <BasisSelect label="Starts" value={form.start_basis} onChange={(b) => set('start_basis', b)} />
          <Input label="Start value" type="number" value={form.start_value} onChange={(e) => set('start_value', Number(e.target.value))} />
          <BasisSelect label="Ends" value={form.end_basis} onChange={(b) => set('end_basis', b)} />
          <Input
            label="End value (blank = rest of plan)"
            type="number"
            value={form.end_value ?? ''}
            onChange={(e) => set('end_value', e.target.value === '' ? null : Number(e.target.value))}
          />
          <label className="block text-sm text-slate-300">
            Whose age
            <select
              className="block w-full bg-transparent border-b"
              value={form.owner}
              onChange={(e) => set('owner', e.target.value as SpendingGoalInput['owner'])}
            >
              <option value="SELF">You</option>
              <option value="SPOUSE">Spouse</option>
              <option value="JOINT">Household (your age)</option>
            </select>
          </label>
          <Input
            label="Extra yearly inflation (%)"
            type="number"
            value={Math.round(form.real_inflation * 10000) / 100}
            onChange={(e) => set('real_inflation', Number(e.target.value) / 100)}
          />
          <label className="flex items-center gap-2 text-sm text-slate-300">
            <input type="checkbox" checked={form.smile_applies} onChange={(e) => set('smile_applies', e.target.checked)} />
            Taper in later years (go-go / slow-go / no-go)
          </label>
          <div className="flex gap-2 md:col-span-2">
            <Button onClick={save}>Save</Button>
            <Button variant="ghost" onClick={() => setForm(null)}>
              Cancel
            </Button>
          </div>
        </div>
      )}
    </Card>
  )
}
