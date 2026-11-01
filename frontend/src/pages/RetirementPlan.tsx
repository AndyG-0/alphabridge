import { Car, Gift, GraduationCap, Hammer, Home, Pencil, Plane, Plus, Trash2 } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import FanChart from '../components/charts/FanChart'
import { Bar as RBar, BarChart, CartesianGrid, Cell, Legend, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { api } from '../api/client'
import RmdCard from './RmdCard'
import SavingsCard from './SavingsCard'
import SocialSecurityCard from './SocialSecurityCard'
import HealthcareCard from './HealthcareCard'
import RealEstateCard from './RealEstateCard'
import ScenarioCard from './ScenarioCard'
import AssumptionsCard from './AssumptionsCard'
import SurvivorCard from './SurvivorCard'
import SpendingCard from './SpendingCard'
import StrategiesCard from './StrategiesCard'
import StressCard from './StressCard'
import RothCard from './RothCard'
import WithdrawalsCard from './WithdrawalsCard'
import type { Ages, DebtPayoff, EarlyAccess, Fire, FireWhatIf, Owner, Phase, PlannedEvent, PlannedEventIn, Profile } from '../api/client'
import { Badge, Button, Card, Err, Hint, Input, pct, usd } from '../components/ui'
import { useAsync } from '../hooks'

// Dark categorical slots 1–4, validated against the card surface (#0e1527)
const SERIES = { portfolio: '#3987e5', social_security_self: '#d95926', social_security_spouse: '#199e70', other_income: '#c98500' }
const SURFACE = '#0e1527'
const AXIS = '#475569'
const tooltipStyle = { background: '#0f172a', border: '1px solid #334155', borderRadius: 12, fontSize: 12 }

const thisYear = new Date().getFullYear()
const r0 = (n: number) => Math.round(n)

function agesText(a: Ages | null | undefined, spouse?: string) {
  if (!a) return ''
  return a.SPOUSE != null && spouse ? `you ${r0(a.SELF)} / ${spouse} ${r0(a.SPOUSE)}` : `you ${r0(a.SELF)}`
}

function useDebounced<T>(value: T, ms = 450) {
  const [v, setV] = useState(value)
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms)
    return () => clearTimeout(t)
  }, [value, ms])
  return v
}

export default function RetirementPlan() {
  const profile = useAsync(api.profile)
  const early = useAsync(api.earlyAccess)
  const events = useAsync(api.events)
  const [whatIf, setWhatIf] = useState<FireWhatIf>({})
  const q = useDebounced(whatIf)
  const fire = useAsync(() => api.fire(q), [JSON.stringify(q), events.data])
  const p = profile.data
  const f = fire.data
  const spouse = p?.spouse_age ? p.spouse_name || 'spouse' : undefined

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">Retirement plan</h1>
      <Err error={profile.error || fire.error} />
      {p && <WhatIfBar p={p} w={whatIf} set={setWhatIf} spouse={spouse} busy={fire.loading} />}
      {f && p && (
        <>
          <div className="grid gap-4 md:grid-cols-2">
            <Headline f={f} p={p} w={whatIf} spouse={spouse} />
            <Earliest f={f} p={p} spouse={spouse} />
          </div>
          {f.monthly_income && f.monthly_income.length > 0 && <Phases phases={f.monthly_income} spouse={spouse} basis={f.monthly_income_basis} />}
          {f.debts && f.debts.length > 0 && (
            <DebtPayoffCard
              debts={f.debts}
              retireYear={thisYear + Math.round((whatIf.retire_age ?? p.target_retirement_age) - p.current_age)}
              spouse={spouse}
            />
          )}
          <div className="grid gap-4 md:grid-cols-2">
            <WealthPath f={f} spouse={spouse} />
            <Timeline f={f} spouse={spouse} />
          </div>
          <Health f={f} spouse={spouse} />
          <WithdrawalsCard />
          <SocialSecurityCard />
          <SavingsCard />
          <StrategiesCard />
          <StressCard />
          <SpendingCard />
          <HealthcareCard />
          <RealEstateCard />
          <ScenarioCard />
          <SurvivorCard />
          <AssumptionsCard />
          <RothCard />
          <RmdCard />
          {early.data && early.data.accounts.length > 0 && <EarlyAccessCard d={early.data} />}
        </>
      )}
      {!f && fire.loading && <p className="text-sm text-slate-400">Running 5,000 simulated markets…</p>}
      <Events items={events.data ?? []} reload={events.reload} spouse={spouse} />
    </div>
  )
}

const SEPP_METHODS: [string, string][] = [
  ['amortization', 'Fixed amortization'],
  ['annuitization', 'Fixed annuitization'],
  ['rmd', 'RMD method (changes yearly)'],
]

function SeppCompare({ balance }: { balance: number }) {
  const [age, setAge] = useState(52)
  const [rows, setRows] = useState<{ label: string; pay: number; ends: number }[]>([])
  useEffect(() => {
    let live = true
    Promise.all(SEPP_METHODS.map(([m]) => api.sepp(balance, age, m)))
      .then((r) => live && setRows(r.map((x, i) => ({ label: SEPP_METHODS[i][1], pay: x.annual_payment, ends: x.ends_at_age }))))
      .catch(() => live && setRows([]))
    return () => {
      live = false
    }
  }, [balance, age])
  if (balance <= 0) return null
  return (
    <div className="mt-4 text-sm">
      <div className="mb-1 flex items-center gap-2">
        <span className="font-medium">72(t) SEPP payment on all pre-tax balances if started at age</span>
        <input
          aria-label="SEPP start age"
          type="number"
          min={35}
          max={59}
          value={age}
          onChange={(e) => setAge(Number(e.target.value))}
          className="w-16 rounded bg-slate-800 px-2 py-1"
        />
      </div>
      <ul className="text-slate-400">
        {rows.map((r) => (
          <li key={r.label}>
            {r.label}: <b className="text-slate-200">{usd(r.pay)}</b>/yr until age {r.ends} (5% rate; the cap is the greater of 5% or 120% of the mid-term rate)
          </li>
        ))}
      </ul>
    </div>
  )
}

function EarlyAccessCard({ d }: { d: EarlyAccess }) {
  return (
    <Card title="Early access to 401(k) money (before 59½)">
      <p className="mb-3 text-sm text-slate-400">
        Withdrawals before 59½ are taxed as income plus a {Math.round(d.penalty_rate * 100)}% penalty, unless an exception applies. The Rule of 55 lets you draw
        from the plan of the employer you leave in or after the year you turn 55, but not from older plans or IRAs. Tick "Current employer's plan" on the
        Portfolio page to include it in the projection.
      </p>
      <ul className="space-y-3">
        {d.accounts.map((a) => (
          <li key={a.id} className="text-sm">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-medium">{a.name}</span>
              <Badge>{usd(a.balance)}</Badge>
              <Badge tone={a.accessible_at < 59.5 ? 'green' : 'amber'}>Penalty-free from {a.accessible_at}</Badge>
              <Badge tone={a.rollover.action === 'keep' ? 'green' : 'slate'}>{a.rollover.action === 'keep' ? 'Keep in plan' : 'Consider IRA rollover'}</Badge>
            </div>
            <p className="mt-1 text-slate-400">
              {a.reason} {a.rollover.reason}
            </p>
          </li>
        ))}
      </ul>
      <SeppCompare balance={d.accounts.reduce((t, a) => t + a.balance, 0)} />
      <p className="mt-3 text-xs text-slate-500">
        General education, not tax advice. Confirm partial-distribution and rollover rules with each plan administrator. Rules as of {d.retrieved_on}.
      </p>
    </Card>
  )
}

function Slider({
  label,
  value,
  min,
  max,
  step = 1,
  fmt,
  onChange,
}: {
  label: string
  value: number
  min: number
  max: number
  step?: number
  fmt: (n: number) => string
  onChange: (n: number) => void
}) {
  return (
    <label className="block text-sm text-slate-300">
      <span className="flex justify-between">
        <span>{label}</span>
        <span className="font-medium text-slate-100">{fmt(value)}</span>
      </span>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="mt-2 w-full accent-emerald-500"
      />
    </label>
  )
}

function WhatIfBar({ p, w, set, spouse, busy }: { p: Profile; w: FireWhatIf; set: (w: FireWhatIf) => void; spouse?: string; busy: boolean }) {
  const retire = w.retire_age ?? p.target_retirement_age
  const gap = p.spouse_age ? p.current_age - p.spouse_age : 0
  const changed = Object.keys(w).length > 0
  return (
    <Card title="What if…">
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Slider
          label="Retire at (your age)"
          value={retire}
          min={Math.max(Math.ceil(p.current_age), 35)}
          max={70}
          fmt={(n) => (spouse ? `${n} (${spouse} ${r0(n - gap)})` : `${n}`)}
          onChange={(n) => set({ ...w, retire_age: n })}
        />
        <Slider
          label="Monthly spending (today's $)"
          value={w.spend ?? p.monthly_expenses_retirement}
          min={1000}
          max={20000}
          step={250}
          fmt={usd}
          onChange={(n) => set({ ...w, spend: n })}
        />
        <Slider
          label="Your Social Security at"
          value={w.ss_claim_age ?? p.ss_claim_age}
          min={62}
          max={70}
          fmt={String}
          onChange={(n) => set({ ...w, ss_claim_age: n })}
        />
        {spouse && (
          <Slider
            label={`${spouse}'s Social Security at`}
            value={w.spouse_ss_claim_age ?? p.spouse_ss_claim_age}
            min={62}
            max={70}
            fmt={String}
            onChange={(n) => set({ ...w, spouse_ss_claim_age: n })}
          />
        )}
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-3 text-sm text-slate-300">
        <label className="flex items-center gap-2">
          <input type="checkbox" checked={w.guardrails ?? p.guardrails_enabled} onChange={(e) => set({ ...w, guardrails: e.target.checked })} />
          Flexible spending (guardrails)
          <Hint>
            Cut spending 10% after a bad stretch in the market and raise it 10% after a good one. Health care, debt and long-term care are never cut.
            Flexibility usually lets you spend more overall.
          </Hint>
        </label>
        {busy && <span className="text-xs text-slate-500">updating…</span>}
        {changed && (
          <Button variant="ghost" className="ml-auto py-1" onClick={() => set({})}>
            Reset to saved plan
          </Button>
        )}
      </div>
      <p className="mt-2 text-xs text-slate-500">These sliders don't change your saved profile. Change the defaults in Settings.</p>
    </Card>
  )
}

function Headline({ f, p, w, spouse }: { f: Fire; p: Profile; w: FireWhatIf; spouse?: string }) {
  const target = pct(f.target_success_rate, 0)
  const sust = f.sustainable_spend_monthly ?? 0
  const planned = w.spend ?? f.planned_spend_monthly ?? p.monthly_expenses_retirement
  const retire = w.retire_age ?? p.target_retirement_age
  const who = spouse ? 'you both' : 'you'
  return (
    <Card title="Monthly spending in retirement">
      {sust > 0 ? (
        <>
          <p className="text-4xl font-semibold text-emerald-400">
            {usd(sust)}
            <span className="text-lg text-slate-400">/mo</span>
          </p>
          <p className="mt-1 text-sm text-slate-300">
            What {who} can spend each month if you retire at {retire}, in today's dollars, with at least a {target} chance the money lasts to 95.
          </p>
          <p className="mt-2 text-xs text-slate-400">
            That's living money on top of taxes, health care, home costs, debt payments and the planned purchases below. It stays the same in buying power: the
            dollar amount rises with inflation.
          </p>
        </>
      ) : (
        <>
          <p className="text-2xl font-semibold text-amber-300">Not enough yet to retire at {retire}</p>
          <p className="mt-1 text-sm text-slate-300">
            Even with very low spending, savings run short in more than {pct(1 - f.target_success_rate, 0)} of simulated markets, usually in the years before
            the 401(k)s unlock at 59½.
          </p>
          {f.sustainable_spend_at_earliest_monthly != null && f.earliest_ages && (
            <p className="mt-2 text-sm text-slate-200">
              At the earliest workable age ({agesText(f.earliest_ages, spouse)}) you could spend <b>{usd(f.sustainable_spend_at_earliest_monthly)}/mo</b>.
            </p>
          )}
        </>
      )}
      <div className="mt-3 flex flex-wrap gap-2 text-xs">
        <Badge tone={sust >= planned ? 'green' : 'amber'}>Your plan: {usd(planned)}/mo</Badge>
        <Badge tone={f.success_rate >= f.target_success_rate ? 'green' : 'amber'}>{pct(f.success_rate, 0)} chance the plan lasts</Badge>
        {f.guardrail_cut_rate != null && <Badge>{pct(f.guardrail_cut_rate, 0)} of markets needed a spending cut</Badge>}
      </div>
    </Card>
  )
}

function Earliest({ f, p, spouse }: { f: Fire; p: Profile; spouse?: string }) {
  const target = pct(f.target_success_rate, 0)
  return (
    <Card title={spouse ? 'Earliest age you can both retire' : 'Earliest age you can retire'}>
      {f.earliest_ages ? (
        <div className="flex flex-wrap gap-6">
          <div>
            <p className="text-4xl font-semibold">{r0(f.earliest_ages.SELF)}</p>
            <p className="text-xs text-slate-400">you</p>
          </div>
          {spouse && f.earliest_ages.SPOUSE != null && (
            <div>
              <p className="text-4xl font-semibold">{r0(f.earliest_ages.SPOUSE)}</p>
              <p className="text-xs text-slate-400">{spouse}</p>
            </div>
          )}
          <div>
            <p className="text-4xl font-semibold text-slate-400">{thisYear + Math.round((f.earliest_retirement_age ?? 0) - p.current_age)}</p>
            <p className="text-xs text-slate-400">year</p>
          </div>
        </div>
      ) : (
        <p className="text-lg text-amber-300">Not reachable by 70 with today's plan</p>
      )}
      <p className="mt-3 flex items-start gap-1.5 text-sm text-slate-300">
        <span>
          The first age where your money lasts to 95 in at least {target} of 5,000 simulated markets, at your planned spending of{' '}
          {usd(p.monthly_expenses_retirement)}/mo.
        </span>
        <Hint>
          We replay 5,000 possible futures with good and bad years for stocks and bonds in random order. "{target}" means the money lasted in {target} of them.
          The other {pct(1 - f.target_success_rate, 0)} usually mean spending less or working a bit longer if markets go badly early on, not running out
          overnight. You can change this target (75–95%) in Settings.
        </Hint>
      </p>
    </Card>
  )
}

const SOURCE_LABELS = (spouse?: string) => ({
  portfolio: 'From savings',
  social_security_self: 'Your Social Security',
  social_security_spouse: `${spouse ?? 'Spouse'}'s Social Security`,
  other_income: 'Pension, paycheck & other',
})
const SPEND_LABELS: Record<keyof Phase['spending'], string> = {
  living: 'Living',
  health_care: 'Health care',
  housing: 'Home (taxes, insurance, upkeep)',
  debt: 'Debt payments',
  planned_purchases: 'Planned purchases (avg.)',
  long_term_care: 'Long-term care (avg.)',
  taxes: 'Taxes',
}

function Phases({ phases, spouse, basis }: { phases: Phase[]; spouse?: string; basis?: string }) {
  const labels = SOURCE_LABELS(spouse)
  const keys = (Object.keys(SERIES) as (keyof typeof SERIES)[]).filter((k) => phases.some((ph) => ph.sources[k] > 0))
  const whole = phases.map((ph) => Math.floor(ph.start_age))
  // two stages can floor to the same age (e.g. 66.2 and 66.7), so add the year to keep the labels distinct
  const data = phases.map((ph, i) => ({
    name: whole.indexOf(whole[i]) !== whole.lastIndexOf(whole[i]) ? `Age ${whole[i]} (${ph.start_year})` : `Age ${whole[i]}`,
    ...ph.sources,
    ph,
  }))
  const [table, setTable] = useState(false)
  return (
    <Card title="Where the monthly money comes from">
      <p className="mb-3 text-sm text-slate-400">
        Each bar is a stage of retirement, in today's dollars per month.
        {basis === 'PLANNED' && ' Shown at your planned spending, because nothing is sustainable at this age yet.'}
      </p>
      <div className="h-64">
        <ResponsiveContainer>
          <BarChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
            <CartesianGrid vertical={false} stroke="#1e293b" />
            <XAxis dataKey="name" tick={{ fontSize: 11, fill: '#94a3b8' }} stroke={AXIS} tickLine={false} />
            <YAxis
              tickFormatter={(v) => `$${+(v / 1000).toFixed(1)}k`}
              tick={{ fontSize: 11, fill: '#94a3b8' }}
              stroke={AXIS}
              width={44}
              axisLine={false}
              tickLine={false}
            />
            <Tooltip
              cursor={{ fill: '#1e293b66' }}
              content={({ active, payload }) => {
                if (!active || !payload?.length) return null
                const ph = (payload[0].payload as { ph: Phase }).ph
                return (
                  <div style={tooltipStyle} className="p-3 text-slate-200">
                    <p className="font-medium">
                      {ph.start_year} · {agesText(ph.ages, spouse)}
                    </p>
                    <p className="mb-1 text-xs text-slate-400">{ph.label}</p>
                    {keys.map(
                      (k) =>
                        ph.sources[k] > 0 && (
                          <p key={k} className="flex items-center gap-2">
                            <span className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: SERIES[k] }} />
                            {labels[k]}: {usd(ph.sources[k])}
                          </p>
                        ),
                    )}
                    <p className="mt-1 border-t border-slate-700 pt-1">Total {usd(ph.total_monthly)}/mo</p>
                  </div>
                )
              }}
            />
            <Legend formatter={(v) => <span className="text-xs text-slate-300">{labels[v as keyof typeof labels]}</span>} iconType="square" iconSize={10} />
            {keys.map((k, i) => (
              <RBar
                key={k}
                dataKey={k}
                stackId="s"
                fill={SERIES[k]}
                stroke={SURFACE}
                strokeWidth={2}
                maxBarSize={56}
                radius={i === keys.length - 1 ? [4, 4, 0, 0] : 0}
              />
            ))}
          </BarChart>
        </ResponsiveContainer>
      </div>
      <button className="mt-2 text-xs text-slate-400 underline" onClick={() => setTable(!table)}>
        {table ? 'Hide' : 'Show'} the budget for each stage
      </button>
      {table && (
        <div tabIndex={0} role="region" aria-label="Scrollable table" className="mt-2 overflow-x-auto">
          <table className="w-full min-w-[640px] text-right text-xs">
            <thead className="text-slate-400">
              <tr>
                <th className="p-1 text-left">Stage</th>
                {phases.map((ph) => (
                  <th key={ph.start_year + ph.label} className="p-1">
                    {ph.start_year}
                    <br />
                    <span className="font-normal">{agesText(ph.ages, spouse)}</span>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {(Object.keys(SPEND_LABELS) as (keyof Phase['spending'])[])
                .filter((k) => phases.some((ph) => ph.spending[k] > 0))
                .map((k) => (
                  <tr key={k} className="border-t border-slate-800">
                    <td className="p-1 text-left text-slate-300">{SPEND_LABELS[k]}</td>
                    {phases.map((ph, i) => (
                      <td key={i} className="p-1">
                        {usd(ph.spending[k])}
                      </td>
                    ))}
                  </tr>
                ))}
              <tr className="border-t border-slate-700 font-medium">
                <td className="p-1 text-left">Total needed</td>
                {phases.map((ph, i) => (
                  <td key={i} className="p-1">
                    {usd(ph.total_monthly)}
                  </td>
                ))}
              </tr>
              {keys.map((k) => (
                <tr key={k} className="text-slate-400">
                  <td className="p-1 text-left">{labels[k]}</td>
                  {phases.map((ph, i) => (
                    <td key={i} className="p-1">
                      {usd(ph.sources[k])}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  )
}

function WealthPath({ f, spouse }: { f: Fire; spouse?: string }) {
  return (
    <Card title="Typical savings over time (today's $)">
      <FanChart path={f.path} ageLabel={(row) => agesText(row.ages, spouse)} />
      <p className="mt-2 text-xs text-slate-400">
        The line is the middle outcome; shading shows the middle half and the middle 80% of simulated markets. In the worst 10% of markets you'd have{' '}
        {usd(f.p10_final_real)} at 95; in the best 10%, {usd(f.p90_final_real)}.
      </p>
    </Card>
  )
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
const payoffText = (d: DebtPayoff) => (d.ongoing ? 'never at this payment' : `${MONTHS[(d.payoff_month ?? 1) - 1]} ${d.payoff_year}`)

function DebtPayoffCard({ debts, retireYear, spouse }: { debts: DebtPayoff[]; retireYear: number; spouse?: string }) {
  // an ongoing debt never ends, so draw it to the end of the longest real payoff (or retirement) and flag it
  const reach = Math.max(retireYear - thisYear, ...debts.filter((d) => !d.ongoing).map((d) => d.months / 12), 1)
  const end = Math.ceil(reach) + 1
  const data = debts.map((d) => ({ name: d.name, years: d.ongoing ? end : +(d.months / 12).toFixed(2), d }))
  const color = (d: DebtPayoff) => (d.ongoing ? '#d95926' : d.paid_before_retirement ? '#199e70' : '#c98500')
  return (
    <Card title="When your debts are paid off">
      <p className="mb-3 text-sm text-slate-400">
        Each bar runs from today to the month the debt is gone. <span className="text-emerald-400">Green</span> ends before you retire,{' '}
        <span className="text-amber-400">amber</span> carries into retirement{debts.some((d) => d.ongoing) && ', and orange never ends at the current payment'}.
      </p>
      <div style={{ height: 56 + debts.length * 36 }}>
        <ResponsiveContainer>
          <BarChart data={data} layout="vertical" margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
            <CartesianGrid horizontal={false} stroke="#1e293b" />
            <XAxis
              type="number"
              domain={[0, end]}
              ticks={Array.from({ length: end + 1 }, (_, i) => i).filter((i) => i % Math.max(Math.ceil(end / 8), 1) === 0)}
              tickFormatter={(v) => String(thisYear + v)}
              tick={{ fontSize: 11, fill: '#94a3b8' }}
              stroke={AXIS}
              tickLine={false}
            />
            <YAxis type="category" dataKey="name" width={110} tick={{ fontSize: 11, fill: '#94a3b8' }} stroke={AXIS} axisLine={false} tickLine={false} />
            <Tooltip
              cursor={{ fill: '#1e293b66' }}
              content={({ active, payload }) => {
                if (!active || !payload?.length) return null
                const d = (payload[0].payload as { d: DebtPayoff }).d
                return (
                  <div style={tooltipStyle} className="p-3 text-slate-200">
                    <p className="font-medium">{d.name}</p>
                    <p>
                      {usd(d.balance)} owed · {usd(d.monthly_payment)}/mo
                    </p>
                    <p>Paid off: {payoffText(d)}</p>
                    {!d.ongoing && <p className="text-xs text-slate-400">{agesText(d.ages, spouse)}</p>}
                  </div>
                )
              }}
            />
            <ReferenceLine
              x={retireYear - thisYear}
              stroke="#94a3b8"
              strokeDasharray="4 3"
              label={{ value: 'Retire', position: 'top', fill: '#94a3b8', fontSize: 11 }}
            />
            <RBar dataKey="years" maxBarSize={22} radius={[0, 4, 4, 0]}>
              {data.map((row) => (
                <Cell key={row.d.id} fill={color(row.d)} />
              ))}
            </RBar>
          </BarChart>
        </ResponsiveContainer>
      </div>
      <div tabIndex={0} role="region" aria-label="Scrollable table" className="mt-2 overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="text-xs text-slate-500">
            <tr>
              <th className="p-1 text-left">Debt</th>
              <th className="p-1 text-right">Owed</th>
              <th className="p-1 text-right">Per month</th>
              <th className="p-1 text-left">Paid off</th>
              <th className="p-1 text-right">Years left</th>
            </tr>
          </thead>
          <tbody>
            {debts.map((d) => (
              <tr key={d.id} className="border-t border-slate-800">
                <td className="p-1">{d.name}</td>
                <td className="p-1 text-right tabular-nums">{usd(d.balance)}</td>
                <td className="p-1 text-right tabular-nums">{usd(d.monthly_payment)}</td>
                <td className="p-1">
                  {payoffText(d)}
                  {!d.ongoing && <span className="ml-2 text-xs text-slate-500">{agesText(d.ages, spouse)}</span>}
                </td>
                <td className="p-1 text-right tabular-nums">{d.ongoing ? '—' : (d.months / 12).toFixed(1)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  )
}

const KIND_TONE: Record<string, 'green' | 'amber' | 'slate' | 'red'> = {
  RETIRE: 'green',
  UNLOCK: 'green',
  SS: 'green',
  MEDICARE: 'green',
  DEBT: 'slate',
  PURCHASE: 'amber',
  INFLOW: 'green',
  LTC: 'red',
}

function Timeline({ f, spouse }: { f: Fire; spouse?: string }) {
  const items = f.timeline ?? []
  return (
    <Card title="Milestones">
      <div tabIndex={0} role="region" aria-label="Milestones timeline" className="max-h-72 overflow-y-auto pr-1">
        <ol className="space-y-2 text-sm">
          {items.map((m, i) => (
            <li key={i} className="flex items-baseline gap-3">
              <span className="w-11 shrink-0 font-medium tabular-nums text-slate-200">{m.year}</span>
              <span className="flex-1 text-slate-300">{m.label}</span>
              <span className="shrink-0 text-xs text-slate-500">{agesText(m.ages, spouse)}</span>
              <span className="hidden sm:inline">
                <Badge tone={KIND_TONE[m.kind] ?? 'slate'}>{m.kind.toLowerCase()}</Badge>
              </span>
            </li>
          ))}
        </ol>
      </div>
    </Card>
  )
}

const COVERAGE: Record<string, string> = { ACA: 'Marketplace (ACA)', 'ACA+MEDICARE': 'ACA + Medicare', MEDICARE: 'Medicare', EMPLOYER: 'Employer plan' }

function Health({ f, spouse }: { f: Fire; spouse?: string }) {
  const rows = (f.health ?? []).filter((h) => h.coverage !== 'EMPLOYER')
  const [all, setAll] = useState(false)
  if (!rows.length) return null
  const shown = all ? rows : rows.slice(0, 8)
  return (
    <Card title="Health care in retirement (per year, today's $)">
      <p className="mb-2 flex items-start gap-1.5 text-sm text-slate-400">
        <span>
          Before 65 you'd buy a marketplace (ACA) plan. The tax credit depends on your taxable income that year, which in early retirement is mostly what you
          pull from 401(k)s plus gains on shares you sell.
        </span>
        <Hint>
          Uses 2026 rules. The bigger 2021–2025 subsidies expired, so households above 400% of the poverty line ($84,600 for two) get no credit. Below 138% you
          may qualify for Medicaid if your state expanded it (set your state in Settings). From 2027 expansion adults 19–64 also need 80 hours a month of work,
          volunteering, training or school, or they lose both Medicaid and the marketplace credit. Premiums use the national average benchmark silver plan by
          age unless you enter your own in Settings. Each person moves to Medicare at their own 65.
        </Hint>
      </p>
      {f.aca_note && <p className="mb-2 rounded-lg bg-amber-950/50 p-2 text-sm text-amber-200">{f.aca_note}</p>}
      <div tabIndex={0} role="region" aria-label="Scrollable table" className="overflow-x-auto">
        <table className="w-full min-w-[620px] text-right text-sm">
          <thead className="text-xs text-slate-400">
            <tr>
              <th className="p-1 text-left">Year</th>
              <th className="p-1 text-left">Coverage</th>
              <th className="p-1">Est. income</th>
              <th className="p-1">ACA plan</th>
              <th className="p-1">Tax credit</th>
              <th className="p-1">Medicare</th>
              <th className="p-1">Dental, vision, out of pocket</th>
              <th className="p-1">Total</th>
            </tr>
          </thead>
          <tbody>
            {shown.map((h) => (
              <tr key={h.year} className="border-t border-slate-800">
                <td className="p-1 text-left">
                  <span className="tabular-nums">{h.year}</span>
                  <br />
                  <span className="text-xs text-slate-500">{agesText(h.ages, spouse)}</span>
                </td>
                <td className="p-1 text-left">
                  {h.medicaid ? h.medicaid_agency : COVERAGE[h.coverage]}
                  {h.medicaid && (
                    <>
                      {' '}
                      <Badge tone="green">low income</Badge>
                    </>
                  )}
                  {h.engagement_required && (
                    <>
                      {' '}
                      <Badge tone="amber">work rule</Badge>
                    </>
                  )}
                  {h.engagement_blocked && (
                    <>
                      {' '}
                      <Badge tone="amber">work rule not met</Badge>
                    </>
                  )}
                  {h.coverage_gap && (
                    <>
                      {' '}
                      <Badge tone="amber">coverage gap</Badge>
                    </>
                  )}
                  {h.over_cliff && (
                    <>
                      {' '}
                      <Badge tone="amber">over cliff</Badge>
                    </>
                  )}
                </td>
                <td className="p-1">{h.coverage === 'MEDICARE' ? '—' : usd(h.magi_est)}</td>
                <td className="p-1">{h.aca_benchmark ? usd(h.aca_benchmark) : '—'}</td>
                <td className="p-1 text-emerald-300">{h.aca_credit ? `−${usd(h.aca_credit)}` : '—'}</td>
                <td className="p-1">{h.medicare ? usd(h.medicare) : '—'}</td>
                <td className="p-1">{usd(h.dental_vision + h.out_of_pocket)}</td>
                <td className="p-1 font-medium">{usd(h.total)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {rows.length > 8 && (
        <button className="mt-2 text-xs text-slate-400 underline" onClick={() => setAll(!all)}>
          {all ? 'Show fewer years' : `Show all ${rows.length} years`}
        </button>
      )}
    </Card>
  )
}

const BLANK: PlannedEventIn = {
  name: '',
  kind: 'PURCHASE',
  amount: 0,
  start_year: thisYear + 1,
  repeat_every_years: 0,
  repeat_until_year: null,
  owner: 'JOINT',
  financed: false,
  down_payment: 0,
  loan_apr: 0.065,
  loan_term_months: 60,
  is_home_sale: false,
}
const PRESETS: { label: string; icon: ReactNode; e: Partial<PlannedEventIn> }[] = [
  { label: 'Car', icon: <Car size={14} />, e: { name: 'New car', amount: 40000, start_year: thisYear + 2, repeat_every_years: 10 } },
  { label: 'Roof / HVAC', icon: <Hammer size={14} />, e: { name: 'Roof / HVAC', amount: 15000, start_year: thisYear + 5, repeat_every_years: 15 } },
  {
    label: 'Wedding / college',
    icon: <GraduationCap size={14} />,
    e: { name: 'College', amount: 25000, start_year: thisYear + 10, repeat_every_years: 1, repeat_until_year: thisYear + 13 },
  },
  { label: 'Travel', icon: <Plane size={14} />, e: { name: 'Big trip', amount: 10000, start_year: thisYear + 1, repeat_every_years: 2 } },
  { label: 'Inheritance', icon: <Gift size={14} />, e: { name: 'Inheritance', kind: 'INFLOW', amount: 100000, start_year: thisYear + 15 } },
  { label: 'Sell home', icon: <Home size={14} />, e: { name: 'Downsize home', kind: 'INFLOW', amount: 250000, start_year: thisYear + 25, is_home_sale: true } },
]
const OWNER_LABEL = (spouse?: string): Record<Owner, string> => ({ SELF: 'Mine', SPOUSE: spouse ? `${spouse}'s` : "Spouse's", JOINT: 'Shared' })

function describe(e: PlannedEvent) {
  const amt = e.kind === 'PENSION' || e.kind === 'ANNUITY' ? `${usd(e.amount)}/mo` : usd(e.amount)
  const rep =
    e.repeat_every_years > 0
      ? (e.repeat_every_years === 1 ? ' every year' : ` every ${e.repeat_every_years} yrs`) + (e.repeat_until_year ? ` until ${e.repeat_until_year}` : '')
      : ''
  const start = e.kind === 'PENSION' || e.kind === 'ANNUITY' || e.kind === 'PARTTIME' || e.kind === 'RENTAL' ? `from ${e.start_year}` : `in ${e.start_year}`
  const fin = e.financed ? ` · financed ${usd(e.down_payment)} down, ${pct(e.loan_apr)} for ${e.loan_term_months} mo` : ''
  return `${amt} ${start}${rep}${fin}${e.is_home_sale ? ' · ends home costs and mortgage' : ''}`
}

function Events({ items, reload, spouse }: { items: PlannedEvent[]; reload: () => void; spouse?: string }) {
  const [edit, setEdit] = useState<(PlannedEventIn & { id?: number }) | null>(null)
  const [err, setErr] = useState<unknown>(null)
  const owners = OWNER_LABEL(spouse)
  const save = async () => {
    if (!edit) return
    try {
      if (edit.id) await api.saveEvent(edit as PlannedEvent)
      else await api.addEvent(edit)
      setEdit(null)
      setErr(null)
      reload()
    } catch (e) {
      setErr(e)
    }
  }
  const total = useMemo(() => items.filter((e) => e.kind === 'PURCHASE').length, [items])
  return (
    <Card title="Big purchases & windfalls">
      <p className="mb-3 text-sm text-slate-400">
        Cars, a new roof, college, travel, an inheritance or selling the house. Purchases before retirement come out of savings that year; after retirement they
        add to that year's withdrawal. All amounts in today's dollars.
      </p>
      {items.length > 0 && (
        <ul className="mb-3 divide-y divide-slate-800">
          {items.map((e) => (
            <li key={e.id} className="flex items-center gap-3 py-2 text-sm">
              <Badge tone={e.kind === 'PURCHASE' ? 'amber' : 'green'}>
                {e.kind === 'PURCHASE' ? 'spend' : e.kind === 'PENSION' ? 'pension' : e.kind === 'LTC' ? 'spend' : 'inflow'}
              </Badge>
              <div className="flex-1">
                <p className="text-slate-100">
                  {e.name} <span className="text-xs text-slate-500">· {owners[e.owner]}</span>
                </p>
                <p className="text-xs text-slate-400">{describe(e)}</p>
              </div>
              <button aria-label={`Edit ${e.name}`} className="text-slate-400 hover:text-slate-200" onClick={() => setEdit({ ...e })}>
                <Pencil size={16} />
              </button>
              <button aria-label={`Delete ${e.name}`} className="text-slate-400 hover:text-red-300" onClick={() => api.deleteEvent(e.id).then(reload)}>
                <Trash2 size={16} />
              </button>
            </li>
          ))}
        </ul>
      )}
      {!edit && (
        <div className="flex flex-wrap gap-2">
          {PRESETS.map((pr) => (
            <Button key={pr.label} variant="ghost" className="flex items-center gap-1.5 py-1.5" onClick={() => setEdit({ ...BLANK, ...pr.e })}>
              {pr.icon}
              {pr.label}
            </Button>
          ))}
          <Button variant="ghost" className="flex items-center gap-1.5 py-1.5" onClick={() => setEdit({ ...BLANK })}>
            <Plus size={14} />
            Other
          </Button>
        </div>
      )}
      {edit && (
        <EventForm
          e={edit}
          set={setEdit}
          owners={owners}
          onSave={save}
          onCancel={() => {
            setEdit(null)
            setErr(null)
          }}
        />
      )}
      <Err error={err} />
      {total === 0 && !edit && (
        <p className="mt-3 text-xs text-slate-500">
          Tip: if you'll both need new cars before retiring, add them here. It changes how much you can spend later.
        </p>
      )}
    </Card>
  )
}

function EventForm({
  e,
  set,
  owners,
  onSave,
  onCancel,
}: {
  e: PlannedEventIn & { id?: number }
  set: (e: PlannedEventIn & { id?: number }) => void
  owners: Record<Owner, string>
  onSave: () => void
  onCancel: () => void
}) {
  const num = (k: keyof PlannedEventIn) => (ev: React.ChangeEvent<HTMLInputElement>) => set({ ...e, [k]: ev.target.value === '' ? 0 : Number(ev.target.value) })
  const sel = 'mt-1 w-full rounded-xl border border-slate-700 bg-slate-950 px-3 py-2 text-slate-100'
  return (
    <div className="space-y-3 rounded-xl border border-slate-800 p-3">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Input label="Name" value={e.name} onChange={(ev) => set({ ...e, name: ev.target.value })} />
        <label className="block text-sm text-slate-300">
          Type
          <select className={sel} value={e.kind} onChange={(ev) => set({ ...e, kind: ev.target.value as PlannedEventIn['kind'] })}>
            <option value="PURCHASE">Purchase (money out)</option>
            <option value="INFLOW">One-time inflow (money in)</option>
            <option value="PENSION">Pension (monthly)</option>
            <option value="ANNUITY">Annuity / SPIA (monthly, taxed)</option>
            <option value="PARTTIME">Part-time income (yearly, taxed)</option>
            <option value="RENTAL">Rental net cash flow (yearly; basis = depreciation)</option>
            <option value="EQUITY">RSU / ESPP / NSO vest (taxed as wages)</option>
            <option value="INHERIT">Inheritance (untaxed)</option>
            <option value="BIZSALE">Business / property sale (basis = cost basis)</option>
            <option value="LTC">Long-term-care cost</option>
          </select>
        </label>
        <Input
          label={e.kind === 'PENSION' || e.kind === 'ANNUITY' ? "Monthly amount (today's $)" : "Amount (today's $)"}
          type="number"
          min={0}
          value={e.amount || ''}
          onChange={num('amount')}
        />
        {(e.kind === 'ANNUITY' || e.kind === 'RENTAL' || e.kind === 'BIZSALE') && (
          <Input
            label={e.kind === 'ANNUITY' ? 'Premium paid (tax-free recovery)' : e.kind === 'RENTAL' ? 'Annual depreciation' : 'Cost basis'}
            type="number"
            min={0}
            value={e.basis || ''}
            onChange={num('basis')}
          />
        )}
        <label className="block text-sm text-slate-300">
          Whose
          <select className={sel} value={e.owner} onChange={(ev) => set({ ...e, owner: ev.target.value as Owner })}>
            {(Object.keys(owners) as Owner[]).map((o) => (
              <option key={o} value={o}>
                {owners[o]}
              </option>
            ))}
          </select>
        </label>
        <Input label={e.kind === 'PENSION' ? 'Starts in year' : 'Year'} type="number" value={e.start_year} onChange={num('start_year')} />
        {e.kind !== 'PENSION' && (
          <Input label="Repeat every (years, 0 = once)" type="number" min={0} value={e.repeat_every_years} onChange={num('repeat_every_years')} />
        )}
        {e.kind !== 'PENSION' && e.repeat_every_years > 0 && (
          <Input
            label="Repeat until (year, blank = for life)"
            type="number"
            value={e.repeat_until_year ?? ''}
            onChange={(ev) => set({ ...e, repeat_until_year: ev.target.value ? Number(ev.target.value) : null })}
          />
        )}
      </div>
      {e.kind === 'PURCHASE' && (
        <div className="space-y-3">
          <label className="flex items-center gap-2 text-sm text-slate-300">
            <input type="checkbox" checked={e.financed} onChange={(ev) => set({ ...e, financed: ev.target.checked })} />
            Financed with a loan
          </label>
          {e.financed && (
            <div className="grid gap-3 sm:grid-cols-3">
              <Input label="Down payment" type="number" min={0} value={e.down_payment || ''} onChange={num('down_payment')} />
              <Input
                label="Loan APR (%)"
                type="number"
                step="0.1"
                min={0}
                value={+(e.loan_apr * 100).toFixed(2)}
                onChange={(ev) => set({ ...e, loan_apr: Number(ev.target.value) / 100 })}
              />
              <Input label="Term (months)" type="number" min={1} value={e.loan_term_months} onChange={num('loan_term_months')} />
            </div>
          )}
        </div>
      )}
      {e.kind === 'INFLOW' && (
        <label className="flex items-center gap-2 text-sm text-slate-300">
          <input type="checkbox" checked={e.is_home_sale} onChange={(ev) => set({ ...e, is_home_sale: ev.target.checked })} />
          This is selling our home (stops home upkeep, property tax/insurance and the mortgage that year). Enter what you'd keep after paying off the mortgage
          and buying the next place.
        </label>
      )}
      <div className="flex gap-2">
        <Button onClick={onSave} disabled={!e.name || e.amount <= 0}>
          {e.id ? 'Save' : 'Add'}
        </Button>
        <Button variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
      </div>
    </div>
  )
}
