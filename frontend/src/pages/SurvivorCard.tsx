import { api } from '../api/client'
import { Card, Err, usd } from '../components/ui'
import { useAsync } from '../hooks'

export default function SurvivorCard() {
  const r = useAsync(api.survivor, [])
  if (r.error) return <Err error={r.error} />
  const d = r.data
  if (!d) return null
  return (
    <Card title="Survivor and estate">
      {d.death_of_spouse && d.social_security && (
        <p className="text-sm">
          If {d.deceased?.toLowerCase()} dies: Social Security falls {usd(d.social_security.monthly_lost)}/mo, and tax on the same income goes{' '}
          {usd(d.death_of_spouse.tax_before)} → {usd(d.death_of_spouse.tax_after)}
          {d.death_of_spouse.widows_penalty ? ' (widow’s penalty)' : ''}. After-tax cushion at {usd(d.death_of_spouse.spend_after)} spend:{' '}
          {usd(d.death_of_spouse.after_tax_surplus_after)}.
        </p>
      )}
      <p className="mt-2 text-sm">
        Estate {usd(d.estate.net_worth)} vs {usd(d.estate.exclusion)} federal exclusion: <b>{d.estate.flag}</b>
        {d.estate.estimated_tax > 0 ? `, est. tax ${usd(d.estate.estimated_tax)}` : ''}.
      </p>
      <p className="mt-2 text-sm">
        Term-life gap {usd(d.insurance.life_gap)} (need {usd(d.insurance.life_need)}); disability gap {usd(d.insurance.disability_gap_monthly)}/mo of{' '}
        {usd(d.insurance.disability_target_monthly)}.
      </p>
      <details className="mt-2 text-sm">
        <summary>Beneficiary and re-titling checklist</summary>
        <ul className="list-disc pl-5">
          {d.beneficiaries.retitling.map((x) => (
            <li key={x.item}>
              <b>{x.item}:</b> {x.note}
            </li>
          ))}
          {d.beneficiaries.accounts.map((a) => (
            <li key={a.account}>
              {a.account} ({usd(a.balance)}): {a.check}
            </li>
          ))}
        </ul>
      </details>
      <p className="mt-2 text-xs text-slate-400">
        {d.defaults.verified === false ? 'Estate figures not read directly from irs.gov. ' : ''}Beneficiaries are not stored; verify with each custodian.
      </p>
    </Card>
  )
}
