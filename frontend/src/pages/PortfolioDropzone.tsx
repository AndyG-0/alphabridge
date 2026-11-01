import { Trash2, Upload } from 'lucide-react'
import { useState } from 'react'
import {
  api,
  type Account,
  type DuplicateDiff,
  type Holding,
  type IngestPreview,
  type Institution,
  type Owner,
  type Pension,
  type RowError,
} from '../api/client'
import { Badge, Button, Card, Err, Input, usd } from '../components/ui'
import { useAsync } from '../hooks'
import ImportHistoryCard from './ImportHistoryCard'
import SpendingCard from './SpendingCard'
import PerformanceCard from './PerformanceCard'
import RebalanceCard from './RebalanceCard'
import RiskCard from './RiskCard'
import TaxLotsCard from './TaxLotsCard'
import XRayCard from './XRayCard'

function MenuGradeCard({ account }: { account: Account }) {
  const g = useAsync(() => api.menuGrade(account.id), [account.id])
  if (!g.data) return null
  return (
    <Card title={`401(k) menu grade — ${account.name}`}>
      <div className="flex items-center gap-3">
        <span className="text-3xl font-semibold">{g.data.grade}</span>
        <span className="text-sm text-slate-400">Weighted expense ratio {(g.data.weighted_expense_ratio * 100).toFixed(3)}%</span>
      </div>
      {g.data.suggestions.map((s) => (
        <p key={s.from} className="mt-2 text-sm">
          Swap <b>{s.from}</b> → <b>{s.to}</b> ({s.to_name}) saves {usd(s.annual_savings)}/yr
        </p>
      ))}
      {g.data.suggestions.length === 0 && <p className="mt-2 text-sm text-slate-400">No cheaper same-class funds on the plan menu.</p>}
    </Card>
  )
}

function PensionCard({ p, who, onChange, onError }: { p: Pension; who: string; onChange: () => void; onError: (e: unknown) => void }) {
  const save = async (edit: Parameters<typeof api.savePension>[1]) => {
    try {
      await api.savePension(p.id, edit)
      onChange()
    } catch (e) {
      onError(e)
    }
  }
  const pr = p.projection
  return (
    <Card title={`${who} pension — ${p.name}`}>
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <Badge tone="green">{usd(p.plan_balance)}</Badge>
        {p.as_of && <Badge>as of {p.as_of}</Badge>}
        <Badge>{(p.pay_credit_pct * 100).toFixed(1)}% pay credit</Badge>
        <Badge>{(p.interest_credit_rate * 100).toFixed(1)}% interest (est.)</Badge>
        <button className="ml-auto flex items-center gap-1 text-xs text-red-400" onClick={() => api.deletePension(p.id).then(onChange, onError)}>
          <Trash2 size={14} />
          Remove
        </button>
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <Input
          label="Benefits start at age"
          type="number"
          min={50}
          max={80}
          defaultValue={p.start_age}
          onBlur={(e) => Number(e.target.value) !== p.start_age && save({ start_age: Number(e.target.value) })}
        />
        <label className="block text-sm text-slate-300">
          Payout
          <select
            className="mt-1 w-full rounded-xl border border-slate-700 bg-slate-950 px-3 py-2 text-slate-100"
            value={p.payout}
            onChange={(e) => save({ payout: e.target.value as Pension['payout'] })}
          >
            <option value="ANNUITY">Monthly annuity</option>
            <option value="LUMP_SUM">Lump sum</option>
          </select>
        </label>
      </div>
      {pr && (
        <p className="mt-3 text-sm text-slate-300">
          Employer credits keep adding until {who === 'Your' ? 'you retire' : 'they retire'} ({pr.years_of_credits.toFixed(1)} yrs of credits). Projected in
          today&apos;s dollars: <b>{usd(pr.balance_at_start)}</b> at age {p.start_age}
          {p.payout === 'ANNUITY' ? (
            <>
              , about <b>{usd(pr.monthly)}/mo</b> to age 95.
            </>
          ) : (
            ' as a lump sum.'
          )}{' '}
          Change the retirement age in the What-If Lab to see it move.
        </p>
      )}
      <p className="mt-1 text-xs text-slate-500">
        The plan&apos;s real annuity factors aren&apos;t on the statement, so the monthly figure assumes a level 1% real payout. Not part of your investable
        portfolio.
      </p>
    </Card>
  )
}

function ProxyRow({ h, onDone }: { h: Holding; onDone: () => void }) {
  const [t, setT] = useState('')
  const [err, setErr] = useState<unknown>(null)
  const [hint, setHint] = useState('')
  return (
    <div className="space-y-1 rounded-xl border border-slate-800 p-3">
      <div className="text-sm">
        <b>{h.name}</b> <span className="text-slate-500">{usd(h.market_value)}</span>
      </div>
      <div className="flex gap-2">
        <Input placeholder="Proxy ticker e.g. VTIVX" value={t} onChange={(e) => setT(e.target.value)} />
        <Button
          variant="ghost"
          onClick={() =>
            api
              .suggestProxy(h.id)
              .then((s) => {
                setT(s.ticker)
                setHint(s.rationale)
              })
              .catch(setErr)
          }
        >
          AI suggest
        </Button>
        <Button disabled={!t} onClick={() => api.mapProxy(h.id, t).then(onDone).catch(setErr)}>
          Map
        </Button>
      </div>
      {hint && <p className="text-xs text-slate-400">{hint}</p>}
      <Err error={err} />
    </div>
  )
}

function DocsHelp({ list }: { list: Institution[] }) {
  return (
    <Card title="Where to get your documents">
      <div className="space-y-2">
        {list.map((i) => (
          <details key={i.id} className="rounded-xl border border-slate-800 p-3">
            <summary className="cursor-pointer text-sm font-medium">{i.label}</summary>
            {i.login_url && (
              <a className="mt-2 inline-block text-sm text-emerald-400 underline" href={i.login_url} target="_blank" rel="noopener noreferrer">
                Open {i.label} site ↗
              </a>
            )}
            {i.docs.map((d) => (
              <div key={d.what} className="mt-2 text-sm">
                <p className="text-slate-300">
                  {d.what} <span className="text-xs text-slate-500">({d.formats.join(' / ')})</span>
                </p>
                <ol className="ml-5 list-decimal text-slate-400">
                  {d.steps.map((s) => (
                    <li key={s}>{s}</li>
                  ))}
                </ol>
              </div>
            ))}
          </details>
        ))}
      </div>
    </Card>
  )
}

function PreviewCard({
  p,
  busy,
  onChange,
  onConfirm,
  onCancel,
}: {
  p: IngestPreview
  busy: boolean
  onChange: (p: IngestPreview) => void
  onConfirm: () => void
  onCancel: () => void
}) {
  const edit = (i: number, k: 'symbol' | 'shares' | 'market_value' | 'account_name', v: string) =>
    onChange({ ...p, rows: p.rows.map((r, j) => (j === i ? { ...r, [k]: k === 'symbol' || k === 'account_name' ? v : Number(v) || 0 } : r)) })
  const tone = { ok: 'text-emerald-400', warn: 'text-amber-300', fail: 'text-red-400' } as const
  const mark = { ok: '✓', warn: '!', fail: '✗' } as const
  return (
    <div className="mt-3 rounded-xl border border-slate-700 p-3 text-sm">
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <b>Review before importing</b>
        <Badge>{p.source === 'vision' ? 'Read by AI vision' : p.source === 'ocr' ? 'Read by OCR' : 'Read by AI'}</Badge>
        <Badge tone={p.confidence === 'high' ? 'green' : p.confidence === 'medium' ? 'amber' : 'red'}>{p.confidence} confidence</Badge>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full">
          <thead className="text-left text-xs text-slate-500">
            <tr>
              <th>Account</th>
              <th>Symbol</th>
              <th className="text-right">Shares</th>
              <th className="text-right">Value</th>
            </tr>
          </thead>
          <tbody>
            {p.rows.map((r, i) => (
              <tr key={i} className="border-t border-slate-800">
                <td>
                  <input
                    aria-label="Account name"
                    className="w-48 rounded bg-slate-950 px-2 py-1"
                    value={r.account_name ?? ''}
                    onChange={(e) => edit(i, 'account_name', e.target.value)}
                  />
                </td>
                <td>
                  <input
                    aria-label="Symbol"
                    className="w-24 rounded bg-slate-950 px-2 py-1 font-mono"
                    value={r.symbol}
                    onChange={(e) => edit(i, 'symbol', e.target.value.toUpperCase())}
                  />
                </td>
                <td className="text-right">
                  <input
                    aria-label="Shares"
                    type="number"
                    className="w-24 rounded bg-slate-950 px-2 py-1 text-right"
                    value={r.shares}
                    onChange={(e) => edit(i, 'shares', e.target.value)}
                  />
                </td>
                <td className="text-right">
                  <input
                    aria-label="Value"
                    type="number"
                    className="w-28 rounded bg-slate-950 px-2 py-1 text-right"
                    value={r.market_value}
                    onChange={(e) => edit(i, 'market_value', e.target.value)}
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <ul className="mt-2 space-y-0.5 text-xs">
        {p.checks.map((c, i) => (
          <li key={i} className={tone[c.level]}>
            {mark[c.level]} {c.message}
          </li>
        ))}
        {p.warnings.map((w, i) => (
          <li key={`w${i}`} className="text-slate-400">
            {w}
          </li>
        ))}
      </ul>
      <p className="mt-2 text-xs text-slate-500">Edits here are used as-is; confirm they match your document.</p>
      <div className="mt-2 flex gap-2">
        <Button disabled={busy} onClick={onConfirm}>
          Confirm import
        </Button>
        <Button variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
      </div>
    </div>
  )
}

const DIFF_TONE = { same: 'text-slate-500', changed: 'text-amber-300', new: 'text-emerald-400', missing: 'text-red-400' } as const
const DIFF_LABEL = { same: 'Same', changed: 'Changed', new: 'New in file', missing: 'Only in account' } as const

function DupDiff({ diff }: { diff: DuplicateDiff }) {
  const [showSame, setShowSame] = useState(false)
  const m = diff.summary
  const rows = diff.rows.filter((r) => showSame || r.status !== 'same')
  const num = (v: number | null) => (v == null ? '—' : v.toLocaleString(undefined, { maximumFractionDigits: 3 }))
  return (
    <div className="mt-2">
      <p className="text-slate-300">
        {m.same} same · {m.changed} changed · {m.new} new in file · {m.missing} only in account — total {usd(m.old_total)} → {usd(m.new_total)} (
        {m.total_delta_pct >= 0 ? '+' : ''}
        {m.total_delta_pct.toFixed(1)}%)
      </p>
      {m.missing > 0 && <p className="text-xs text-red-400">Replacing removes the “only in account” holdings.</p>}
      <div className="mt-2 overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="text-left text-slate-500">
              <th>Symbol</th>
              <th>Status</th>
              <th className="text-right">Shares (account → file)</th>
              <th className="text-right">Value (account → file)</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.symbol}>
                <td>{r.symbol}</td>
                <td className={DIFF_TONE[r.status]}>{DIFF_LABEL[r.status]}</td>
                <td className="text-right">
                  {num(r.old_shares)} → {num(r.new_shares)}
                </td>
                <td className="text-right">
                  {r.old_value == null ? '—' : usd(r.old_value)} → {r.new_value == null ? '—' : usd(r.new_value)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {m.same > 0 && (
        <button className="mt-1 text-xs text-slate-400 underline" onClick={() => setShowSame((v) => !v)}>
          {showSame ? 'Hide' : 'Show'} {m.same} identical holdings
        </button>
      )}
    </div>
  )
}

const ACCOUNT_TYPES: Record<string, string> = {
  TAXABLE_BROKERAGE: 'Taxable brokerage',
  ROTH: 'Roth IRA',
  PRE_TAX_401K: '401(k) / pre-tax',
  HSA: 'HSA',
  CASH_MMF: 'Cash / money market',
}
const RISK_TIERS: Record<string, string> = {
  SAFE_CORE: 'Safe core',
  MODERATE_GROWTH: 'Moderate growth',
  AGGRESSIVE_SATELLITE: 'Aggressive satellite',
  CASH: 'Cash',
}
export default function PortfolioDropzone() {
  const pf = useAsync(api.portfolio)
  const inst = useAsync(api.institutions)
  const labels = inst.data
    ?.filter((i) => i.id !== 'OTHER' && i.kind !== 'other')
    .map((i) => i.label.replace(/ \(.*\)$/, ''))
    .slice(0, 5)
    .join(' / ')
  const instLabel = (id: string) => inst.data?.find((i) => i.id === id)?.label ?? id
  const un = useAsync(api.unmapped)
  const ea = useAsync(api.earlyAccess, [pf.data])
  const pens = useAsync(api.pensions)
  const prof = useAsync(api.profile)
  const spouse = prof.data?.spouse_age ? prof.data.spouse_name || 'Spouse' : ''
  const OWNERS: Record<Owner, string> = { SELF: 'Mine', SPOUSE: spouse ? `${spouse}'s` : "Spouse's", JOINT: 'Joint' }
  const HEADERS: Record<Owner, string> = { SELF: 'Your accounts', SPOUSE: spouse ? `${spouse}'s accounts` : "Spouse's accounts", JOINT: 'Joint accounts' }
  const [owner, setOwner] = useState<Owner | ''>('')
  const [askOwner, setAskOwner] = useState<{ names: string; retry: (o: Owner) => void } | null>(null)
  const [accountId, setAccountId] = useState<number | ''>('')
  const [newName, setNewName] = useState('')
  const [newType, setNewType] = useState('')
  const [msg, setMsg] = useState('')
  const [logVersion, setLogVersion] = useState(0)
  const [rowErrors, setRowErrors] = useState<RowError[]>([])
  const [err, setErr] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)
  const [over, setOver] = useState(false)

  const [review, setReview] = useState<IngestPreview | null>(null)
  const [dup, setDup] = useState<{ file: File; id: number; name: string; diff?: DuplicateDiff } | null>(null)
  const [confirmDel, setConfirmDel] = useState('')

  const needsOwner = (e: unknown, retry: (o: Owner) => void) => {
    const d = e as { status?: number; data?: { needs_owner?: boolean; error?: string } }
    if (d.status === 409 && d.data?.needs_owner) {
      setAskOwner({ names: d.data.error ?? '', retry })
      return true
    }
    return false
  }
  const upload = async (f: File, target: number | undefined = accountId || undefined, allowDup = false, who: Owner | '' = owner) => {
    setBusy(true)
    setErr(null)
    setMsg('')
    setRowErrors([])
    setDup(null)
    setAskOwner(null)
    try {
      const r = await api.ingest(f, target, allowDup, who || undefined)
      if ('preview' in r) {
        setReview(r)
        return
      }
      if (r.pension) {
        setMsg(`Imported pension balance ${usd(r.pension.plan_balance)} for ${r.pension.owner === 'SPOUSE' ? 'spouse' : 'you'}.`)
        pens.reload()
        return
      }
      const same = r.accounts?.length && r.unchanged?.length === r.accounts.length
      setMsg(same ? 'Nothing changed: these holdings were already imported.' : `Imported ${r.rows} holdings (${r.parser}).`)
      setRowErrors(r.row_errors ?? [])
      setLogVersion((v) => v + 1)
      pf.reload()
      un.reload()
    } catch (e) {
      const data = (e as { data?: { duplicate_of?: { id: number; name: string }; diff?: DuplicateDiff } }).data
      const d = data?.duplicate_of
      if ((e as { status?: number }).status === 409 && d) setDup({ file: f, ...d, diff: data?.diff })
      else if (
        !needsOwner(e, (o) => {
          setOwner(o)
          upload(f, target, allowDup, o)
        })
      )
        setErr(e)
    } finally {
      setBusy(false)
    }
  }
  const confirmReview = async (who: Owner | '' = owner) => {
    if (!review) return
    setBusy(true)
    setErr(null)
    setAskOwner(null)
    try {
      const r = await api.confirmIngest(review, accountId || undefined, who || undefined)
      setMsg(`Imported ${r.rows} holdings (${review.source === 'ocr' ? 'OCR' : 'AI'}, reviewed).`)
      setReview(null)
      pf.reload()
      un.reload()
    } catch (e) {
      if (
        !needsOwner(e, (o) => {
          setOwner(o)
          confirmReview(o)
        })
      )
        setErr(e)
    } finally {
      setBusy(false)
    }
  }
  const remove = async (key: string, fn: () => Promise<unknown>) => {
    if (confirmDel !== key) {
      setConfirmDel(key)
      return
    }
    try {
      await fn()
      setConfirmDel('')
      pf.reload()
      un.reload()
    } catch (e) {
      setErr(e)
    }
  }
  const editAccount = async (a: Account, patch: Parameters<typeof api.updateAccount>[1]) => {
    try {
      await api.updateAccount(a, patch)
      pf.reload()
      ea.reload()
    } catch (e) {
      setErr(e)
    }
  }
  const createAcct = async () => {
    try {
      const a = await api.createAccount({
        name: newName,
        ...(owner ? { owner } : {}),
        ...(newType === 'HSA' ? { tax_bucket: 'HSA', risk_tier: 'MODERATE_GROWTH' } : {}),
      }) // backend infers institution/bucket/tier from the name
      setNewName('')
      setNewType('')
      setAccountId(a.id)
      pf.reload()
    } catch (e) {
      setErr(e)
    }
  }

  return (
    <div className="space-y-4">
      <PerformanceCard />
      <RiskCard />
      <RebalanceCard />
      <TaxLotsCard />
      <XRayCard />
      <Card title="Statement dropzone">
        <div className="mb-3 grid gap-3 md:grid-cols-3">
          <label className="block text-sm text-slate-300">
            Target account
            <select
              className="mt-1 w-full rounded-xl border border-slate-700 bg-slate-950 px-3 py-2"
              value={accountId}
              onChange={(e) => setAccountId(e.target.value ? Number(e.target.value) : '')}
            >
              <option value="">Auto-detect from file</option>
              {pf.data?.accounts.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name} ({OWNERS[a.owner]})
                </option>
              ))}
            </select>
          </label>
          {!accountId && (
            <label className="block text-sm text-slate-300">
              Whose account is this?
              <select
                className="mt-1 w-full rounded-xl border border-slate-700 bg-slate-950 px-3 py-2"
                value={owner}
                onChange={(e) => setOwner(e.target.value as Owner | '')}
              >
                <option value="">Ask me if it's unclear</option>
                {(Object.keys(OWNERS) as Owner[]).map((o) => (
                  <option key={o} value={o}>
                    {OWNERS[o]}
                  </option>
                ))}
              </select>
              <span className="mt-1 block text-xs text-slate-500">Pick this when you both have accounts with the same name, like two Fidelity 401(k)s.</span>
            </label>
          )}
          <div className="flex items-end gap-2">
            <Input label="New account" placeholder="e.g. Chase Checking" value={newName} onChange={(e) => setNewName(e.target.value)} />
            <select
              aria-label="Account type"
              className="rounded-xl border border-slate-700 bg-slate-950 px-3 py-2 text-sm"
              value={newType}
              onChange={(e) => setNewType(e.target.value)}
              title="HSA: tax-free for medical, kept out of bridge funds. FSAs aren't tracked (use-it-or-lose-it, not investable)."
            >
              <option value="">Type: detect from name</option>
              <option value="HSA">HSA</option>
            </select>
            <Button variant="ghost" disabled={!newName} onClick={createAcct}>
              Add
            </Button>
          </div>
        </div>
        <label
          onDragOver={(e) => {
            e.preventDefault()
            setOver(true)
          }}
          onDragLeave={() => setOver(false)}
          onDrop={(e) => {
            e.preventDefault()
            setOver(false)
            const f = e.dataTransfer.files[0]
            if (f) upload(f)
          }}
          className={`flex cursor-pointer flex-col items-center gap-2 rounded-2xl border-2 border-dashed p-8 text-center ${over ? 'border-emerald-400 bg-emerald-950/30' : 'border-slate-700'}`}
        >
          <Upload />
          <span className="text-sm">{busy ? 'Parsing…' : `Drop a ${labels ?? 'statement'} CSV, PDF or photo, or tap to choose`}</span>
          <input
            type="file"
            accept=".csv,.ofx,.qfx,.qif,.pdf,.png,.jpg,.jpeg"
            className="hidden"
            onChange={(e) => {
              const f = e.target.files?.[0]
              if (f) upload(f)
              e.target.value = ''
            }}
          />
        </label>
        {review && <PreviewCard p={review} busy={busy} onChange={setReview} onConfirm={() => confirmReview()} onCancel={() => setReview(null)} />}
        {askOwner && (
          <div className="mt-3 rounded-xl border border-amber-600 bg-amber-950/30 p-3 text-sm">
            <p className="text-amber-300">{askOwner.names}</p>
            <div className="mt-2 flex flex-wrap gap-2">
              {(Object.keys(OWNERS) as Owner[]).map((o) => (
                <Button key={o} variant={o === 'SELF' ? 'primary' : 'ghost'} onClick={() => askOwner.retry(o)}>
                  {OWNERS[o]}
                </Button>
              ))}
              <Button variant="ghost" onClick={() => setAskOwner(null)}>
                Cancel
              </Button>
            </div>
          </div>
        )}
        {dup && (
          <div className="mt-3 rounded-xl border border-amber-600 bg-amber-950/30 p-3 text-sm">
            <p className="text-amber-300">This looks like a duplicate of “{dup.name}”, which already holds mostly the same funds at a similar value.</p>
            {dup.diff && <DupDiff diff={dup.diff} />}
            <div className="mt-2 flex flex-wrap gap-2">
              <Button onClick={() => upload(dup.file, dup.id)}>Replace “{dup.name}” with this file</Button>
              <Button variant="ghost" onClick={() => upload(dup.file, accountId || undefined, true)}>
                Import anyway
              </Button>
              <Button variant="ghost" onClick={() => setDup(null)}>
                Cancel
              </Button>
            </div>
          </div>
        )}
        {msg && <p className="mt-2 text-sm text-emerald-400">{msg}</p>}
        {rowErrors.length > 0 && (
          <ul className="mt-2 space-y-1 text-xs">
            {rowErrors.map((e) => (
              <li key={`${e.line}-${e.symbol}`} className={e.level === 'error' ? 'text-red-400' : 'text-amber-300'}>
                Line {e.line} ({e.symbol}): {e.error}
              </li>
            ))}
          </ul>
        )}
        <Err error={err} />
      </Card>

      {inst.data && <DocsHelp list={inst.data} />}

      {un.data && un.data.length > 0 && (
        <Card title="Map plan funds to public proxy tickers">
          <p className="mb-2 text-xs text-slate-400">Employer-plan funds without a public ticker need a proxy so prices and risk can be tracked.</p>
          <div className="space-y-2">
            {un.data.map((h) => (
              <ProxyRow
                key={h.id}
                h={h}
                onDone={() => {
                  un.reload()
                  pf.reload()
                }}
              />
            ))}
          </div>
        </Card>
      )}

      {pens.data?.map((p) => (
        <PensionCard key={p.id} p={p} who={p.owner === 'SPOUSE' ? spouse || 'Spouse' : 'Your'} onChange={pens.reload} onError={setErr} />
      ))}

      {pf.data?.accounts
        .filter((a) => a.is_restricted_plan)
        .map((a) => (
          <MenuGradeCard key={a.id} account={a} />
        ))}

      <ImportHistoryCard version={logVersion} onChanged={() => pf.reload()} />
      <SpendingCard />

      {(['SELF', 'SPOUSE', 'JOINT'] as Owner[]).map((o) => {
        const accts = pf.data?.accounts.filter((a) => a.owner === o) ?? []
        if (!accts.length) return null
        return (
          <section key={o} className="space-y-3">
            <h2 className="flex items-baseline justify-between border-b border-slate-800 pb-1 text-base font-semibold">
              {HEADERS[o]}
              <span className="text-sm font-normal text-slate-400">{usd(accts.reduce((t, a) => t + a.total, 0))}</span>
            </h2>
            {accts.map((a) => (
              <Card key={a.id} title={a.name}>
                <div className="mb-2 flex flex-wrap gap-2">
                  <Badge>{instLabel(a.institution)}</Badge>
                  <select
                    aria-label="Account type"
                    className="rounded-lg border border-slate-700 bg-slate-950 px-2 py-0.5 text-xs"
                    value={a.tax_bucket}
                    onChange={(e) => editAccount(a, { tax_bucket: e.target.value })}
                  >
                    {Object.entries(ACCOUNT_TYPES).map(([v, label]) => (
                      <option key={v} value={v}>
                        {label}
                      </option>
                    ))}
                  </select>
                  <select
                    aria-label="Risk tier"
                    className="rounded-lg border border-slate-700 bg-slate-950 px-2 py-0.5 text-xs"
                    value={a.risk_tier}
                    onChange={(e) => editAccount(a, { risk_tier: e.target.value })}
                  >
                    {Object.entries(RISK_TIERS).map(([v, label]) => (
                      <option key={v} value={v}>
                        {label}
                      </option>
                    ))}
                  </select>
                  <Badge tone="green">{usd(a.total)}</Badge>
                  {a.tax_bucket === 'PRE_TAX_401K' &&
                    (() => {
                      const x = ea.data?.accounts.find((e) => e.id === a.id)
                      return x ? (
                        <Badge tone={x.accessible_at < 59.5 ? 'green' : 'amber'}>
                          {x.accessible_at < 59.5 ? `Penalty-free from ` : 'Penalty-free at 59.5'}
                        </Badge>
                      ) : null
                    })()}
                  {a.tax_bucket === 'PRE_TAX_401K' && (
                    <label className="flex items-center gap-1 text-xs text-slate-300" title="The Rule of 55 only reaches the plan of the employer you leave">
                      <input
                        type="checkbox"
                        checked={a.is_current_employer_plan}
                        onChange={async (e) => {
                          try {
                            await api.setCurrentEmployer(a, e.target.checked)
                            pf.reload()
                          } catch (x) {
                            setErr(x)
                          }
                        }}
                      />
                      Current employer's plan
                    </label>
                  )}
                  <select
                    aria-label="Account owner"
                    className="rounded-lg border border-slate-700 bg-slate-950 px-2 py-0.5 text-xs"
                    value={a.owner}
                    onChange={async (e) => {
                      try {
                        await api.setOwner(a, e.target.value)
                        pf.reload()
                      } catch (x) {
                        setErr(x)
                      }
                    }}
                  >
                    {(Object.keys(OWNERS) as Owner[]).map((x) => (
                      <option key={x} value={x}>
                        {OWNERS[x]}
                      </option>
                    ))}
                  </select>
                  <button className="ml-auto flex items-center gap-1 text-xs text-red-400" onClick={() => remove(`a${a.id}`, () => api.deleteAccount(a.id))}>
                    <Trash2 size={14} />
                    {confirmDel === `a${a.id}` ? 'Click again to delete account' : 'Delete account'}
                  </button>
                </div>
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead className="text-left text-xs text-slate-500">
                      <tr>
                        <th>Symbol</th>
                        <th>Name</th>
                        <th className="text-right">Shares</th>
                        <th className="text-right">Value</th>
                        <th></th>
                      </tr>
                    </thead>
                    <tbody>
                      {a.holdings.map((h) => (
                        <tr key={h.id} className="border-t border-slate-800">
                          <td className="py-1 font-mono">{h.proxy_ticker ?? h.symbol}</td>
                          <td className="max-w-48 truncate text-slate-400">{h.name}</td>
                          <td className="text-right">{h.shares.toLocaleString()}</td>
                          <td className="text-right">{usd(h.market_value)}</td>
                          <td className="pl-2 text-right">
                            <button
                              aria-label="Delete holding"
                              className="text-xs text-red-400"
                              onClick={() => remove(`h${h.id}`, () => api.deleteHolding(h.id))}
                            >
                              {confirmDel === `h${h.id}` ? 'Confirm' : <Trash2 size={14} />}
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </Card>
            ))}
          </section>
        )
      })}
    </div>
  )
}
