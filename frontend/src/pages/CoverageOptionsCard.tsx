import { useState } from 'react'
import { api, type CoverageCategory, type CoverageOption, type CoverageOptionInput } from '../api/client'
import { Badge, Button, Card, Err, Input, usd } from '../components/ui'
import { useAsync } from '../hooks'

const CATEGORIES: Record<CoverageCategory, string> = {
  PRE_MEDICARE: 'Pre-Medicare plan',
  MEDICARE_ADVANTAGE: 'Medicare Advantage',
  MEDIGAP: 'Medigap',
  DRUG: 'Prescription add-on',
  OTHER: 'Other',
}

const BLANK: CoverageOptionInput = {
  name: '',
  carrier: '',
  plan_code: '',
  category: 'PRE_MEDICARE',
  premium_by_year: {},
  premium_period: 'MONTHLY',
  premium_basis: 'PER_PERSON',
  deductible: 0,
  oop_max: 0,
  eligibility_min_age: 0,
  eligibility_max_age: null,
  requires_medicare_parts: '',
  requires_part_b_premium: false,
  includes_drugs: false,
  drug_option_id: null,
  owner: 'BOTH',
  cost_sharing_note: '',
  source_note: '',
  verified: false,
  active: true,
  sort_order: 0,
}

export const parsePrices = (s: string): Record<string, number> =>
  Object.fromEntries(
    s
      .split(',')
      .map((p) => p.split(':').map((x) => x.trim()))
      .filter((p) => p.length === 2 && p[0] !== '' && p[1] !== '' && !Number.isNaN(Number(p[1])))
      .map(([y, v]) => [y, Number(v)]),
  )
export const formatPrices = (p: Record<string, number>) =>
  Object.entries(p)
    .map(([y, v]) => `${y}: ${v}`)
    .join(', ')

const monthly = (o: CoverageOption) => {
  const ys = Object.keys(o.premium_by_year).sort()
  if (!ys.length) return 'no price yet'
  const y = ys[ys.length - 1]
  const v = o.premium_by_year[y]
  return `${usd(v)}/${o.premium_period === 'ANNUAL' ? 'yr' : 'mo'} (${y}${o.premium_basis === 'PER_HOUSEHOLD' ? ', household' : ', per person'})`
}

export default function CoverageOptionsCard() {
  const r = useAsync(api.coverageOptions, [])
  const [form, setForm] = useState<(CoverageOptionInput & { id?: number }) | null>(null)
  const [prices, setPrices] = useState('')
  const [err, setErr] = useState<unknown>(null)
  const opts = r.data?.options ?? []
  const choice = r.data?.choice ?? {}
  const drugs = opts.filter((o) => o.category === 'DRUG')
  const act = async (fn: () => Promise<unknown>) => {
    setErr(null)
    try {
      await fn()
      r.reload()
    } catch (e) {
      setErr(e)
    }
  }
  const edit = (o: CoverageOption | null) => {
    const f = o ? { ...o } : { ...BLANK }
    setForm(f)
    setPrices(formatPrices(f.premium_by_year))
  }
  const set = <K extends keyof CoverageOptionInput>(k: K, v: CoverageOptionInput[K]) => setForm((f) => (f ? { ...f, [k]: v } : f))
  const save = () =>
    form &&
    act(async () => {
      const { id, ...body } = form
      const payload = { ...body, premium_by_year: parsePrices(prices) }
      await (id ? api.saveCoverageOption(id, payload) : api.addCoverageOption(payload))
      setForm(null)
    })
  const selectable = opts.filter((o) => o.category !== 'DRUG' && o.active)

  return (
    <Card title="Health coverage options (instead of ACA / flat Medicare)">
      <Err error={err ?? r.error} />
      <p className="mb-2 text-xs text-slate-400">
        Add employer retiree plans, Medicare Advantage or drug add-ons. Pick one per person below and the plan uses its cost, once eligible, instead of the ACA
        premium or the flat Medicare figure. Ineligible years fall back to ACA / Medicare.
      </p>
      {(['SELF', 'SPOUSE'] as const).map((k) => (
        <label key={k} className="mb-1 block text-sm">
          {k === 'SELF' ? 'You' : 'Spouse'} use{' '}
          <select
            className="bg-transparent border-b"
            aria-label={`${k === 'SELF' ? 'Your' : 'Spouse'} coverage`}
            value={choice[k] ?? ''}
            onChange={(e) => act(() => api.setCoverageChoice({ [k]: e.target.value ? Number(e.target.value) : null }))}
          >
            <option value="">ACA before 65 / flat Medicare</option>
            {selectable
              .filter((o) => o.owner === 'BOTH' || o.owner === k)
              .map((o) => (
                <option key={o.id} value={o.id}>
                  {o.name}
                </option>
              ))}
          </select>
        </label>
      ))}
      <ul className="mt-3 divide-y divide-slate-800 text-sm">
        {opts.map((o) => (
          <li key={o.id} className="flex flex-wrap items-center justify-between gap-2 py-2">
            <div>
              <b>{o.name}</b> <span className="text-slate-400">{[o.carrier, CATEGORIES[o.category]].filter(Boolean).join(' · ')}</span>{' '}
              {!o.verified && <Badge tone="amber">unverified</Badge>} {!o.active && <Badge>inactive</Badge>}
              <div className="text-xs text-slate-400">
                {monthly(o)}
                {o.eligibility_min_age > 0 && ` · from age ${o.eligibility_min_age}`}
                {o.eligibility_max_age != null && ` to ${o.eligibility_max_age}`}
                {o.requires_medicare_parts && ` · needs Medicare ${o.requires_medicare_parts}`}
                {o.requires_part_b_premium && ' · Part B premium still paid'}
                {o.drug_option_id != null && ` · Rx: ${opts.find((d) => d.id === o.drug_option_id)?.name ?? 'add-on'}`}
                {o.cost_sharing_note ? ` · ${o.cost_sharing_note}` : o.category === 'PRE_MEDICARE' ? ' · cost sharing: to be confirmed' : ''}
              </div>
            </div>
            <div className="flex gap-2">
              <Button variant="ghost" onClick={() => edit(o)}>
                Edit
              </Button>
              <Button variant="ghost" onClick={() => window.confirm(`Delete ${o.name}?`) && act(() => api.deleteCoverageOption(o.id))}>
                Delete
              </Button>
            </div>
          </li>
        ))}
      </ul>
      {!form && (
        <Button className="mt-3" onClick={() => edit(null)}>
          Add option
        </Button>
      )}
      {form && (
        <div className="mt-3 grid gap-2 md:grid-cols-2">
          <Input label="Name" value={form.name} onChange={(e) => set('name', e.target.value)} />
          <Input label="Carrier" value={form.carrier} onChange={(e) => set('carrier', e.target.value)} />
          <Input label="Plan code" value={form.plan_code} onChange={(e) => set('plan_code', e.target.value)} />
          <label className="block text-sm text-slate-300">
            Type
            <select
              className="block w-full bg-transparent border-b"
              value={form.category}
              onChange={(e) => set('category', e.target.value as CoverageCategory)}
            >
              {Object.entries(CATEGORIES).map(([k, v]) => (
                <option key={k} value={k}>
                  {v}
                </option>
              ))}
            </select>
          </label>
          <Input label="Premiums by year (e.g. 2026: 1616, 2027: 1700)" value={prices} onChange={(e) => setPrices(e.target.value)} />
          <label className="block text-sm text-slate-300">
            Premium period
            <select
              className="block w-full bg-transparent border-b"
              value={form.premium_period}
              onChange={(e) => set('premium_period', e.target.value as 'MONTHLY' | 'ANNUAL')}
            >
              <option value="MONTHLY">Monthly</option>
              <option value="ANNUAL">Annual</option>
            </select>
          </label>
          <label className="block text-sm text-slate-300">
            Premium covers
            <select
              className="block w-full bg-transparent border-b"
              value={form.premium_basis}
              onChange={(e) => set('premium_basis', e.target.value as 'PER_PERSON' | 'PER_HOUSEHOLD')}
            >
              <option value="PER_PERSON">Each person</option>
              <option value="PER_HOUSEHOLD">Whole household</option>
            </select>
          </label>
          <label className="block text-sm text-slate-300">
            Available to
            <select
              className="block w-full bg-transparent border-b"
              value={form.owner}
              onChange={(e) => set('owner', e.target.value as 'SELF' | 'SPOUSE' | 'BOTH')}
            >
              <option value="BOTH">Both</option>
              <option value="SELF">You</option>
              <option value="SPOUSE">Spouse</option>
            </select>
          </label>
          <Input
            label="Eligible from age"
            type="number"
            value={form.eligibility_min_age}
            onChange={(e) => set('eligibility_min_age', Number(e.target.value))}
          />
          <Input
            label="Eligible until age (blank = no limit)"
            type="number"
            value={form.eligibility_max_age ?? ''}
            onChange={(e) => set('eligibility_max_age', e.target.value === '' ? null : Number(e.target.value))}
          />
          <Input label="Deductible" type="number" value={form.deductible} onChange={(e) => set('deductible', Number(e.target.value))} />
          <Input label="Out-of-pocket max" type="number" value={form.oop_max} onChange={(e) => set('oop_max', Number(e.target.value))} />
          <label className="block text-sm text-slate-300">
            Required Medicare parts
            <select
              className="block w-full bg-transparent border-b"
              value={form.requires_medicare_parts}
              onChange={(e) => set('requires_medicare_parts', e.target.value as CoverageOptionInput['requires_medicare_parts'])}
            >
              <option value="">None</option>
              <option value="A">A</option>
              <option value="B">B</option>
              <option value="A,B">A and B</option>
            </select>
          </label>
          <label className="block text-sm text-slate-300">
            Prescription add-on
            <select
              className="block w-full bg-transparent border-b"
              value={form.drug_option_id ?? ''}
              onChange={(e) => set('drug_option_id', e.target.value ? Number(e.target.value) : null)}
            >
              <option value="">None</option>
              {drugs
                .filter((d) => d.id !== form.id)
                .map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.name}
                  </option>
                ))}
            </select>
          </label>
          <Input label="Cost sharing (copays, coinsurance)" value={form.cost_sharing_note} onChange={(e) => set('cost_sharing_note', e.target.value)} />
          <Input label="Source" value={form.source_note} onChange={(e) => set('source_note', e.target.value)} />
          <div className="flex flex-wrap gap-4 text-sm md:col-span-2">
            {(
              [
                ['requires_part_b_premium', 'Part B premium still paid'],
                ['includes_drugs', 'Includes drug coverage'],
                ['verified', 'Verified against plan documents'],
                ['active', 'Active'],
              ] as const
            ).map(([k, label]) => (
              <label key={k}>
                <input type="checkbox" checked={form[k]} onChange={(e) => set(k, e.target.checked)} /> {label}
              </label>
            ))}
          </div>
          <div className="flex gap-2 md:col-span-2">
            <Button onClick={save} disabled={!form.name.trim()}>
              Save
            </Button>
            <Button variant="ghost" onClick={() => setForm(null)}>
              Cancel
            </Button>
          </div>
        </div>
      )}
    </Card>
  )
}
