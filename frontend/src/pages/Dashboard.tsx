import { Cell, Line, LineChart, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { ArrowRight } from 'lucide-react'
import { Link } from 'react-router-dom'
import { api, type Owner } from '../api/client'
import ActionFeed from '../components/ActionFeed'
import CashFlowSankey from '../components/charts/CashFlowSankey'
import CompletenessMeter from '../components/CompletenessMeter'
import { Badge, Bar, Card, Err, Hint, pct, usd } from '../components/ui'
import { useAsync } from '../hooks'
import CashPlanCard from './CashPlanCard'
import NetWorthCard from './NetWorthCard'

const COLORS = { safe_core: '#38bdf8', satellite: '#a78bfa', dry_powder: '#34d399' }
const LABELS = { safe_core: 'Safe Core (401k)', satellite: 'Growth Satellite', dry_powder: 'Dry Powder (cash)' }
const SIGNAL = { HOLD_MMF: ['Hold in Money Market', 'slate'], DCA: ['Dollar-cost average', 'amber'], AGGRESSIVE_BUY: ['Aggressive buy', 'green'] } as const

export default function Dashboard() {
  const pf = useAsync(api.portfolio)
  const cash = useAsync(api.cash)
  const fire = useAsync(api.fire)
  const debt = useAsync(api.debt)
  const prof = useAsync(api.profile)
  const ob = useAsync(api.onboarding)
  const flow = useAsync(api.chartCashflow)
  const spouse = prof.data?.spouse_age ? prof.data.spouse_name || 'Spouse' : undefined
  const ownerLabel: Record<Owner, string> = { SELF: 'Yours', SPOUSE: spouse ? `${spouse}'s` : "Spouse's", JOINT: 'Joint' }
  const byOwner = pf.data?.by_owner
    ? (Object.keys(ownerLabel) as Owner[]).filter((o) => pf.data!.by_owner[o] && (pf.data!.by_owner[o].assets || pf.data!.by_owner[o].liabilities))
    : []
  const b = pf.data?.buckets
  const pie = b ? (Object.keys(COLORS) as (keyof typeof COLORS)[]).map((k) => ({ name: LABELS[k], value: b[k], color: COLORS[k] })) : []
  return (
    <div className="grid gap-4 md:grid-cols-2">
      {ob.data?.show && !ob.data.completed && (
        <Card title="Finish setting up" className="md:col-span-2">
          <CompletenessMeter c={ob.data.completeness} />
          <Link to="/onboarding" className="mt-3 inline-flex items-center gap-1 text-sm text-emerald-400">
            Continue setup <ArrowRight size={14} aria-hidden />
          </Link>
        </Card>
      )}
      <Card title="Next actions" className="md:col-span-2">
        <ActionFeed limit={5} />
      </Card>
      <Card title="Net worth & barbell split" className="md:col-span-2">
        <Err error={pf.error} />
        <div className="flex flex-wrap items-center gap-6">
          <div>
            <div className="text-4xl font-semibold">{usd(pf.data?.net_worth)}</div>
            {!!pf.data?.liabilities && (
              <div className="text-xs text-slate-400">
                {usd(pf.data.assets)} assets − {usd(pf.data.liabilities)} debt
              </div>
            )}
            <div className="mt-2 space-y-1 text-sm">
              {pie.map((p) => (
                <div key={p.name} className="flex items-center gap-2">
                  <span className="h-3 w-3 rounded-full" style={{ background: p.color }} />
                  {p.name}: <b>{usd(p.value)}</b> <span className="text-slate-500">{pf.data?.assets ? pct(p.value / pf.data.assets, 0) : ''}</span>
                </div>
              ))}
            </div>
          </div>
          <div className="h-40 w-40">
            <ResponsiveContainer>
              <PieChart>
                <Pie data={pie} dataKey="value" innerRadius={45} outerRadius={70} stroke="none">
                  {pie.map((p) => (
                    <Cell key={p.name} fill={p.color} />
                  ))}
                </Pie>
              </PieChart>
            </ResponsiveContainer>
          </div>
        </div>
        {byOwner.length > 1 && (
          <div className="mt-3 flex flex-wrap gap-x-6 gap-y-1 border-t border-slate-800 pt-3 text-sm">
            {byOwner.map((o) => {
              const t = pf.data!.by_owner[o]
              return (
                <div key={o}>
                  <span className="text-slate-400">{ownerLabel[o]}:</span> <b>{usd(t.assets - t.liabilities)}</b>
                  {t.liabilities > 0 && (
                    <span className="text-xs text-slate-500">
                      {' '}
                      ({usd(t.assets)} − {usd(t.liabilities)} debt)
                    </span>
                  )}
                </div>
              )
            })}
          </div>
        )}
        {pf.data && pf.data.accounts.length === 0 && <p className="mt-3 text-sm text-slate-400">No accounts yet — upload a statement in the Portfolio tab.</p>}
      </Card>
      <Card title="Where your income goes" className="md:col-span-2">
        <CashFlowSankey data={flow.data} loading={flow.loading && !flow.data} error={flow.error} />
        {flow.data && flow.data.shortfall > 0 && (
          <p className="mt-2 text-xs text-amber-300">Spending, debt and savings exceed income by {usd(flow.data.shortfall)} a year.</p>
        )}
        {flow.data && <p className="mt-1 text-xs text-slate-500">{flow.data.note}</p>}
      </Card>

      <NetWorthCard />

      {debt.data && debt.data.liabilities.length > 0 && (
        <Card title="Debt" className="md:col-span-2">
          <div className="mb-3 flex flex-wrap gap-6 text-sm">
            <div>
              <div className="text-2xl font-semibold">{usd(debt.data.total_balance)}</div>total owed
            </div>
            <div>
              <div className="text-2xl font-semibold">{usd(debt.data.monthly_debt_service)}</div>monthly payments
            </div>
            <div>
              <div className="text-2xl font-semibold">{pct(debt.data.debt_to_income, 0)}</div>debt-to-income
            </div>
          </div>
          <ul className="space-y-2 text-sm">
            {debt.data.liabilities.map((l) => (
              <li key={l.id} className="flex flex-wrap items-center gap-2">
                <b>{l.name}</b>{' '}
                <span className="text-slate-400">
                  {ownerLabel[l.owner]} · {usd(l.balance)} @ {pct(l.apr, 2)}
                </span>
                <Badge tone={l.recommendation.action === 'PAY_DOWN' ? 'red' : l.recommendation.action === 'SPLIT' ? 'amber' : 'green'}>
                  {l.recommendation.action === 'PAY_DOWN' ? 'Pay down' : l.recommendation.action === 'SPLIT' ? 'Split 50/50' : 'Keep & invest'}
                </Badge>
                <span className="text-xs text-slate-500">{l.recommendation.reason}</span>
                {l.extra_payment && l.extra_payment.months_saved > 0 && (
                  <span className="w-full text-xs text-emerald-300">
                    With the extra {usd(l.extra_monthly_payment)}/mo{l.extra_payment_until === 'RETIREMENT' ? ' until retirement' : ''}: paid off{' '}
                    {l.extra_payment.payoff_date_with_extra?.slice(0, 7)}, {Math.floor(l.extra_payment.months_saved / 12)} yr{' '}
                    {l.extra_payment.months_saved % 12} mo early, saving {usd(l.extra_payment.interest_saved)} in interest.
                  </span>
                )}
              </li>
            ))}
          </ul>
        </Card>
      )}

      <Card title="Cash deployment">
        <Err error={cash.error} />
        {cash.loading && <p className="text-sm text-slate-500">Loading market data…</p>}
        {cash.data &&
          (() => {
            const c = cash.data
            const [label, tone] = SIGNAL[c.signal]
            return (
              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <Badge tone={tone}>{label}</Badge>
                  <span className="text-sm text-slate-400">Score {c.score}/100</span>
                </div>
                <Bar value={c.score} />
                {c.pay_down_debt > 0 && (
                  <p className="text-sm text-red-300">
                    Pay <b>{usd(c.pay_down_debt)}</b> toward high-APR debt before deploying.
                  </p>
                )}
                <p className="text-sm">
                  Keep <b>{usd(c.keep_in_mmf)}</b> in money market ({pct(c.mmf_yield, 2)}); deploy <b>{usd(c.deploy_now)}</b>
                  {c.tranches > 0 && (
                    <>
                      {' '}
                      in {c.tranches} tranches of {usd(c.tranche_amount)}
                    </>
                  )}
                  .
                </p>
                <ul className="list-disc space-y-1 pl-5 text-xs text-slate-400">
                  {c.reasons.map((r) => (
                    <li key={r}>{r}</li>
                  ))}
                </ul>
                {c.notes.map((n) => (
                  <p key={n} className="text-xs text-amber-400">
                    {n}
                  </p>
                ))}
              </div>
            )
          })()}
      </Card>

      <CashPlanCard />

      <Card title="Retirement">
        <Err error={fire.error} />
        {fire.loading && <p className="text-sm text-slate-500">Running 5,000 simulated markets…</p>}
        {fire.data &&
          (() => {
            const f = fire.data
            const target = pct(f.target_success_rate, 0)
            const ea = f.earliest_ages
            return (
              <div className="space-y-3">
                <div className="grid grid-cols-2 gap-3 text-sm">
                  <div>
                    {f.sustainable_spend_monthly ? (
                      <>
                        <div className="text-2xl font-semibold text-emerald-400">{usd(f.sustainable_spend_monthly)}/mo</div>
                        you can spend at {f.people[0]?.retire_age.toFixed(0)}
                      </>
                    ) : (
                      <>
                        <div className="text-2xl font-semibold text-amber-400">Not enough yet</div>
                        to retire at {f.people[0]?.retire_age.toFixed(0)}
                        {f.sustainable_spend_at_earliest_monthly != null && ea && (
                          <div className="text-xs text-slate-400">
                            {usd(f.sustainable_spend_at_earliest_monthly)}/mo if you wait until {Math.round(ea.SELF)}
                          </div>
                        )}
                      </>
                    )}
                  </div>
                  <div>
                    <div className="text-2xl font-semibold">
                      {ea ? (spouse && ea.SPOUSE != null ? `${Math.round(ea.SELF)} / ${Math.round(ea.SPOUSE)}` : Math.round(ea.SELF)) : '—'}
                    </div>
                    <span className="inline-flex items-center gap-1">
                      earliest age{spouse ? ` (you / ${spouse})` : ''}
                      <Hint>
                        The first age where the money lasts to 95 in at least {target} of 5,000 simulated markets, at your planned spending. Spending is in
                        today's dollars, after taxes, health care and home costs.
                      </Hint>
                    </span>
                  </div>
                </div>
                <p className="text-xs text-slate-400">
                  {pct(f.success_rate, 0)} chance your current plan lasts to 95 (target {target}).
                </p>
                <div>
                  <div className="mb-1 flex justify-between text-xs text-slate-400">
                    <span>Savings for the years before 59½</span>
                    <span>{f.bridge_readiness_pct.toFixed(0)}%</span>
                  </div>
                  <Bar value={f.bridge_readiness_pct} tone={f.bridge_readiness_pct >= 100 ? 'bg-emerald-500' : 'bg-amber-500'} />
                  <p className="mt-1 text-xs text-slate-500">
                    {usd(f.bridge_capital_projected_real)} projected vs {usd(f.bridge_capital_needed)} needed (today's $)
                  </p>
                </div>
                <div className="h-32">
                  <ResponsiveContainer>
                    <LineChart data={f.path}>
                      <XAxis dataKey="year" tick={{ fontSize: 10 }} stroke="#475569" minTickGap={24} />
                      <YAxis hide />
                      <Tooltip
                        formatter={(v) => [usd(Number(v)), 'Median savings']}
                        contentStyle={{ background: '#0f172a', border: '1px solid #334155' }}
                        labelFormatter={(_, pl) => {
                          const r = pl?.[0]?.payload as (typeof f.path)[number] | undefined
                          return r
                            ? `${r.year} · you ${Math.round(r.ages.SELF)}${spouse && r.ages.SPOUSE != null ? ` / ${spouse} ${Math.round(r.ages.SPOUSE)}` : ''}`
                            : ''
                        }}
                      />
                      <Line dataKey="value" stroke="#3987e5" dot={false} strokeWidth={2} />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
                <Link className="flex items-center gap-1 text-sm text-emerald-400 hover:underline" to="/plan">
                  Open the full plan <ArrowRight size={14} />
                </Link>
              </div>
            )
          })()}
      </Card>
    </div>
  )
}
