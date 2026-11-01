import { useState } from 'react'
import { api } from '../api/client'
import { Button, Card, Err } from '../components/ui'
import { useAsync } from '../hooks'

export default function ImportHistoryCard({ version, onChanged }: { version: number; onChanged: () => void }) {
  const log = useAsync(api.importLog, [version])
  const [err, setErr] = useState<unknown>(null)
  const undo = async (id: number) => {
    setErr(null)
    try {
      await api.undoImport(id)
      log.reload()
      onChanged()
    } catch (e) {
      setErr(e)
    }
  }
  if (!log.data?.length) return null
  return (
    <Card title="Import history">
      <Err error={err ?? log.error} />
      <div className="overflow-x-auto">
        <table className="w-full text-left text-xs">
          <thead className="text-slate-400">
            <tr>
              <th className="pr-3">When</th>
              <th className="pr-3">File</th>
              <th className="pr-3">Account</th>
              <th className="pr-3">Rows</th>
              <th className="pr-3">Status</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {log.data.map((r) => (
              <tr key={r.id} className="border-t border-slate-800" title={r.message || undefined}>
                <td className="py-1 pr-3 whitespace-nowrap">{r.created_at.slice(0, 16).replace('T', ' ')}</td>
                <td className="pr-3">{r.filename}</td>
                <td className="pr-3">{r.account ?? '—'}</td>
                <td className="pr-3">{r.rows}</td>
                <td className={r.status === 'ERROR' ? 'pr-3 text-red-400' : r.status === 'UNDONE' ? 'pr-3 text-slate-500' : 'pr-3'}>{r.status}</td>
                <td className="text-right">
                  {r.can_undo && (
                    <Button variant="ghost" className="px-2 py-1 text-xs" onClick={() => undo(r.id)}>
                      Undo
                    </Button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  )
}
