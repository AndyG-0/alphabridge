const TOKEN_KEY = 'ab_token'

export const getToken = () => localStorage.getItem(TOKEN_KEY) ?? ''
export const setToken = (t: string) => localStorage.setItem(TOKEN_KEY, t)

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function req<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers)
  const token = getToken()
  if (token) headers.set('Authorization', `Bearer ${token}`)
  if (init.body && !(init.body instanceof FormData)) headers.set('Content-Type', 'application/json')
  const res = await fetch(`/api${path}`, { ...init, headers })
  if (res.status === 401) window.dispatchEvent(new Event('ab-unauthorized'))
  const text = await res.text()
  const data = text ? JSON.parse(text) : null
  if (!res.ok) {
    const detail = Array.isArray(data?.details) ? data.details.map((d: { loc: string[]; msg: string }) => `${d.loc.join('.')}: ${d.msg}`).join('; ') : ''
    throw Object.assign(new ApiError(res.status, detail || data?.error || res.statusText), { data })
  }
  return data as T
}

const json = (method: string, body?: unknown): RequestInit => ({ method, body: body === undefined ? undefined : JSON.stringify(body) })

export interface ChatSession {
  id: number
  title: string
  title_source: 'auto' | 'user'
  updated_at: string
  message_count?: number
}
export interface ChatMsg {
  id: number
  role: 'user' | 'assistant'
  content: string
  tools: string[]
}
export interface ChatSessionFull extends ChatSession {
  messages: ChatMsg[]
}

export interface Holding {
  id: number
  account_id: number
  symbol: string
  name: string
  shares: number
  market_value: number
  asset_class: string
  proxy_ticker: string | null
  current_price: number
  cost_basis_total: number
}
export interface Account {
  id: number
  name: string
  institution: string
  tax_bucket: string
  risk_tier: string
  is_restricted_plan: boolean
  owner: 'SELF' | 'SPOUSE' | 'JOINT'
  is_current_employer_plan: boolean
  total: number
  bucket: string
  holdings: Holding[]
}
export interface Institution {
  id: string
  label: string
  kind: string
  login_url: string | null
  docs: { what: string; steps: string[]; formats: string[] }[]
}
export type Owner = 'SELF' | 'SPOUSE' | 'JOINT'
export interface Portfolio {
  accounts: Account[]
  buckets: { safe_core: number; satellite: number; dry_powder: number }
  assets: number
  liabilities: number
  net_worth: number
  by_owner: Record<Owner, { assets: number; liabilities: number }>
}
export interface NetWorthPoint {
  taken_at: string
  total: number
  safe_core: number
  satellite: number
  dry_powder: number
  liabilities: number
  breakdown: { assets?: Record<string, number>; liabilities?: Record<string, number> }
}
export interface NetWorthSummary {
  series: NetWorthPoint[]
  latest: NetWorthPoint | null
  milestones: {
    reached: { level: number; reached_on: string; is_fi: boolean }[]
    next: { level: number; remaining: number; is_fi: boolean } | null
  }
  drift: { month: string; actual: number; planned: number; drift: number; drift_pct: number | null }[]
  assumptions: { annual_return: number; monthly_contribution: number; baseline: string | null }
}
export interface Profile {
  birth_date: string
  spouse_birth_date: string | null
  current_age: number
  target_retirement_age: number
  annual_income: number
  monthly_expenses_current: number
  monthly_expenses_retirement: number
  emergency_fund_target_months: number
  current_money_market_yield: number
  money_market_yield_override: boolean
  effective_tax_rate: number
  monthly_contribution: number
  target_allocation?: Record<string, number>
  risk_appetite: number
  sector_concentration_limit: number
  employer_symbol: string
  spouse_name: string
  spouse_age: number
  spouse_annual_income: number
  social_security_monthly: number
  spouse_social_security_monthly: number
  spouse_target_retirement_age: number
  spouse_take_home_monthly: number
  target_success_rate: number
  ss_claim_age: number
  spouse_ss_claim_age: number
  state: string
  meets_community_engagement: boolean
  aca_benchmark_premium_monthly: number
  dental_vision_monthly: number
  health_oop_annual: number
  medicare_monthly_per_person: number
  health_inflation: number
  home_value: number
  home_upkeep_pct: number
  ltc_annual: number
  ltc_years: number
  ltc_start_age: number
  guardrails_enabled: boolean
}
export type Ages = { SELF: number; SPOUSE?: number }
export interface Phase {
  label: string
  start_age: number
  end_age: number
  start_year: number
  ages: Ages
  total_monthly: number
  spending: { living: number; health_care: number; housing: number; planned_purchases: number; long_term_care: number; debt: number; taxes: number }
  sources: { portfolio: number; social_security_self: number; social_security_spouse: number; other_income: number }
}
export interface Milestone {
  year: number
  years_from_now: number
  ages: Ages
  label: string
  kind: string
  who: Owner
}
export interface DebtPayoff {
  id: number
  name: string
  kind: string
  owner: Owner
  balance: number
  monthly_payment: number
  months: number
  payoff_year: number | null
  payoff_month: number | null
  ages: Ages
  paid_before_retirement: boolean
  ongoing: boolean
}
export interface HealthYear {
  year: number
  ages: Ages
  coverage: 'EMPLOYER' | 'ACA' | 'ACA+MEDICARE' | 'MEDICARE'
  aca_benchmark: number
  aca_credit: number
  aca_net: number
  medicare: number
  dental_vision: number
  out_of_pocket: number
  total: number
  magi_est: number
  fpl_ratio: number
  medicaid: boolean
  medicaid_agency: string
  coverage_gap: boolean
  engagement_blocked: boolean
  engagement_required: boolean
  over_cliff: boolean
  cliff_magi: number | null
}
export interface Fire {
  success_rate: number
  bridge_success_rate: number
  bridge_readiness_pct: number
  bridge_capital_needed: number
  bridge_capital_projected_real: number
  earliest_retirement_age: number | null
  earliest_ages: Ages | null
  median_final_real: number
  p10_final_real: number
  p90_final_real: number
  median_path_real: [number, number][]
  n_sims: number
  target_success_rate: number
  guardrail_cut_rate: number | null
  people: { key: 'SELF' | 'SPOUSE'; name: string; age_now: number; retire_age: number }[]
  path: { year: number; ages: Ages; value: number }[]
  sustainable_spend_monthly?: number
  sustainable_spend_at_earliest_monthly?: number | null
  planned_spend_monthly?: number
  monthly_income_basis?: 'SUSTAINABLE' | 'PLANNED'
  monthly_income?: Phase[]
  timeline?: Milestone[]
  debts?: DebtPayoff[]
  health?: HealthYear[]
  aca_note?: string | null
}
export interface FireWhatIf {
  retire_age?: number
  spouse_retire_age?: number
  spend?: number
  ss_claim_age?: number
  spouse_ss_claim_age?: number
  target?: number
  guardrails?: boolean
}
export type EventKind = 'PURCHASE' | 'INFLOW' | 'PENSION' | 'LTC' | 'ANNUITY' | 'PARTTIME' | 'RENTAL' | 'EQUITY' | 'INHERIT' | 'BIZSALE'
export interface PlannedEventIn {
  name: string
  kind: EventKind
  amount: number
  start_year: number
  repeat_every_years: number
  repeat_until_year: number | null
  owner: Owner
  financed: boolean
  down_payment: number
  loan_apr: number
  loan_term_months: number
  is_home_sale: boolean
  basis?: number
}
export interface PlannedEvent extends PlannedEventIn {
  id: number
}
export interface Cash {
  signal: 'HOLD_MMF' | 'DCA' | 'AGGRESSIVE_BUY'
  score: number
  cash_total: number
  emergency_buffer: number
  investable_surplus: number
  pay_down_debt: number
  keep_in_mmf: number
  deploy_now: number
  tranches: number
  tranche_amount: number
  mmf_yield: number
  reasons: string[]
  notes: string[]
  satellite_allocation: Record<string, number>
}
export interface Report {
  id: number
  symbol: string
  quant_score: number
  valuation_grade: string
  growth_grade: string
  moat_grade: string
  bull_case_md: string
  bear_case_md: string
  sec_filing_citations_json: { form: string; filing_date: string; section?: string; quote?: string; url?: string }[]
  portfolio_fit_notes: string
  recommended_action: string
}
export interface Screen {
  symbol: string
  score: number
  passed: boolean
  revenue_growth: number | null
  rsi14: number | null
  sector: string | null
  name: string | null
}
export interface ScoreBreakdown {
  points: number
  max: number
}
export interface SymbolDetail {
  symbol: string
  price: number
  fundamentals: Record<string, number | string | null>
  screen: Screen & {
    score_breakdown: Record<string, ScoreBreakdown>
    checks: Record<string, boolean>
    sma200_dist: number | null
    pe: number | null
    operating_margin: number | null
  }
  technicals: {
    ret_1m: number | null
    ret_3m: number | null
    ret_1y: number | null
    volatility: number | null
    max_drawdown_1y: number
    beta: number | null
    high_52w: number
    low_52w: number
  }
  dcf_value: number | null
  dcf_upside: number | null
  held_weight: number
  sector_weight: number
  price_series: number[]
  report: {
    id: number
    recommended_action: string
    valuation_grade: string
    growth_grade: string
    moat_grade: string
    bull_case_md: string
    bear_case_md: string
    created_at: string
    portfolio_fit_notes: string
    red_flags: string[]
  } | null
}
export interface WhatIf {
  symbol: string
  asset_beta: number | null
  portfolio_beta_before: number | null
  portfolio_beta_after: number | null
  sector_before: Record<string, number>
  sector_after: Record<string, number>
  warnings: string[]
  fundamentals: Record<string, number | string | null>
}
export interface MenuGrade {
  weighted_expense_ratio: number
  grade: string
  annual_savings_potential: number
  suggestions: { from: string; to: string; to_name: string; annual_savings: number }[]
}

export type LiabilityKind = 'MORTGAGE' | 'AUTO' | 'CARD' | 'STUDENT' | 'HELOC' | 'OTHER'
export interface LiabilityIn {
  name: string
  kind: LiabilityKind
  balance: number
  apr: number
  monthly_payment: number
  payoff_date: string | null
  owner: Owner
  escrow_monthly: number
  extra_monthly_payment: number
  extra_payment_until: 'RETIREMENT' | 'PAYOFF'
}
export interface Liability extends LiabilityIn {
  id: number
}
export interface DebtItem extends Liability {
  months_remaining: number | null
  total_interest_remaining: number | null
  extra_payment: {
    months_with_extra: number
    interest_with_extra: number
    months_saved: number
    interest_saved: number
    payoff_date_with_extra: string | null
  } | null
  recommendation: { action: 'PAY_DOWN' | 'INVEST' | 'SPLIT' | 'NONE'; pay_down_amount: number; reason: string }
}
export interface DebtSummary {
  total_balance: number
  monthly_debt_service: number
  monthly_escrow: number
  debt_to_income: number | null
  liabilities: DebtItem[]
}

export interface EarlyAccessAccount {
  id: number
  name: string
  owner: Owner
  balance: number
  is_current_employer_plan: boolean
  accessible_at: number
  reason: string
  rollover: { action: 'keep' | 'consider_roll'; reason: string }
}
export interface EarlyAccess {
  accounts: EarlyAccessAccount[]
  exceptions: { id: string; label: string }[]
  penalty_rate: number
  retrieved_on: string
}

export interface WithdrawalYear {
  year: number
  age: number
  draw_taxable: number
  draw_pretax: number
  draw_roth: number
  social_security: number
  magi: number
  tax: number
  marginal_rate: number
  aca_premium: number
  aca_over_cliff: boolean
  shortfall: number
  balances: { taxable: number; pretax: number; roth: number }
}
export interface WithdrawalStrategy {
  strategy: string
  label: string
  years?: WithdrawalYear[]
  lifetime_tax: number
  lifetime_aca_premiums: number
  lifetime_cost: number
  shortfall_years: number
  ending_after_tax: number
  years_over_aca_cliff: number
  vs_taxable_first: number
}
export interface Withdrawals {
  best: string
  retire_age: number
  strategies: WithdrawalStrategy[]
  assumptions: string[]
  rules_year: number
  aca_rules_year: number
  aca_enhanced: boolean
  starting_balances: { taxable: number; pretax: number; roth: number }
}

export interface RmdRow {
  year: number
  age: number
  rmd: number
  qcd: number
  taxable_rmd: number
  end_balance: number
}
export interface RmdReport {
  people: { owner: 'SELF' | 'SPOUSE'; pretax_balance: number; start_age: number; joint_life_table_would_apply: boolean; rows: RmdRow[] }[]
  household_by_year: { year: number; rmd: number; qcd: number }[]
  peak_year_bracket: {
    year: number
    rmd: number
    marginal_without: number
    marginal_with: number
    bracket_jump: boolean
    irmaa_jump: boolean
    extra_tax: number
  } | null
  qcd_limit: number
  retrieved_on: string
}

export interface RothPlan {
  strategy: string
  label: string
  years?: (WithdrawalYear & { conversion: number; conversion_tax: number })[]
  ladder: { year: number; age: number; amount: number; seasoned_year: number }[]
  total_converted: number
  conversion_tax: number
  lifetime_cost: number
  ending_after_tax: number
  shortfall_years: number
  pretax_at_rmd_age: number
  first_rmd: number
  bridge_ok: boolean
  vs_none: { lifetime_cost: number; ending_after_tax: number; first_rmd: number }
}
export interface RothConversions {
  best: string | null
  plans: RothPlan[]
  retire_age: number
  rmd_start_age: number
  rules_year: number
  assumptions: string[]
}

export interface SsGrid {
  people: {
    name: string
    pia: number
    fra: number
    claim_age: number
    rows: { claim_age: number; monthly: number; factor: number; breakeven_vs_62: number | null }[]
  }[]
  best: { claim_a: number; claim_b: number | null; npv: number }
  current: { claim_a: number; claim_b: number | null; npv: number }
  gain_vs_current: number
  assumptions: string[]
}

export interface Pension {
  id: number
  owner: 'SELF' | 'SPOUSE'
  name: string
  plan_balance: number
  as_of: string | null
  pay_credit_pct: number
  covered_pay_annual: number
  interest_credit_rate: number
  start_age: number
  payout: 'ANNUITY' | 'LUMP_SUM'
  projection: { balance_at_start: number; monthly: number; years_to_start: number; years_of_credits: number } | null
}
export type PensionEdit = Partial<Pick<Pension, 'start_age' | 'payout' | 'interest_credit_rate' | 'pay_credit_pct' | 'covered_pay_annual'>>

export interface RowError {
  line: number
  symbol: string
  level: 'error' | 'warn'
  error: string
}
export interface IngestResult {
  pension?: Pension
  rows: number
  needs_mapping: string[]
  parser: string
  unchanged?: number[]
  accounts?: number[]
  row_errors?: RowError[]
}
export interface ImportLogEntry {
  id: number
  filename: string
  parser: string
  rows: number
  status: string
  message: string
  created_at: string
  account: string | null
  batch_id: string
  content_hash: string
  can_undo: boolean
  undone_at: string | null
}
export interface PreviewRow {
  symbol: string
  name: string
  shares: number
  price: number
  market_value: number
  asset_class: string
  account_name: string | null
}
export interface DuplicateDiffRow {
  symbol: string
  name: string
  status: 'same' | 'changed' | 'new' | 'missing'
  old_shares: number | null
  new_shares: number | null
  old_value: number | null
  new_value: number | null
}
export interface DuplicateDiff {
  summary: {
    same: number
    changed: number
    new: number
    missing: number
    symbol_overlap_pct: number
    old_total: number
    new_total: number
    total_delta_pct: number
  }
  rows: DuplicateDiffRow[]
}
export interface IngestPreview {
  preview: true
  parser: string
  source: string
  confidence: 'high' | 'medium' | 'low'
  filename: string
  checks: { level: 'ok' | 'warn' | 'fail'; message: string }[]
  warnings: string[]
  row_errors?: RowError[]
  rows: PreviewRow[]
}

export interface SchedulerStatus {
  enabled: boolean
  running: boolean
  jobs: { id: string; next_run: string | null }[]
  history: Record<string, { last_run: string; status: 'running' | 'ok' | 'error'; error: string | null }>
}

const updateAccount = (a: Account, patch: Partial<Pick<Account, 'name' | 'institution' | 'tax_bucket' | 'risk_tier' | 'owner' | 'is_current_employer_plan'>>) =>
  req<Account>(
    `/accounts/${a.id}`,
    json('PUT', {
      name: a.name,
      institution: a.institution,
      tax_bucket: a.tax_bucket,
      risk_tier: a.risk_tier,
      is_restricted_plan: a.is_restricted_plan,
      owner: a.owner,
      is_current_employer_plan: a.is_current_employer_plan,
      ...patch,
    }),
  )

export type PerfPeriod = { start: string; end: string; return: number }
export type BenchmarkRow = { name: string; return: number | null; excess: number | null }
export type CashFlowRow = { id: number; on: string; amount: number; note: string }
export type Performance = {
  points: number
  flow_mode: 'recorded' | 'none' | 'assumed_monthly_contribution'
  flows: number
  notes: string[]
  returns: {
    twr: { total: number | null; annualized: number | null; days: number; periods: PerfPeriod[] }
    mwr: number | null
    start: string
    end: string
    start_value: number
    end_value: number
  } | null
  benchmarks?: { market: BenchmarkRow; target: BenchmarkRow | null; approximate: boolean }
  fees: {
    annual_fee: number
    weighted_expense_ratio: number
    covered_pct: number
    unknown: string[]
    rows: { symbol: string; value: number; expense_ratio: number; annual_fee: number }[]
    drag: Record<string, { cost: number; cost_pct: number; years: number }>
  }
  income: {
    months: { month: number; amount: number }[]
    annual_income: number
    missing_yield: string[]
    assumption: string
  }
}

export type RebalanceTrade = {
  account_id: number
  account: string
  tax_bucket: string
  action: 'BUY' | 'SELL'
  symbol: string
  name?: string
  asset_class: string
  amount: number
  realized_gain: number
}
export type Rebalance = {
  has_target: boolean
  notes: string[]
  drift?: {
    total: number
    total_drift: number
    threshold: number
    breached: boolean
    rows: { asset_class: string; current: number; target: number; drift: number; dollars: number; breach: boolean }[]
  }
  trades?: RebalanceTrade[]
  unresolved?: { sell: Record<string, number>; buy: Record<string, number> }
  realized_gains?: number
  est_tax?: number
  after?: { total_drift: number }
  asset_location: {
    marginal_rate: number
    note: string
    suggestions: { symbol: string; account: string; from_bucket: string; to_bucket: string; value: number; est_annual_tax_drag: number; why: string }[]
  }
}

export type LotView = {
  id: number
  account_id: number
  symbol: string
  acquired: string
  shares: number
  cost_basis: number
  value: number
  gain: number
  term: 'SHORT' | 'LONG'
  days_to_long_term: number
}
export type HarvestRow = LotView & {
  account: string
  loss: number
  rate: number
  est_tax_savings: number
  alternatives: string[]
  identical_to: string[]
  wash_conflicts: { account: string; symbol: string; acquired: string; owner: string }[]
  avoid_buying_until: string
}
export type TaxLotReport = {
  lots: number
  missing_lots: string[]
  notes: string[]
  harvest?: {
    candidates: HarvestRow[]
    blocked_by_wash_sale: HarvestRow[]
    total_loss: number
    total_est_savings: number
    note: string
  }
  gain_harvest?: {
    zero_bracket_top: number
    headroom: number
    total_gain: number
    picks: { lot_id: number; symbol: string; shares: number; gain: number }[]
    note: string
  }
  upcoming_long_term?: LotView[]
}
export type LotSale = {
  symbol: string
  raised: number
  shortfall: number
  total_gain: number
  est_tax: number
  picks: { lot_id: number; acquired: string; term: string; shares: number; proceeds: number; gain: number; est_tax: number }[]
}

export type RiskReport = {
  total: number
  notes: string[]
  coverage?: { priced_pct: number; unpriced: string[]; proxied: string[]; cash_pct: number }
  risk?: {
    days: number
    volatility: number
    max_drawdown: number
    var_1d: number
    cvar_1d: number
    var_1d_dollars: number
    cvar_1d_dollars: number
    confidence: number
    beta: number | null
  }
  contribution?: { symbol: string; weight: number; risk_share: number }[]
  correlation?: Record<string, Record<string, number>>
  stress: {
    id: string
    label: string
    portfolio_change: number
    portfolio_return: number
    benchmark: { stocks: number; bonds: number; bills: number }
    by_class: Record<string, { return: number; change: number }>
  }[]
}

export const api = {
  risk: () => req<RiskReport>('/portfolio/risk'),
  taxLots: () => req<TaxLotReport>('/tax-lots'),
  lotSale: (symbol: string, amount: number) => req<LotSale>(`/tax-lots/sell?symbol=${encodeURIComponent(symbol)}&amount=${amount}`),
  importLots: (file: File, accountId: number) => {
    const fd = new FormData()
    fd.append('file', file)
    fd.append('account_id', String(accountId))
    return req<{ lots: number; symbols: string[]; row_errors: RowError[] }>('/tax-lots/import', { method: 'POST', body: fd })
  },
  rebalance: () => req<Rebalance>('/rebalance'),
  performance: (assume = false) => req<Performance>(`/performance${assume ? '?assume_contributions=1' : ''}`),
  cashFlows: () => req<CashFlowRow[]>('/cashflows'),
  addCashFlow: (f: { on: string; amount: number; note?: string }) => req<CashFlowRow>('/cashflows', json('POST', f)),
  deleteCashFlow: (id: number) => req<null>(`/cashflows/${id}`, json('DELETE')),
  pensions: () => req<Pension[]>('/pensions'),
  savePension: (id: number, edit: PensionEdit) => req<Pension>(`/pensions/${id}`, json('PUT', edit)),
  deletePension: (id: number) => req<null>(`/pensions/${id}`, json('DELETE')),
  schedulerStatus: () => req<SchedulerStatus>('/scheduler/status'),
  liabilities: () => req<Liability[]>('/liabilities'),
  addLiability: (l: LiabilityIn) => req<Liability>('/liabilities', json('POST', l)),
  saveLiability: (l: Liability) => req<Liability>(`/liabilities/${l.id}`, json('PUT', l)),
  ingestLiabilities: (file: File) => {
    const fd = new FormData()
    fd.append('file', file)
    return req<{ parser: string; rows: number; created: string[]; updated: string[]; warnings: string[] }>('/liabilities/ingest', { method: 'POST', body: fd })
  },
  liabilityHelp: () => req<{ what: string; steps: string[] }[]>('/liabilities/help'),
  deleteLiability: (id: number) => req<null>(`/liabilities/${id}`, json('DELETE')),
  debt: () => req<DebtSummary>('/planner/debt'),
  portfolio: () => req<Portfolio>('/portfolio'),
  xray: () => req<XRay>('/portfolio/xray'),
  netWorth: () => req<NetWorthSummary>('/networth/summary'),
  profile: () => req<Profile>('/profile'),
  saveProfile: (p: Partial<Profile>) => req<Profile>('/profile', json('PUT', p)),
  fire: (w: FireWhatIf = {}) => {
    const q = new URLSearchParams()
    for (const [k, v] of Object.entries(w)) if (v !== undefined) q.set(k, typeof v === 'boolean' ? (v ? '1' : '0') : String(v))
    const qs = q.toString()
    return req<Fire>(`/planner/fire${qs ? `?${qs}` : ''}`)
  },
  events: () => req<PlannedEvent[]>('/planner/events'),
  addEvent: (e: PlannedEventIn) => req<PlannedEvent>('/planner/events', json('POST', e)),
  saveEvent: (e: PlannedEvent) => req<PlannedEvent>(`/planner/events/${e.id}`, json('PUT', e)),
  deleteEvent: (id: number) => req<null>(`/planner/events/${id}`, json('DELETE')),
  cash: () => req<Cash>('/planner/cash'),
  menuGrade: (id: number) => req<MenuGrade>(`/planner/menu-grade/${id}`),
  institutions: () => req<Institution[]>('/institutions'),
  createAccount: (a: { name: string; tax_bucket?: string; risk_tier?: string; institution?: string; is_restricted_plan?: boolean; owner?: string }) =>
    req<Account>('/accounts', json('POST', a)),
  updateAccount,
  setOwner: (a: Account, owner: string) => updateAccount(a, { owner: owner as Account['owner'] }),
  setCurrentEmployer: (a: Account, v: boolean) => updateAccount(a, { is_current_employer_plan: v }),
  sepp: (balance: number, age: number, method: string, rate = 0.05) =>
    req<{ annual_payment: number; ends_at_age: number; max_rate: number; rate_within_cap: boolean; warning: string }>(
      `/early-access/sepp?balance=${balance}&age=${age}&method=${method}&rate=${rate}`,
    ),
  earlyAccess: () => req<EarlyAccess>('/early-access'),
  rmd: () => req<RmdReport>('/rmd'),
  roth: () => req<RothConversions>('/planner/roth'),
  strategies: () => req<StrategyPlan>('/planner/strategies?detail=0&n_sims=1000'),
  stress: () => req<StressPlan>('/planner/stress?n_sims=1000'),
  healthcare: (magi: number, people: number) => req<HealthcarePlan>(`/planner/healthcare?magi=${magi}&people=${people}${people > 1 ? '&status=MFJ' : ''}`),
  realEstate: (q: string) => req<RealEstatePlan>(`/planner/real-estate${q}`),
  assumptions: () => req<AssumptionList>('/planner/assumptions'),
  saveAssumptions: (overrides: Record<string, number | null>) => req<AssumptionList>('/planner/assumptions', json('PUT', { overrides })),
  planHealth: () => req<PlanHealth>('/planner/health'),
  saveHealthSnapshot: () => req<PlanHealth>('/planner/health/snapshot', json('POST', {})),
  feeDrag: (balance: number, contribution: number, years: number, grossReturn: number, fee: number) =>
    req<FeeDrag>(`/planner/fee-drag?balance=${balance}&contribution=${contribution}&years=${years}&gross_return=${grossReturn}&fee=${fee}`),
  survivor: () => req<SurvivorPlan>('/planner/survivor'),
  scenarios: () => req<ScenarioList>('/planner/scenarios'),
  saveScenario: (x: { name: string; overrides: Record<string, number>; shock: number }) => req<SavedScenario>('/planner/scenarios', json('POST', x)),
  deleteScenario: (id: number) => req<null>(`/planner/scenarios/${id}`, json('DELETE')),
  compareScenarios: (ids: number[], presets: string[]) => req<ScenarioCompare>(`/planner/scenarios/compare?ids=${ids.join(',')}&presets=${presets.join(',')}`),
  tornado: () => req<Tornado>('/planner/tornado'),
  solve: (kind: string) => req<SolveResult>(`/planner/solve?kind=${kind}`),
  spending: (nominal: boolean, smile?: boolean) =>
    req<SpendingPlan>(`/planner/spending?nominal=${nominal ? 1 : 0}${smile === undefined ? '' : `&smile=${smile ? 1 : 0}`}`),
  eventTemplates: () => req<Record<string, { name: string; amount: number; kind: string }>>('/planner/event-templates'),
  addEventFromTemplate: (template: string, start_year: number) => req<unknown[]>('/planner/events/from-template', json('POST', { template, start_year })),
  savings: () => req<SavingsPlan>('/planner/savings'),
  socialSecurity: () => req<SsGrid>('/planner/social-security'),
  withdrawals: () => req<Withdrawals>('/planner/withdrawals'),
  ingest: (file: File, accountId?: number, allowDuplicate = false, owner?: Owner) => {
    const fd = new FormData()
    fd.append('file', file)
    if (accountId) fd.append('account_id', String(accountId))
    if (owner) fd.append('owner', owner)
    if (allowDuplicate) fd.append('allow_duplicate', '1')
    return req<IngestResult | IngestPreview>('/ingest', { method: 'POST', body: fd })
  },
  confirmIngest: (p: IngestPreview, accountId?: number, owner?: Owner) => {
    const fd = new FormData()
    if (owner) fd.append('owner', owner)
    fd.append('filename', p.filename)
    fd.append('rows', JSON.stringify({ rows: p.rows, source: p.source }))
    if (accountId) fd.append('account_id', String(accountId))
    fd.append('allow_duplicate', '1') // the user just reviewed this data
    return req<IngestResult>('/ingest', { method: 'POST', body: fd })
  },
  importLog: () => req<ImportLogEntry[]>('/ingest/log'),
  undoImport: (id: number) => req<{ undone: number[] }>(`/ingest/${id}/undo`, json('POST')),
  chatSessions: () => req<ChatSession[]>('/chat/sessions'),
  createChatSession: () => req<ChatSessionFull>('/chat/sessions', json('POST')),
  chatSession: (id: number) => req<ChatSessionFull>(`/chat/sessions/${id}`),
  renameChatSession: (id: number, title: string) => req<ChatSession>(`/chat/sessions/${id}`, json('PATCH', { title })),
  deleteChatSession: (id: number) => req<null>(`/chat/sessions/${id}`, json('DELETE')),
  sendChat: (id: number, content: string) =>
    req<{ session: ChatSession; user: ChatMsg; assistant: ChatMsg }>(`/chat/sessions/${id}/messages`, json('POST', { content })),
  deleteAccount: (id: number) => req<null>(`/accounts/${id}`, json('DELETE')),
  deleteHolding: (id: number) => req<null>(`/holdings/${id}`, json('DELETE')),
  unmapped: () => req<Holding[]>('/holdings/unmapped'),
  mapProxy: (holding_id: number, proxy_ticker: string) => req('/holdings/map-proxy', json('POST', { holding_id, proxy_ticker })),
  suggestProxy: (id: number) => req<{ ticker: string; rationale: string }>(`/holdings/${id}/suggest-proxy`, json('POST')),
  reports: () => req<Report[]>('/research/reports'),
  screener: () => req<Screen[]>('/research/screener'),
  runScreener: () => req<Screen[]>('/research/screener/run', json('POST')),
  deepDive: (symbol: string) => req<Report>('/research/deep-dive', json('POST', { symbol })),
  symbolDetail: (symbol: string) => req<SymbolDetail>(`/research/symbol/${encodeURIComponent(symbol)}`),
  whatIf: (symbol: string, amount: number) => req<WhatIf>('/research/what-if', json('POST', { symbol, amount })),
  llm: () =>
    req<{ provider: string; fast_model: string; reasoning_model: string; api_base: string; api_key_set: boolean; providers: string[] }>('/settings/llm'),
  saveLlm: (b: Record<string, string>) => req('/settings/llm', json('PUT', b)),
  testLlm: () => req<{ ok: boolean; reply?: string }>('/settings/llm/test', json('POST')),
  notif: () => req<{ discord_configured: boolean; smtp_host: string; smtp_to: string; smtp_user: string }>('/settings/notifications'),
  saveNotif: (b: Record<string, string>) => req('/settings/notifications', json('PUT', b)),
  testNotif: () => req<{ ok: boolean; channel: string }>('/settings/notifications/test', json('POST')),
}

export interface SavingsPlan {
  waterfall: {
    steps: { step: string; amount: number; room: number; why: string }[]
    unallocated: number
    limits: { year: number; rules_year: number; k401_max: number; ira_base: number; roth_ira_allowed: number }
  }
  checklist: { backdoor_viable: boolean; mega_backdoor_viable: boolean }
  fi: {
    numbers: Record<'lean' | 'fi' | 'fat' | 'barista', number>
    progress: Record<string, number>
    years_to: Record<string, number | null>
    coast: { needed_now: number; reached: boolean }
  }
  inputs: { annual_saving: number; investable_balance: number; annual_spend: number }
}

export interface StrategyPlan {
  portfolio: number
  years: number
  retire_age: number
  portfolio_source: string
  current_plan_spend_after_tax: number
  policies: {
    policy: string
    label: string
    safe_spend: Record<string, number>
    safe_spend_after_tax: Record<string, number>
    worst_year_spend_p10: number
    median_ending: number
  }[]
}

export interface StressPlan {
  inputs: { portfolio: number; initial_spend: number; years: number }
  data: { source_url: string; first_year: number; last_year: number }
  historical: { start_year: number; complete: boolean; years_covered: number; success: boolean; ending_real: number }[]
  rolling: { windows: number; success_rate: number | null; worst_start?: number }
  simulated: { method: string; description: string; success_rate: number; by_first5: { bucket: number; success_rate: number | null }[] }[]
  bucket: { improvement: number; bucket_years: number; plain: { success_rate: number }; bucket: { success_rate: number } }
}

export interface SpendingPlan {
  nominal: boolean
  base_annual: number
  model: { smile: boolean }
  rows: { age: number; phase: string; total: number; categories: Record<string, number> }[]
}

export interface HealthcarePlan {
  medicare: {
    irmaa_tier: number
    irmaa_monthly: number
    part_b_monthly: number
    part_d_monthly: number
    medigap_monthly: number
    annual: number
    rules_year: number
  }
  pre65: { age: number; benchmark: number; credit: number; net: number }[]
  ltc: { mode: string; probability: number; annual_cost: number; years: number; total: number }[]
  assumptions: { verified: boolean; source_url: string }
  magi_basis: string
}

export interface RealEstatePlan {
  home_value: number
  mortgage_balance: number
  equity: number
  projection: { year: number; value: number; mortgage: number; equity: number }[]
  paydown_vs_invest: { id: number; name: string; balance: number; apr: number; action: string; pay_down_amount: number; reason: string }[]
  downsize?: {
    net_proceeds: number
    cash_freed: number
    tax: number
    taxable_gain: number
    exclusion: number
    selling_costs: number
    upkeep_change_annual: number
  }
  relocation?: { new_spend: number; spend_change: number; state_tax_change: number; annual_saving: number }
  defaults: { appreciation: number; selling_cost_pct: number }
}

export interface SavedScenario {
  id: number
  name: string
  overrides: Record<string, number>
  shock: number
}
export interface ScenarioList {
  saved: SavedScenario[]
  presets: { name: string; label: string }[]
}
export interface ScenarioMetrics {
  success_rate: number
  bridge_success_rate: number
  median_final_real: number
  retire_age: number
  monthly_spend: number
}
export interface ScenarioCompare {
  base: ScenarioMetrics
  scenarios: { name: string; kind: string; label?: string; metrics: ScenarioMetrics; vs_base: Record<string, number | null> }[]
}
export interface Tornado {
  base_success: number
  bars: { input: string; low_label: string; high_label: string; low_delta: number; high_delta: number; swing: number }[]
}
export interface SolveResult {
  kind: string
  value: number | null
  unit: string
  current: number
  target_success: number
  note?: string
}

export interface SurvivorPlan {
  married: boolean
  deceased?: string
  social_security?: { household_before: number; household_after: number; monthly_lost: number }
  death_of_spouse?: {
    tax_before: number
    tax_after: number
    tax_increase: number
    income_before: number
    income_after: number
    spend_after: number
    after_tax_surplus_after: number
    widows_penalty: boolean
  }
  estate: { net_worth: number; exclusion: number; estimated_tax: number; flag: 'OK' | 'WATCH' | 'OVER'; headroom: number }
  beneficiaries: { accounts: { account: string; balance: number; check: string }[]; retitling: { item: string; note: string }[] }
  insurance: { life_need: number; life_gap: number; disability_target_monthly: number; disability_gap_monthly: number }
  defaults: { verified?: boolean; notes: string; source_url: string }
}

export interface Assumption {
  key: string
  label: string
  group: string
  default: number
  value: number
  min: number
  max: number
  source: string
  overridden: boolean
}
export interface AssumptionList {
  assumptions: Assumption[]
  overridden: number
}
export interface PlanHealth {
  health: { score: number; grade: 'STRONG' | 'OK' | 'WEAK'; parts: { name: string; weight: number; points: number; why: string }[] }
  diff: {
    has_previous: boolean
    metrics: { metric: string; before: number; after: number; change: number }[]
    assumptions: { key: string; before: number | null; after: number | null }[]
  }
  last_run_at: string | null
}
export interface FeeDrag {
  without_fee: number
  with_fee: number
  cost: number
  cost_pct: number
}

export interface XRay {
  total: number
  asset_class: Record<string, number>
  sector: Record<string, number>
  region: Record<string, number>
  market_cap: Record<string, number>
  overlap: { a: string; b: string; overlap: number; shared: number }[]
  concentration: {
    top_names: { symbol: string; weight: number }[]
    hhi_named: number
    named_share: number
    employer_symbol: string
    employer_weight: number
    warnings: string[]
  }
  coverage: { symbol: string; missing: string[]; fallback_used?: boolean }[]
  notes: string
}
