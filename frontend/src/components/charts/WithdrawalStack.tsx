import type { WithdrawalYear } from '../../api/client'
import StackedYears from './StackedYears'

const SERIES = [
  { key: 'draw_taxable', label: 'Taxable accounts' },
  { key: 'draw_pretax', label: 'Pre-tax (401k/IRA)' },
  { key: 'draw_roth', label: 'Roth' },
  { key: 'tax', label: 'Tax paid' },
]

/** Where each year's money comes from (taxable / pre-tax / Roth) alongside the tax bill. */
export default function WithdrawalStack({ years, loading, error }: { years?: WithdrawalYear[]; loading?: boolean; error?: unknown }) {
  return (
    <StackedYears
      title="Withdrawals and tax by year"
      rows={years as unknown as Record<string, number>[] | undefined}
      series={SERIES}
      loading={loading}
      error={error}
    />
  )
}
