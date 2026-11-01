import type { ReactNode } from 'react'

export interface FrameTable {
  caption: string
  headers: string[]
  rows: (string | number)[][]
}

export const money = (v: number) => (Math.abs(v) >= 1e6 ? `$${(v / 1e6).toFixed(1)}M` : Math.abs(v) >= 1e3 ? `$${+(v / 1e3).toFixed(1)}k` : `$${Math.round(v)}`)

export const isNum = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v)

/** Shared recharts text/grid/tooltip styling driven by the theme tokens in index.css. */
export const axisTick = { fontSize: 11, fill: 'var(--viz-axis)' }
export const gridStroke = 'var(--viz-grid)'
export const tooltipStyle = { background: 'var(--popover)', border: '1px solid var(--border)', borderRadius: 12, fontSize: 12 }

/**
 * Wraps every chart: title, loading / error / empty / bad-number states, a legend (identity is never color alone),
 * and a table view so the numbers are available to screen readers and when contrast is marginal.
 */
export default function ChartFrame({
  title,
  loading,
  error,
  empty,
  invalid,
  legend,
  table,
  height = 224,
  showTitle,
  children,
}: {
  title: string
  loading?: boolean
  error?: unknown
  empty?: boolean
  invalid?: boolean
  legend?: { label: string; color: string }[]
  table?: FrameTable
  height?: number
  showTitle?: boolean
  children: ReactNode
}) {
  let body: ReactNode = null
  if (loading) body = <p className="text-sm text-slate-400">Loading chart…</p>
  else if (error)
    body = (
      <p role="alert" className="text-sm text-red-400">
        Chart unavailable: {error instanceof Error ? error.message : String(error)}
      </p>
    )
  else if (invalid) body = <p className="text-sm text-amber-300">Some values are not valid numbers, so this chart is hidden rather than drawn wrong.</p>
  else if (empty) body = <p className="text-sm text-slate-400">Nothing to chart yet.</p>
  return (
    <figure aria-label={title} className="m-0">
      {showTitle && <figcaption className="mb-1 text-sm font-medium text-slate-300">{title}</figcaption>}
      {body ?? (
        <>
          <div style={{ height }} role="img" aria-label={`${title}. A table view follows.`}>
            {children}
          </div>
          {legend && legend.length > 1 && (
            <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-300" aria-label="Legend">
              {legend.map((l) => (
                <li key={l.label} className="flex items-center gap-1.5">
                  <span aria-hidden className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: l.color }} />
                  {l.label}
                </li>
              ))}
            </ul>
          )}
          {table && (
            <details className="mt-2 text-xs text-slate-400">
              <summary className="cursor-pointer">View as table</summary>
              <div tabIndex={0} role="region" aria-label={`${title} table`} className="mt-1 max-h-48 overflow-auto">
                <table className="w-full">
                  <caption className="sr-only">{table.caption}</caption>
                  <thead>
                    <tr>
                      {table.headers.map((h) => (
                        <th key={h} scope="col" className="text-left font-medium">
                          {h}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {table.rows.map((r, i) => (
                      <tr key={i}>
                        {r.map((c, j) => (
                          <td key={j}>{c}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </details>
          )}
        </>
      )}
    </figure>
  )
}
