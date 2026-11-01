import DataCard from './DataCard'
import { useEffect, useRef, useState } from 'react'
import { api, type Liability, type LiabilityIn, type LiabilityKind, type Owner, type Profile } from '../api/client'
import { Button, Card, Err, Input, pct } from '../components/ui'
import { useAsync } from '../hooks'
import { US_STATES } from '../usStates'

const OWNER_LABEL: Record<Owner, string> = { SELF: 'Mine', SPOUSE: "Spouse's", JOINT: 'Joint' }
const KINDS: LiabilityKind[] = ['MORTGAGE', 'AUTO', 'CARD', 'STUDENT', 'HELOC', 'OTHER']
const BLANK: LiabilityIn = {
  name: '',
  kind: 'MORTGAGE',
  balance: 0,
  apr: 0,
  monthly_payment: 0,
  payoff_date: null,
  owner: 'SELF',
  escrow_monthly: 0,
  extra_monthly_payment: 0,
  extra_payment_until: 'RETIREMENT',
}

function Liabilities({ act }: { act: (fn: () => Promise<unknown>, ok: string) => Promise<void> }) {
  const list = useAsync(api.liabilities)
  const help = useAsync(api.liabilityHelp)
  const [f, setF] = useState<LiabilityIn>(BLANK)
  const [aprPct, setAprPct] = useState('')
  const [addErr, setAddErr] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)
  const [over, setOver] = useState(false)
  const [res, setRes] = useState<{ created: string[]; updated: string[]; warnings: string[] } | null>(null)
  const [editId, setEditId] = useState<number | null>(null)
  const formRef = useRef<HTMLDivElement>(null)
  const resetForm = () => {
    setF(BLANK)
    setAprPct('')
    setEditId(null)
    setAddErr(null)
  }
  const startEdit = (l: Liability) => {
    // Copy only the editable fields so extra columns from the API aren't sent back.
    const next = Object.fromEntries(Object.keys(BLANK).map((k) => [k, l[k as keyof LiabilityIn]])) as unknown as LiabilityIn
    setF(next)
    setAprPct(String(+(l.apr * 100).toFixed(4)))
    setEditId(l.id)
    setAddErr(null)
    formRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }
  const submitLabel = editId === null ? 'Add debt' : 'Save changes'
  const upload = async (file: File) => {
    setBusy(true)
    setRes(null)
    await act(async () => {
      setRes(await api.ingestLiabilities(file))
      list.reload()
    }, 'Statement imported — review the values below')
    setBusy(false)
  }
  const n = (k: keyof LiabilityIn) => (e: React.ChangeEvent<HTMLInputElement>) => setF({ ...f, [k]: Number(e.target.value) })
  return (
    <Card title="Debts & liabilities">
      <p className="mb-3 text-xs text-slate-500">
        Leave payoff date empty to derive it from balance, APR and payment. Escrow (property tax/insurance) keeps counting after a mortgage is paid off.
      </p>
      <label
        onDragOver={(e) => {
          e.preventDefault()
          setOver(true)
        }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => {
          e.preventDefault()
          setOver(false)
          const file = e.dataTransfer.files[0]
          if (file) upload(file)
        }}
        className={`mb-3 flex cursor-pointer flex-col items-center gap-1 rounded-2xl border-2 border-dashed p-6 text-center ${over ? 'border-emerald-400 bg-emerald-950/30' : 'border-slate-700'}`}
      >
        <span className="text-sm">{busy ? 'Reading statement…' : 'Drop a mortgage, loan or credit-card statement (CSV, PDF or photo), or tap to choose'}</span>
        <input
          type="file"
          accept=".csv,.pdf,.png,.jpg,.jpeg"
          className="hidden"
          onChange={(e) => {
            const file = e.target.files?.[0]
            if (file) upload(file)
            e.target.value = ''
          }}
        />
      </label>
      {res && (
        <div className="mb-3 rounded-xl border border-slate-700 p-3 text-xs text-slate-300">
          {res.created.length > 0 && <p>Added: {res.created.join(', ')}</p>}
          {res.updated.length > 0 && <p>Updated balances: {res.updated.join(', ')}</p>}
          {res.warnings.map((w) => (
            <p key={w} className="text-amber-400">
              {w}
            </p>
          ))}
        </div>
      )}
      <details className="mb-4 text-xs text-slate-400">
        <summary className="cursor-pointer">Where do I get these files?</summary>
        {(help.data ?? []).map((h) => (
          <div key={h.what} className="mt-2">
            <b>{h.what}</b>
            <ul className="list-disc pl-5">
              {h.steps.map((x) => (
                <li key={x}>{x}</li>
              ))}
            </ul>
          </div>
        ))}
      </details>
      <ul className="mb-4 space-y-1 text-sm">
        {(list.data ?? []).map((l: Liability) => (
          <li
            key={l.id}
            className={`flex items-center justify-between gap-2 rounded-lg px-2 py-1 ${editId === l.id ? 'border border-emerald-500 bg-emerald-950/30' : ''}`}
          >
            <span>
              <b>{l.name}</b>
              {editId === l.id && <span className="ml-1 text-xs text-emerald-400">(editing)</span>}{' '}
              <span className="text-slate-400">
                {l.kind} · ${l.balance.toLocaleString()} @ {pct(l.apr, 2)} · ${l.monthly_payment}/mo{l.escrow_monthly ? ` + $${l.escrow_monthly} escrow` : ''}
                {l.extra_monthly_payment
                  ? ` + $${l.extra_monthly_payment} extra principal ${l.extra_payment_until === 'PAYOFF' ? 'until paid off' : 'until retirement'}`
                  : ''}
                {l.payoff_date ? ` · ends ${l.payoff_date}` : ''} · {OWNER_LABEL[l.owner]}
              </span>
            </span>
            <span className="flex shrink-0 gap-1">
              <Button variant="ghost" onClick={() => startEdit(l)}>
                Edit
              </Button>
              <Button
                variant="ghost"
                onClick={() =>
                  act(async () => {
                    await api.deleteLiability(l.id)
                    if (editId === l.id) resetForm()
                    list.reload()
                  }, 'Debt removed')
                }
              >
                Delete
              </Button>
            </span>
          </li>
        ))}
        {list.data?.length === 0 && <li className="text-slate-500">No debts entered.</li>}
      </ul>
      <div ref={formRef} className="scroll-mt-4">
        {editId !== null && <p className="mb-2 text-sm text-emerald-400">Editing {list.data?.find((l) => l.id === editId)?.name ?? 'debt'}</p>}
      </div>
      <Row>
        <Input label="Name" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} />
        <label className="block text-sm text-slate-300">
          Type
          <select
            className="mt-1 w-full rounded-xl border border-slate-700 bg-slate-950 px-3 py-2"
            value={f.kind}
            onChange={(e) => setF({ ...f, kind: e.target.value as LiabilityKind })}
          >
            {KINDS.map((k) => (
              <option key={k}>{k}</option>
            ))}
          </select>
        </label>
        <Input label="Balance" type="number" value={f.balance || ''} onChange={n('balance')} />
        <Input
          label="APR (%, e.g. 6.5)"
          type="number"
          step="0.01"
          value={aprPct}
          onChange={(e) => {
            setAprPct(e.target.value)
            setF({ ...f, apr: Number(e.target.value) / 100 })
          }}
        />
        <Input label="Monthly payment (principal + interest)" type="number" value={f.monthly_payment || ''} onChange={n('monthly_payment')} />
        <Input label="Payoff date (optional)" type="date" value={f.payoff_date ?? ''} onChange={(e) => setF({ ...f, payoff_date: e.target.value || null })} />
        <Input label="Escrow / month (mortgage tax + insurance)" type="number" value={f.escrow_monthly || ''} onChange={n('escrow_monthly')} />
        <label className="block text-sm text-slate-300">
          Whose debt
          <select
            className="mt-1 w-full rounded-xl border border-slate-700 bg-slate-950 px-3 py-2"
            value={f.owner}
            onChange={(e) => setF({ ...f, owner: e.target.value as Owner })}
          >
            {(Object.keys(OWNER_LABEL) as Owner[]).map((o) => (
              <option key={o} value={o}>
                {OWNER_LABEL[o]}
              </option>
            ))}
          </select>
        </label>
        <Input
          label="Extra principal / month (optional)"
          type="number"
          value={f.extra_monthly_payment || ''}
          onChange={n('extra_monthly_payment')}
          hint="Extra you pay toward principal on top of the regular payment. Your Monthly savings figure should already be net of this, so it isn't counted twice."
        />
        {f.extra_monthly_payment > 0 && (
          <label className="block text-sm text-slate-300">
            Keep paying extra
            <select
              className="mt-1 w-full rounded-xl border border-slate-700 bg-slate-950 px-3 py-2"
              value={f.extra_payment_until}
              onChange={(e) => setF({ ...f, extra_payment_until: e.target.value as LiabilityIn['extra_payment_until'] })}
            >
              <option value="RETIREMENT">Until we retire</option>
              <option value="PAYOFF">Until it's paid off (also in retirement)</option>
            </select>
          </label>
        )}
      </Row>
      <div className="mt-3 flex gap-2">
        <Button
          disabled={!f.name}
          onClick={async () => {
            setAddErr(null)
            try {
              if (editId === null) await api.addLiability(f)
              else await api.saveLiability({ ...f, id: editId })
              resetForm()
              list.reload()
            } catch (e) {
              setAddErr(e)
            }
          }}
        >
          {submitLabel}
        </Button>
        {editId !== null && (
          <Button variant="ghost" onClick={resetForm}>
            Cancel
          </Button>
        )}
      </div>
      <Err error={addErr} />
      {!f.name && <p className="mt-1 text-xs text-slate-500">Enter a name to enable {submitLabel}.</p>}
    </Card>
  )
}

const ssHint = (
  <>
    Log in at{' '}
    <a href="https://www.ssa.gov/myaccount" target="_blank" rel="noreferrer" className="text-emerald-400 underline">
      ssa.gov/myaccount
    </a>
    , open your <b>my Social Security</b> statement, and use the monthly estimate <b>at age 67</b> (full retirement age if born 1960 or later). Today's dollars,
    per person.
  </>
)

function SchedulerPanel() {
  const st = useAsync(api.schedulerStatus)
  const s = st.data
  return (
    <Card title="Background jobs">
      {!s ? (
        <p className="text-sm text-slate-500">Loading…</p>
      ) : !s.enabled ? (
        <p className="text-sm text-slate-500">Scheduler is off (set ENABLE_SCHEDULER=1 on a single worker).</p>
      ) : (
        <ul className="space-y-1 text-sm">
          {s.jobs.map((j) => {
            const h = s.history[j.id]
            return (
              <li key={j.id} className="flex flex-wrap justify-between gap-2">
                <span className="font-medium">{j.id}</span>
                <span className="text-slate-500">
                  next {j.next_run ? new Date(j.next_run).toLocaleString() : '—'} · last{' '}
                  {h ? `${h.status} ${new Date(h.last_run).toLocaleString()}` : 'never run'}
                  {h?.error ? ` — ${h.error}` : ''}
                </span>
              </li>
            )
          })}
        </ul>
      )}
      <div className="mt-3">
        <Button variant="ghost" onClick={st.reload}>
          Refresh
        </Button>
      </div>
    </Card>
  )
}

function Row({ children }: { children: React.ReactNode }) {
  return <div className="grid gap-3 md:grid-cols-2">{children}</div>
}

export default function Settings() {
  const llm = useAsync(api.llm)
  const notif = useAsync(api.notif)
  const prof = useAsync(api.profile)
  const [l, setL] = useState({ provider: 'anthropic', fast_model: '', reasoning_model: '', api_key: '', api_base: '', token_budget: 0 })
  const [n, setN] = useState({ discord_webhook: '', smtp_host: '', smtp_user: '', smtp_password: '', smtp_to: '' })
  const [p, setP] = useState<Partial<Profile>>({})
  const [msg, setMsg] = useState('')
  const [err, setErr] = useState<unknown>(null)
  useEffect(() => {
    if (llm.data) setL((x) => ({ ...x, ...llm.data!, api_key: '' }))
  }, [llm.data])
  useEffect(() => {
    if (notif.data) setN((x) => ({ ...x, smtp_host: notif.data!.smtp_host, smtp_user: notif.data!.smtp_user, smtp_to: notif.data!.smtp_to }))
  }, [notif.data])
  useEffect(() => {
    if (prof.data) setP(prof.data)
  }, [prof.data])
  const act = async (fn: () => Promise<unknown>, ok: string) => {
    setErr(null)
    setMsg('')
    try {
      await fn()
      setMsg(ok)
    } catch (e) {
      setErr(e)
    }
  }
  const num = (k: keyof Profile) => (e: React.ChangeEvent<HTMLInputElement>) => setP({ ...p, [k]: Number(e.target.value) })
  return (
    <div className="space-y-4">
      {msg && <p className="rounded-lg bg-emerald-950/60 p-2 text-sm text-emerald-300">{msg}</p>}
      <Err error={err} />
      <Card title="Profile & risk">
        <Row>
          <Input
            label={`Birth date (age ${p.current_age?.toFixed(1) ?? '–'})`}
            type="date"
            value={p.birth_date ?? ''}
            onChange={(e) => setP({ ...p, birth_date: e.target.value })}
          />
          <Input label="Target retirement age" type="number" value={p.target_retirement_age ?? ''} onChange={num('target_retirement_age')} />
          <Input
            label="Monthly living expenses (now, excl. debt payments)"
            type="number"
            value={p.monthly_expenses_current ?? ''}
            onChange={num('monthly_expenses_current')}
          />
          <Input
            label="Monthly living expenses (retired, excl. debt payments)"
            type="number"
            value={p.monthly_expenses_retirement ?? ''}
            onChange={num('monthly_expenses_retirement')}
          />
          <Input label="Monthly savings" type="number" value={p.monthly_contribution ?? ''} onChange={num('monthly_contribution')} />
          <Input
            label="Employer 401(k) match: $ per $1 deferred (e.g. 0.5)"
            type="number"
            step="0.05"
            value={p.employer_match_rate ?? ''}
            onChange={num('employer_match_rate')}
          />
          <Input
            label="Match applies to first % of pay (decimal, e.g. 0.06)"
            type="number"
            step="0.005"
            value={p.employer_match_cap_pct ?? ''}
            onChange={num('employer_match_cap_pct')}
          />
          <Input label="Emergency fund (months)" type="number" value={p.emergency_fund_target_months ?? ''} onChange={num('emergency_fund_target_months')} />
          <Input
            label="Money market yield (decimal, e.g. 0.046)"
            type="number"
            step="0.001"
            value={p.current_money_market_yield ?? ''}
            onChange={num('current_money_market_yield')}
          />
          <Input label="Your annual income" type="number" value={p.annual_income ?? ''} onChange={num('annual_income')} />
          <Input
            label="Your est. Social Security at 67 ($/mo, today's $)"
            hint={ssHint}
            type="number"
            value={p.social_security_monthly ?? ''}
            onChange={num('social_security_monthly')}
          />
          <Input label="Effective tax rate (decimal)" type="number" step="0.01" value={p.effective_tax_rate ?? ''} onChange={num('effective_tax_rate')} />
        </Row>
        <h3 className="mt-4 text-sm font-medium text-slate-300">
          Spouse / partner <span className="text-xs text-slate-500">(leave birth date empty if none)</span>
        </h3>
        <Row>
          <Input label="Name" value={p.spouse_name ?? ''} onChange={(e) => setP({ ...p, spouse_name: e.target.value })} />
          <Input
            label={`Birth date${p.spouse_birth_date ? ` (age ${p.spouse_age?.toFixed(1)})` : ''}`}
            type="date"
            value={p.spouse_birth_date ?? ''}
            onChange={(e) => setP({ ...p, spouse_birth_date: e.target.value || null })}
          />
          <Input label="Annual income" type="number" value={p.spouse_annual_income ?? ''} onChange={num('spouse_annual_income')} />
          <Input
            label="Retirement age (leave blank to retire together)"
            type="number"
            value={p.spouse_target_retirement_age || ''}
            onChange={num('spouse_target_retirement_age')}
            hint="Blank means you both stop working on the same date. Enter an age only to test retiring at different times."
          />
          {!!p.spouse_target_retirement_age && (
            <Input
              label="Take-home pay / month while still working after you retire"
              type="number"
              value={p.spouse_take_home_monthly || ''}
              onChange={num('spouse_take_home_monthly')}
              hint="Blank estimates it from annual income minus the tax rate. Their employer health plan is assumed to cover you both until they retire."
            />
          )}
          <Input
            label="Est. Social Security at their 67 ($/mo, today's $)"
            hint={ssHint}
            type="number"
            value={p.spouse_social_security_monthly ?? ''}
            onChange={num('spouse_social_security_monthly')}
          />
        </Row>
        <p className="mt-1 text-xs text-slate-500">
          Expenses, savings, tax rate and risk settings are shared by the household. By default you both retire on the same date. Set each account's owner on
          the Portfolio tab: a spouse's 401(k) unlocks at the spouse's 59.5, not yours.
        </p>
        <label className="mt-3 flex items-center gap-2 text-sm">
          <input type="checkbox" checked={!!p.money_market_yield_override} onChange={(e) => setP({ ...p, money_market_yield_override: e.target.checked })} />{' '}
          Use my yield instead of live T-bill rate
        </label>
        <label className="mt-3 block text-sm">
          Speculative share of surplus: {pct(p.risk_appetite ?? 0, 0)}
          <input type="range" min={0} max={1} step={0.05} className="w-full" value={p.risk_appetite ?? 0} onChange={num('risk_appetite')} />
        </label>
        <label className="mt-3 block text-sm">
          Sector concentration limit: {pct(p.sector_concentration_limit ?? 0, 0)}
          <input
            type="range"
            min={0.1}
            max={0.6}
            step={0.05}
            className="w-full"
            value={p.sector_concentration_limit ?? 0.3}
            onChange={num('sector_concentration_limit')}
          />
        </label>
        <div className="mt-3">
          <Input
            label="Employer stock ticker (for X-Ray concentration)"
            value={p.employer_symbol ?? ''}
            placeholder="e.g. MSFT"
            onChange={(e) => setP({ ...p, employer_symbol: e.target.value.toUpperCase() })}
          />
        </div>
        <Button className="mt-3" onClick={() => act(() => api.saveProfile(p), 'Profile saved')}>
          Save profile
        </Button>
      </Card>

      <Card title="Retirement assumptions">
        <h3 className="text-sm font-medium text-slate-300">Confidence & flexibility</h3>
        <Row>
          <label className="block text-sm text-slate-300">
            How sure should the plan be?
            <select
              className="mt-1 w-full rounded-xl border border-slate-700 bg-slate-950 px-3 py-2"
              value={p.target_success_rate ?? 0.85}
              onChange={(e) => setP({ ...p, target_success_rate: Number(e.target.value) })}
            >
              {[0.75, 0.85, 0.9, 0.95].map((v) => (
                <option key={v} value={v}>
                  {pct(v, 0)} of simulated markets{v === 0.85 ? ' (typical)' : ''}
                </option>
              ))}
            </select>
            <span className="mt-1 block text-xs text-slate-500">
              Used for the earliest retirement age and the monthly spending number. Higher is safer, so you'd retire later or spend less.
            </span>
          </label>
          <label className="flex items-center gap-2 text-sm text-slate-300">
            <input type="checkbox" checked={!!p.guardrails_enabled} onChange={(e) => setP({ ...p, guardrails_enabled: e.target.checked })} />
            Flexible spending (cut 10% after bad markets, raise 10% after good ones)
          </label>
        </Row>
        <h3 className="mt-4 text-sm font-medium text-slate-300">Social Security start age</h3>
        <Row>
          <Input
            label="You claim at (62–70)"
            type="number"
            min={62}
            max={70}
            value={p.ss_claim_age ?? 67}
            onChange={num('ss_claim_age')}
            hint="62 pays about 70% of the age-67 amount for life; 70 pays about 124%. Waiting usually helps if you expect a long life, and it raises the survivor benefit."
          />
          {!!p.spouse_age && (
            <Input label="Spouse claims at (62–70)" type="number" min={62} max={70} value={p.spouse_ss_claim_age ?? 67} onChange={num('spouse_ss_claim_age')} />
          )}
        </Row>
        <h3 className="mt-4 text-sm font-medium text-slate-300">Health care</h3>
        <Row>
          <label className="block text-sm text-slate-300">
            State
            <select
              className="mt-1 w-full rounded-xl border border-slate-700 bg-slate-950 px-3 py-2"
              value={p.state ?? 'AZ'}
              onChange={(e) => setP({ ...p, state: e.target.value })}
            >
              {US_STATES.map(([code, name]) => (
                <option key={code} value={code}>
                  {name}
                </option>
              ))}
            </select>
            <span className="mt-1 block text-xs text-slate-500">
              Decides whether low-income early-retirement years can be on Medicaid (expansion states only).
            </span>
          </label>
          <label className="flex items-center gap-2 text-sm text-slate-300">
            <input type="checkbox" checked={!!p.meets_community_engagement} onChange={(e) => setP({ ...p, meets_community_engagement: e.target.checked })} />
            I'll meet the Medicaid work rule from 2027 (80 hrs/month of work, volunteering, training or school)
          </label>
          <Input
            label="Marketplace benchmark premium, household ($/mo, blank = estimate)"
            type="number"
            value={p.aca_benchmark_premium_monthly || ''}
            onChange={num('aca_benchmark_premium_monthly')}
            hint={
              <>
                Price of the second-cheapest Silver plan for both of you at retirement age, before any tax credit. Look it up at{' '}
                <a href="https://www.healthcare.gov/see-plans/" target="_blank" rel="noreferrer" className="text-emerald-400 underline">
                  healthcare.gov/see-plans
                </a>{' '}
                (or your state's site). Blank uses a national average by age.
              </>
            }
          />
          <Input label="Dental + vision ($/mo per person)" type="number" value={p.dental_vision_monthly ?? ''} onChange={num('dental_vision_monthly')} />
          <Input
            label="Out-of-pocket before 65 ($/yr per person)"
            type="number"
            value={p.health_oop_annual ?? ''}
            onChange={num('health_oop_annual')}
            hint="Deductibles, copays and prescriptions on a marketplace plan."
          />
          <Input
            label="Medicare Part B + Medigap + Part D ($/mo per person)"
            type="number"
            value={p.medicare_monthly_per_person ?? ''}
            onChange={num('medicare_monthly_per_person')}
          />
          <Input
            label="Health cost growth (%/yr)"
            type="number"
            step="0.5"
            value={+((p.health_inflation ?? 0.05) * 100).toFixed(2)}
            onChange={(e) => setP({ ...p, health_inflation: Number(e.target.value) / 100 })}
            hint="Health care tends to rise faster than general inflation (2.5%). The extra growth is applied for the next 20 years."
          />
        </Row>
        <h3 className="mt-4 text-sm font-medium text-slate-300">Home & long-term care</h3>
        <Row>
          <Input label="Home value (today's $)" type="number" value={p.home_value || ''} onChange={num('home_value')} />
          <Input
            label="Upkeep (% of home value per year)"
            type="number"
            step="0.25"
            value={+((p.home_upkeep_pct ?? 0.01) * 100).toFixed(2)}
            onChange={(e) => setP({ ...p, home_upkeep_pct: Number(e.target.value) / 100 })}
            hint="Repairs and maintenance in retirement. 1% a year is a common rule of thumb. Property tax and insurance come from the mortgage escrow."
          />
          <Input
            label="Long-term care cost ($/yr per person, today's $)"
            type="number"
            value={p.ltc_annual ?? ''}
            onChange={num('ltc_annual')}
            hint="Assisted living runs about $70k/yr, a nursing home $100k+ (national medians). Set years to 0 if you have LTC insurance."
          />
          <Input label="Years of care per person" type="number" step="0.5" value={p.ltc_years ?? ''} onChange={num('ltc_years')} />
          <Input label="Care starts at age" type="number" value={p.ltc_start_age ?? ''} onChange={num('ltc_start_age')} />
        </Row>
        <Button className="mt-3" onClick={() => act(() => api.saveProfile(p), 'Assumptions saved')}>
          Save assumptions
        </Button>
      </Card>

      <Liabilities act={act} />

      <Card title="LLM router">
        <Row>
          <label className="block text-sm text-slate-300">
            Provider
            <select
              className="mt-1 w-full rounded-xl border border-slate-700 bg-slate-950 px-3 py-2"
              value={l.provider}
              onChange={(e) => setL({ ...l, provider: e.target.value })}
            >
              {(llm.data?.providers ?? []).map((x) => (
                <option key={x}>{x}</option>
              ))}
            </select>
          </label>
          <Input
            label={`API key ${llm.data?.api_key_set ? '(set — leave blank to keep)' : ''}`}
            type="password"
            value={l.api_key}
            onChange={(e) => setL({ ...l, api_key: e.target.value })}
          />
          <Input label="Fast model (extraction)" value={l.fast_model} onChange={(e) => setL({ ...l, fast_model: e.target.value })} />
          <Input label="Reasoning model (research)" value={l.reasoning_model} onChange={(e) => setL({ ...l, reasoning_model: e.target.value })} />
          <Input label="API base (Ollama / proxy, optional)" value={l.api_base} onChange={(e) => setL({ ...l, api_base: e.target.value })} />
          <Input
            label="Token budget per research run (0 = unlimited)"
            type="number"
            value={String(l.token_budget)}
            onChange={(e) => setL({ ...l, token_budget: Number(e.target.value) || 0 })}
          />
        </Row>
        <div className="mt-3 flex gap-2">
          <Button
            onClick={() =>
              act(async () => {
                await api.saveLlm(l)
                llm.reload()
              }, 'LLM settings saved')
            }
          >
            Save
          </Button>
          <Button
            variant="ghost"
            onClick={() =>
              act(async () => {
                const r = await api.testLlm()
                if (!r.ok) throw new Error('failed')
              }, 'LLM responded')
            }
          >
            Test
          </Button>
        </div>
      </Card>

      <Card title="Alerts">
        <Row>
          <Input
            label={`Discord webhook URL ${notif.data?.discord_configured ? '(set)' : ''}`}
            type="password"
            value={n.discord_webhook}
            onChange={(e) => setN({ ...n, discord_webhook: e.target.value })}
          />
          <Input label="SMTP host (fallback)" value={n.smtp_host} onChange={(e) => setN({ ...n, smtp_host: e.target.value })} />
          <Input label="SMTP user" value={n.smtp_user} onChange={(e) => setN({ ...n, smtp_user: e.target.value })} />
          <Input label="SMTP password" type="password" value={n.smtp_password} onChange={(e) => setN({ ...n, smtp_password: e.target.value })} />
          <Input label="Send alerts to" value={n.smtp_to} onChange={(e) => setN({ ...n, smtp_to: e.target.value })} />
        </Row>
        <div className="mt-3 flex gap-2">
          <Button
            onClick={() =>
              act(async () => {
                const body: Record<string, string> = { smtp_host: n.smtp_host, smtp_user: n.smtp_user, smtp_to: n.smtp_to }
                if (n.discord_webhook) body.discord_webhook = n.discord_webhook
                if (n.smtp_password) body.smtp_password = n.smtp_password
                await api.saveNotif(body)
                notif.reload()
              }, 'Alert settings saved')
            }
          >
            Save
          </Button>
          <Button
            variant="ghost"
            onClick={() =>
              act(async () => {
                await api.testNotif()
              }, 'Test alert sent')
            }
          >
            Send test alert
          </Button>
        </div>
      </Card>
      <DataCard />
      <SchedulerPanel />
    </div>
  )
}
