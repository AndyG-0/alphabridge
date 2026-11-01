import { ArrowRight } from 'lucide-react'
import { Link } from 'react-router-dom'
import { api, type ActionItem } from '../api/client'
import { useAsync } from '../hooks'
import { Badge, Button, Err, usd } from './ui'

const TONE = (p: number) => (p >= 70 ? 'red' : p >= 50 ? 'amber' : 'slate')

/** Prioritized to-dos. `limit` shows the top N with a link to the full list; `showHidden` adds snoozed and done items. */
export default function ActionFeed({ limit, showHidden = false }: { limit?: number; showHidden?: boolean }) {
  const feed = useAsync(() => api.actions(showHidden), [showHidden])
  if (feed.error) return <Err error={feed.error} />
  if (!feed.data) return null
  const all = feed.data.items
  const items = limit ? all.filter((i) => i.status === 'open').slice(0, limit) : all
  const act = async (fn: Promise<unknown>) => {
    await fn
    feed.reload()
  }
  if (items.length === 0) return <p className="text-sm text-slate-400">Nothing needs your attention right now.</p>
  return (
    <div>
      <ul className="divide-y divide-slate-800">
        {items.map((i) => (
          <Row key={i.key} item={i} act={act} />
        ))}
      </ul>
      {limit && (
        <Link to="/actions" className="mt-3 inline-flex items-center gap-1 text-sm text-emerald-400">
          See all actions{feed.data.hidden ? ` (${feed.data.hidden} snoozed or done)` : ''} <ArrowRight size={14} aria-hidden />
        </Link>
      )}
    </div>
  )
}

function Row({ item: i, act }: { item: ActionItem; act: (p: Promise<unknown>) => Promise<void> }) {
  const open = i.status === 'open'
  return (
    <li className="flex flex-wrap items-start gap-3 py-3">
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <Link to={i.where} className="font-medium hover:underline">
            {i.title}
          </Link>
          <Badge tone={TONE(i.priority)}>Priority {Math.round(i.priority)}</Badge>
          {!open && <Badge>{i.status === 'done' ? 'Done' : `Snoozed until ${i.snooze_until}`}</Badge>}
        </div>
        <p className="mt-1 text-sm text-slate-400">
          {i.detail}
          {i.dollars ? ` Worth about ${usd(i.dollars)}.` : ''}
        </p>
      </div>
      <div className="flex gap-2">
        {open ? (
          <>
            <Button variant="ghost" aria-label={`Snooze 1 wk: ${i.title}`} onClick={() => act(api.actionSnooze(i.key, 7))}>
              Snooze 1 wk
            </Button>
            <Button aria-label={`Done: ${i.title}`} onClick={() => act(api.actionDone(i.key))}>
              Done
            </Button>
          </>
        ) : (
          <Button variant="ghost" aria-label={`Reopen: ${i.title}`} onClick={() => act(api.actionReopen(i.key))}>
            Reopen
          </Button>
        )}
      </div>
    </li>
  )
}
