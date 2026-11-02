import { Check, MessageSquarePlus, Pencil, Send, Trash2, X } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { api, type ChatMsg } from '../api/client'
import { Markdown } from '../components/Markdown'
import { Button, Card, Err, Input } from '../components/ui'
import { useAsync } from '../hooks'

const SUGGESTIONS = [
  'Am I on track to retire at my target age?',
  'Should I move cash out of savings right now?',
  'What is my biggest risk or concentration?',
  'What data is missing for an accurate plan?',
  'What if I retire two years earlier or save $1,000 more a month?',
]

export default function Chat() {
  const { sessionId } = useParams()
  const navigate = useNavigate()
  const id = sessionId ? Number(sessionId) : null
  const sessions = useAsync(api.chatSessions)
  const [msgs, setMsgs] = useState<ChatMsg[]>([])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<unknown>(null)
  const [editing, setEditing] = useState<number | null>(null)
  const [draft, setDraft] = useState('')
  const [scenario, setScenario] = useState('')
  const [memory, setMemory] = useState('')
  const [saved, setSaved] = useState(false)
  const loaded = useRef<number | null>(null) // the session whose messages are in state; avoids reloading one we just created
  const end = useRef<HTMLDivElement>(null)
  useEffect(() => {
    end.current?.scrollIntoView({ behavior: 'smooth' })
  }, [msgs, busy])

  useEffect(() => {
    if (id === loaded.current) return
    loaded.current = id
    setErr(null)
    setSaved(false)
    if (id === null) {
      setMsgs([])
      setScenario('')
      setMemory('')
      return
    }
    api
      .chatSession(id)
      .then((s) => {
        setMsgs(s.messages)
        setScenario(s.scenario ?? '')
        setMemory(s.memory ?? '')
      })
      .catch((e) => {
        setErr(e)
        setMsgs([])
      })
  }, [id])

  const send = async (text: string) => {
    const content = text.trim()
    if (!content || busy) return
    setInput('')
    setErr(null)
    setBusy(true)
    setMsgs((m) => [...m, { id: -Date.now(), role: 'user', content, tools: [] }])
    try {
      let sid = id
      if (sid === null) {
        sid = (await api.createChatSession()).id
        loaded.current = sid
        navigate(`/chat/${sid}`, { replace: true })
      }
      const r = await api.sendChat(sid, content)
      setMsgs((m) => [...m.filter((x) => x.id > 0), r.user, r.assistant])
      sessions.reload()
    } catch (e) {
      setErr(e)
      setMsgs((m) => m.filter((x) => x.id > 0))
      sessions.reload()
    } finally {
      setBusy(false)
    }
  }

  const rename = async (sid: number) => {
    const title = draft.trim()
    setEditing(null)
    if (!title) return
    try {
      await api.renameChatSession(sid, title)
      sessions.reload()
    } catch (e) {
      setErr(e)
    }
  }

  const saveNotes = async () => {
    if (id === null) return
    try {
      await api.updateChatSession(id, { scenario, memory })
      setSaved(true)
      setErr(null)
    } catch (e) {
      setErr(e)
    }
  }

  const remove = async (sid: number) => {
    try {
      await api.deleteChatSession(sid)
      sessions.reload()
      if (sid === id) navigate('/chat')
    } catch (e) {
      setErr(e)
    }
  }

  return (
    <div className="grid gap-4 md:grid-cols-[16rem_1fr]">
      <Card title="Conversations" className="md:max-h-[75vh] md:overflow-y-auto">
        <button
          onClick={() => navigate('/chat')}
          className="mb-2 flex w-full items-center gap-2 rounded-xl border border-slate-700 px-3 py-2 text-sm hover:border-emerald-500"
        >
          <MessageSquarePlus size={16} /> New chat
        </button>
        <ul className="max-h-40 space-y-1 overflow-y-auto md:max-h-none">
          {(sessions.data ?? []).map((s) => (
            <li key={s.id} className={`group flex items-center gap-1 rounded-lg px-2 py-1 text-sm ${s.id === id ? 'bg-slate-800' : 'hover:bg-slate-800/60'}`}>
              {editing === s.id ? (
                <>
                  <input
                    aria-label="Conversation title"
                    value={draft}
                    onChange={(e) => setDraft(e.target.value)}
                    onKeyDown={(e) => e.key === 'Enter' && rename(s.id)}
                    className="min-w-0 flex-1 rounded border border-slate-700 bg-slate-950 px-1 text-sm"
                  />
                  <button aria-label="Save title" onClick={() => rename(s.id)}>
                    <Check size={14} />
                  </button>
                  <button aria-label="Cancel rename" onClick={() => setEditing(null)}>
                    <X size={14} />
                  </button>
                </>
              ) : (
                <>
                  <button className="min-w-0 flex-1 truncate text-left" onClick={() => navigate(`/chat/${s.id}`)} title={s.title}>
                    {s.title}
                  </button>
                  <button
                    aria-label={`Rename ${s.title}`}
                    className="text-slate-500 hover:text-slate-200"
                    onClick={() => {
                      setEditing(s.id)
                      setDraft(s.title)
                    }}
                  >
                    <Pencil size={14} />
                  </button>
                  <button aria-label={`Delete ${s.title}`} className="text-slate-500 hover:text-red-400" onClick={() => remove(s.id)}>
                    <Trash2 size={14} />
                  </button>
                </>
              )}
            </li>
          ))}
          {sessions.data?.length === 0 && <li className="px-2 text-xs text-slate-500">No saved conversations yet.</li>}
        </ul>
      </Card>
      <Card title="Ask the AI">
        <p className="mb-3 text-xs text-slate-400">
          The assistant calls read-only tools over your profile, accounts, plan, pensions, debts, early-access rules, health-care rules, market data and
          research. Data it reads is sent to your configured LLM provider with each question. Conversations are saved here so you can resume them.
        </p>
        {id !== null && (
          <details className="mb-3 rounded-xl border border-slate-800 px-3 py-2 text-sm" open={Boolean(scenario || memory)}>
            <summary className="cursor-pointer text-slate-300">Scenario and notes for this chat</summary>
            <div className="mt-2 space-y-2">
              <Input
                label="Scenario name"
                value={scenario}
                maxLength={80}
                onChange={(e) => {
                  setScenario(e.target.value)
                  setSaved(false)
                }}
              />
              <label className="block text-xs text-slate-400">
                Notes the assistant should remember in this chat
                <textarea
                  value={memory}
                  maxLength={4000}
                  rows={3}
                  onChange={(e) => {
                    setMemory(e.target.value)
                    setSaved(false)
                  }}
                  className="mt-1 block w-full rounded-xl border border-slate-700 bg-slate-950 px-3 py-2 text-sm"
                />
              </label>
              <div className="flex items-center gap-3">
                <Button type="button" variant="ghost" onClick={saveNotes}>
                  Save notes
                </Button>
                {saved && <span className="text-xs text-emerald-400">Saved</span>}
              </div>
            </div>
          </details>
        )}
        <div className="max-h-[55vh] min-h-48 space-y-3 overflow-y-auto">
          {msgs.length === 0 && (
            <div className="flex flex-wrap gap-2">
              {SUGGESTIONS.map((s) => (
                <button
                  key={s}
                  onClick={() => send(s)}
                  className="rounded-full border border-slate-700 px-3 py-1 text-left text-xs text-slate-300 hover:border-emerald-500"
                >
                  {s}
                </button>
              ))}
            </div>
          )}
          {msgs.map((m) => (
            <div
              key={m.id}
              className={
                m.role === 'user'
                  ? 'ml-8 whitespace-pre-wrap rounded-2xl bg-emerald-900/40 px-3 py-2 text-sm'
                  : 'mr-8 min-w-0 rounded-2xl bg-slate-900 px-3 py-2 text-sm'
              }
            >
              {m.role === 'user' ? m.content : <Markdown>{m.content}</Markdown>}
              {m.tools.length > 0 && <div className="mt-1 text-[11px] text-slate-500">Checked: {m.tools.join(', ')}</div>}
              {m.footer && <div className="mt-1 text-[11px] text-slate-500">{m.footer}</div>}
            </div>
          ))}
          {busy && <div className="mr-8 rounded-2xl bg-slate-900 px-3 py-2 text-sm text-slate-400">Thinking…</div>}
          <div ref={end} />
        </div>
        <Err error={err} />
        <form
          className="mt-3 flex gap-2"
          onSubmit={(e) => {
            e.preventDefault()
            send(input)
          }}
        >
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Ask about your plan…"
            className="min-w-0 flex-1 rounded-xl border border-slate-700 bg-slate-950 px-3 py-2 text-sm"
          />
          <Button type="submit" aria-label="Send message" disabled={busy || !input.trim()}>
            <Send size={16} />
          </Button>
        </form>
      </Card>
    </div>
  )
}
