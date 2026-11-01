import { Check } from 'lucide-react'
import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import type { OnboardingStep, Profile } from '../api/client'
import CompletenessMeter from '../components/CompletenessMeter'
import { Button, Card, Err, Input, pct } from '../components/ui'
import { useAsync } from '../hooks'

const ACCOUNT_TYPES: Record<string, string> = {
  TAXABLE_BROKERAGE: 'Taxable brokerage',
  ROTH: 'Roth IRA',
  PRE_TAX_401K: '401(k) / pre-tax',
  HSA: 'HSA',
  CASH_MMF: 'Cash / money market',
}

const num = (v: string) => (v === '' ? 0 : Number(v))

function HouseholdStep({ p, done }: { p: Profile; done: (patch: Partial<Profile>) => Promise<void> }) {
  const [f, setF] = useState({
    name: p.name === 'Me' ? '' : p.name,
    birth_date: p.birth_date,
    annual_income: String(p.annual_income || ''),
    filing: p.tax_filing_status,
  })
  return (
    <form
      className="space-y-3"
      onSubmit={(e) => {
        e.preventDefault()
        void done({ name: f.name, birth_date: f.birth_date, annual_income: num(f.annual_income), tax_filing_status: f.filing })
      }}
    >
      <Input label="Your first name" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} required />
      <Input label="Birth date" type="date" value={f.birth_date} onChange={(e) => setF({ ...f, birth_date: e.target.value })} required />
      <Input label="Annual income (before tax)" type="number" min={0} value={f.annual_income} onChange={(e) => setF({ ...f, annual_income: e.target.value })} />
      <label className="block text-sm text-slate-300">
        Tax filing status
        <select
          className="mt-1 w-full rounded-xl border border-input bg-background px-3 py-2"
          value={f.filing}
          onChange={(e) => setF({ ...f, filing: e.target.value as Profile['tax_filing_status'] })}
        >
          <option value="SINGLE">Single</option>
          <option value="MFJ">Married filing jointly</option>
        </select>
      </label>
      <p className="text-xs text-slate-500">Spouse details, Social Security and health costs can be added later from the Plan page.</p>
      <Button type="submit">Save and continue</Button>
    </form>
  )
}

function AccountsStep({ count, onAdded }: { count: number; onAdded: () => void }) {
  const [name, setName] = useState('')
  const [bucket, setBucket] = useState('TAXABLE_BROKERAGE')
  const [err, setErr] = useState<unknown>(null)
  return (
    <form
      className="space-y-3"
      onSubmit={(e) => {
        e.preventDefault()
        setErr(null)
        api
          .createAccount({ name, tax_bucket: bucket })
          .then(() => {
            setName('')
            onAdded()
          })
          .catch(setErr)
      }}
    >
      <p className="text-sm text-slate-400">
        {count ? `${count} account${count === 1 ? '' : 's'} added.` : 'Add each account you want planned (401(k), brokerage, IRA, cash).'}
      </p>
      <Input label="Account name" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Fidelity brokerage" required />
      <label className="block text-sm text-slate-300">
        Type
        <select className="mt-1 w-full rounded-xl border border-input bg-background px-3 py-2" value={bucket} onChange={(e) => setBucket(e.target.value)}>
          {Object.entries(ACCOUNT_TYPES).map(([k, v]) => (
            <option key={k} value={k}>
              {v}
            </option>
          ))}
        </select>
      </label>
      <Err error={err} />
      <Button type="submit">Add account</Button>
    </form>
  )
}

function GoalsStep({ p, done }: { p: Profile; done: (patch: Partial<Profile>) => Promise<void> }) {
  const [f, setF] = useState({
    age: String(p.target_retirement_age || ''),
    retire: String(p.monthly_expenses_retirement || ''),
    now: String(p.monthly_expenses_current || ''),
    save: String(p.monthly_contribution || ''),
  })
  return (
    <form
      className="space-y-3"
      onSubmit={(e) => {
        e.preventDefault()
        void done({
          target_retirement_age: num(f.age),
          monthly_expenses_retirement: num(f.retire),
          monthly_expenses_current: num(f.now),
          monthly_contribution: num(f.save),
        })
      }}
    >
      <Input
        label="Age you want to stop working"
        type="number"
        min={30}
        max={80}
        value={f.age}
        onChange={(e) => setF({ ...f, age: e.target.value })}
        required
      />
      <Input
        label="Monthly spending in retirement (today's dollars)"
        type="number"
        min={0}
        value={f.retire}
        onChange={(e) => setF({ ...f, retire: e.target.value })}
        hint="Exclude debt payments; debts are entered separately."
        required
      />
      <Input label="Monthly spending now" type="number" min={0} value={f.now} onChange={(e) => setF({ ...f, now: e.target.value })} />
      <Input label="Monthly savings across all accounts" type="number" min={0} value={f.save} onChange={(e) => setF({ ...f, save: e.target.value })} />
      <Button type="submit">Save and continue</Button>
    </form>
  )
}

function PlanStep({ onFinish }: { onFinish: () => void }) {
  const fire = useAsync(() => api.fire())
  return (
    <div className="space-y-3 text-sm">
      {fire.loading && <p className="text-slate-400">Running 5,000 simulated markets…</p>}
      <Err error={fire.error} />
      {fire.data && (
        <div className="space-y-1">
          <div className="text-3xl font-semibold">{pct(fire.data.success_rate, 0)}</div>
          <p className="text-slate-400">of simulated markets fund your plan through age 95 on what you entered. These are model outputs, not a guarantee.</p>
        </div>
      )}
      <Button onClick={onFinish}>Finish and open dashboard</Button>
    </div>
  )
}

export default function Onboarding() {
  const nav = useNavigate()
  const ob = useAsync(api.onboarding)
  const prof = useAsync(api.profile)
  const [view, setView] = useState<OnboardingStep['id'] | null>(null)
  const [err, setErr] = useState<unknown>(null)
  const o = ob.data
  const p = prof.data
  if (!o || !p)
    return (
      <Card title="Setup">{ob.error || prof.error ? <Err error={ob.error ?? prof.error} /> : <p className="text-sm text-slate-400">Loading setup…</p>}</Card>
    )
  const active = view ?? o.current

  const go = (step: OnboardingStep['id']) => {
    setView(step)
    api.saveOnboarding({ step }).then(() => ob.reload(), setErr)
  }
  const next = (from: OnboardingStep['id']) => {
    const i = o.steps.findIndex((s) => s.id === from)
    const n = o.steps[i + 1]
    if (n) go(n.id)
  }
  const saveProfile = (from: OnboardingStep['id']) => async (patch: Partial<Profile>) => {
    try {
      await api.saveProfile(patch)
      prof.reload()
      next(from)
    } catch (e) {
      setErr(e)
    }
  }
  const skip = (id: OnboardingStep['id']) => api.saveOnboarding({ skip: id }).then(() => (ob.reload(), next(id)), setErr)
  const finish = () => api.saveOnboarding({ completed: true }).then(() => nav('/'), setErr)
  const step = o.steps.find((s) => s.id === active)!
  const accounts = o.completeness.inputs.find((i) => i.key === 'accounts')?.filled ? 1 : 0

  return (
    <div className="grid gap-4 md:grid-cols-[1fr_20rem]">
      <Card title={`Set up AlphaBridge`}>
        <ol className="mb-4 flex flex-wrap gap-2" aria-label="Setup steps">
          {o.steps.map((s, i) => (
            <li key={s.id}>
              <button
                type="button"
                onClick={() => go(s.id)}
                aria-current={s.id === active ? 'step' : undefined}
                className={`flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs ${s.id === active ? 'border-emerald-500 text-slate-100' : 'border-slate-700 text-slate-400'}`}
              >
                {s.done ? <Check size={12} aria-hidden /> : <span aria-hidden>{i + 1}</span>}
                {s.title}
                {s.skipped && <span className="text-slate-500">(skipped)</span>}
              </button>
            </li>
          ))}
        </ol>
        <h3 className="text-lg font-semibold">{step.title}</h3>
        <p className="mb-3 text-sm text-slate-400">{step.blurb}</p>
        <Err error={err} />
        {active === 'household' && <HouseholdStep p={p} done={saveProfile('household')} />}
        {active === 'accounts' && (
          <AccountsStep
            count={accounts}
            onAdded={() => {
              ob.reload()
            }}
          />
        )}
        {active === 'upload' && (
          <div className="space-y-3 text-sm">
            <p className="text-slate-300">
              Drop a Fidelity, NetBenefits, Nationwide, Ally or Chase export (CSV or PDF) on the Portfolio page; you review the parse before anything is saved.
            </p>
            <Link to="/portfolio" className="inline-block rounded-xl border border-border px-4 py-2 hover:bg-accent">
              Open Portfolio &amp; Dropzone
            </Link>
          </div>
        )}
        {active === 'goals' && <GoalsStep p={p} done={saveProfile('goals')} />}
        {active === 'plan' && <PlanStep onFinish={() => void finish()} />}
        {active !== 'plan' && (
          <div className="mt-4 flex gap-2 border-t border-border pt-3">
            <Button variant="ghost" onClick={() => next(active)}>
              Next
            </Button>
            {!step.done && (
              <Button variant="ghost" onClick={() => void skip(active)}>
                Skip for now
              </Button>
            )}
            <Button variant="ghost" className="ml-auto" onClick={() => void api.saveOnboarding({ dismissed: true }).then(() => nav('/'), setErr)}>
              Dismiss setup
            </Button>
          </div>
        )}
      </Card>
      <Card title="How accurate is your plan?">
        <CompletenessMeter c={o.completeness} showAll />
      </Card>
    </div>
  )
}
