import { useState } from 'react'
import { api } from '../api/client'
import { Button, Card, Err } from '../components/ui'

export default function DataCard() {
  const [err, setErr] = useState<unknown>(null)
  const [msg, setMsg] = useState('')
  const [link, setLink] = useState('')
  const act = async (fn: () => Promise<string | void>) => {
    setErr(null)
    setMsg('')
    try {
      setMsg((await fn()) || '')
    } catch (e) {
      setErr(e)
    }
  }
  const restore = async (f: File) => {
    if (!window.confirm('Importing replaces ALL current data with the file. Continue?')) return
    await act(async () => {
      await api.importExport(JSON.parse(await f.text()))
      return 'Imported. Reload the page.'
    })
  }
  return (
    <Card title="Your data">
      <Err error={err} />
      <div className="flex flex-wrap gap-2">
        <Button variant="ghost" onClick={() => act(() => api.download('/export/report.pdf', 'alphabridge-report.pdf'))}>
          Plan report (PDF)
        </Button>
        <Button variant="ghost" onClick={() => act(() => api.download('/export/report.csv', 'alphabridge-report.csv'))}>
          Plan report (CSV)
        </Button>
        <Button variant="ghost" onClick={() => act(() => api.download('/export/json', 'alphabridge-export.json'))}>
          Full export (JSON)
        </Button>
        <Button variant="ghost" onClick={() => act(async () => `Backup written to ${(await api.runBackup()).path}`)}>
          Back up now
        </Button>
        <Button
          variant="ghost"
          onClick={() =>
            act(async () => {
              const r = await api.createShareLink(7)
              setLink(`${window.location.origin}/api/share/${r.token}/report.pdf`)
              return `Read-only report link valid until ${r.expires.slice(0, 10)}`
            })
          }
        >
          Share report link (7 days)
        </Button>
        <label className="cursor-pointer text-sm text-slate-300 underline">
          Restore from export
          <input type="file" accept=".json" hidden onChange={(e) => e.target.files?.[0] && restore(e.target.files[0])} />
        </label>
      </div>
      {link && <p className="mt-2 break-all text-xs text-slate-400">{link}</p>}
      {msg && <p className="mt-2 text-xs text-slate-400">{msg}</p>}
      <p className="mt-2 text-xs text-slate-500">Exports never include API keys. Scheduled encrypted backups are configured with BACKUP_DEST (see README).</p>
    </Card>
  )
}
