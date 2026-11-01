import { FlaskConical, FolderUp, Home, MessageCircle, Settings as Cog, Sunset } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Navigate, NavLink, Route, Routes } from 'react-router-dom'
import { setToken } from './api/client'
import { Button, Input } from './components/ui'
import Chat from './pages/Chat'
import Dashboard from './pages/Dashboard'
import PortfolioDropzone from './pages/PortfolioDropzone'
import ResearchLab from './pages/ResearchLab'
import RetirementPlan from './pages/RetirementPlan'
import Settings from './pages/Settings'

const TABS = [
  { path: '/', label: 'Command', icon: Home, el: <Dashboard /> },
  { path: '/plan', label: 'Plan', icon: Sunset, el: <RetirementPlan /> },
  { path: '/portfolio', label: 'Portfolio', icon: FolderUp, el: <PortfolioDropzone /> },
  { path: '/research', label: 'Analyst', icon: FlaskConical, el: <ResearchLab /> },
  { path: '/chat', label: 'Ask AI', icon: MessageCircle, el: <Chat /> },
  { path: '/settings', label: 'Settings', icon: Cog, el: <Settings /> },
]

function Login({ onDone }: { onDone: () => void }) {
  const [t, setT] = useState('')
  return (
    <div className="mx-auto mt-24 max-w-sm space-y-3 p-4">
      <h1 className="text-xl font-semibold">AlphaBridge</h1>
      <Input label="Access token" type="password" value={t} onChange={(e) => setT(e.target.value)} />
      <Button
        onClick={() => {
          setToken(t)
          onDone()
        }}
      >
        Unlock
      </Button>
    </div>
  )
}

export default function App() {
  const [locked, setLocked] = useState(false)
  const [epoch, setEpoch] = useState(0)
  useEffect(() => {
    const h = () => setLocked(true)
    window.addEventListener('ab-unauthorized', h)
    return () => {
      window.removeEventListener('ab-unauthorized', h)
    }
  }, [])
  if (locked)
    return (
      <Login
        onDone={() => {
          setLocked(false)
          setEpoch((e) => e + 1)
        }}
      />
    )
  return (
    <div className="min-h-screen md:flex">
      <nav className="fixed inset-x-0 bottom-0 z-10 flex border-t border-slate-800 bg-slate-950/95 pb-[env(safe-area-inset-bottom)] backdrop-blur md:static md:w-52 md:flex-col md:border-r md:border-t-0 md:p-3">
        <div className="hidden px-3 py-4 text-lg font-semibold text-emerald-400 md:block">AlphaBridge</div>
        {TABS.map(({ path, label, icon: Icon }) => (
          <NavLink
            key={path}
            to={path}
            end={path === '/'}
            className={({ isActive }) =>
              `flex flex-1 flex-col items-center gap-1 py-2 text-xs md:flex-none md:flex-row md:gap-3 md:rounded-xl md:px-3 md:text-sm ${isActive ? 'text-emerald-400 md:bg-slate-900' : 'text-slate-400'}`
            }
          >
            <Icon size={20} />
            {label}
          </NavLink>
        ))}
      </nav>
      <main className="mx-auto w-full max-w-6xl flex-1 p-4 pb-24 md:pb-6" key={epoch}>
        <Routes>
          {TABS.map(({ path, el }) => (
            <Route key={path} path={path === '/chat' ? '/chat/:sessionId?' : path} element={el} />
          ))}
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </div>
  )
}
