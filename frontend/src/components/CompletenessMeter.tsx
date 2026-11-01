import type { Onboarding } from '../api/client'
import { Bar } from './ui'

/** Data-completeness score (computed server-side) plus what each missing input would improve. */
export default function CompletenessMeter({ c, showAll = false }: { c: Onboarding['completeness']; showAll?: boolean }) {
  const missing = c.inputs.filter((i) => !i.filled)
  return (
    <div>
      <div className="mb-1 flex items-baseline justify-between text-sm">
        <span className="text-slate-300">Data completeness</span>
        <span className="font-semibold" data-testid="completeness-score">
          {c.score}%
        </span>
      </div>
      <div role="progressbar" aria-label="Data completeness" aria-valuemin={0} aria-valuemax={100} aria-valuenow={c.score}>
        <Bar value={c.score} />
      </div>
      {missing.length === 0 ? (
        <p className="mt-2 text-xs text-slate-400">Everything the planner can use is filled in.</p>
      ) : (
        <ul className="mt-3 space-y-1.5 text-xs text-slate-400">
          {(showAll ? missing : missing.slice(0, 3)).map((i) => (
            <li key={i.key}>
              <span className="text-slate-200">{i.label}</span> (+{i.weight}) improves {i.improves}. <span className="text-slate-500">{i.where}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
