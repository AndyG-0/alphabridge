import { Eye, EyeOff, FlaskConical, FolderUp, Home, MessageCircle, Moon, Settings as Cog, Sun, Sunset, type LucideIcon } from 'lucide-react'
import { useEffect, useState, type ReactElement } from 'react'
import { Navigate, NavLink, Route, Routes } from 'react-router-dom'
import { api, setToken } from './api/client'
import { Button, Input } from './components/ui'
import { useAsync } from './hooks'
import { t, type MessageKey } from './i18n'
import { usePrivacy } from './lib/privacy'
import { useTheme } from './lib/theme'
import Actions from './pages/Actions'
import Chat from './pages/Chat'
import Dashboard from './pages/Dashboard'
import Onboarding from './pages/Onboarding'
import PortfolioDropzone from './pages/PortfolioDropzone'
import ResearchLab from './pages/ResearchLab'
import RetirementPlan from './pages/RetirementPlan'
import Settings from './pages/Settings'

const TABS: { path: string; label: MessageKey; icon: LucideIcon; el: ReactElement }[] = [
  { path: '/', label: 'nav.command', icon: Home, el: <DashboardGate /> },
  { path: '/plan', label: 'nav.plan', icon: Sunset, el: <RetirementPlan /> },
  { path: '/portfolio', label: 'nav.portfolio', icon: FolderUp, el: <PortfolioDropzone /> },
  { path: '/research', label: 'nav.analyst', icon: FlaskConical, el: <ResearchLab /> },
  { path: '/chat', label: 'nav.chat', icon: MessageCircle, el: <Chat /> },
  { path: '/settings', label: 'nav.settings', icon: Cog, el: <Settings /> },
]

/** Brand-new installs (no data, setup not dismissed) land on the wizard instead of an empty dashboard. */
function DashboardGate() {
  const ob = useAsync(api.onboarding)
  if (ob.data?.first_run && ob.data.show) return <Navigate to="/onboarding" replace />
  return <Dashboard />
}

function Login({ onDone }: { onDone: () => void }) {
  const [token, setTok] = useState('')
  return (
    <div className="mx-auto mt-24 max-w-sm space-y-3 p-4">
      <h1 className="text-xl font-semibold">{t('app.name')}</h1>
      <Input label={t('login.token')} type="password" value={token} onChange={(e) => setTok(e.target.value)} />
      <Button
        onClick={() => {
          setToken(token)
          onDone()
        }}
      >
        {t('login.unlock')}
      </Button>
    </div>
  )
}

export default function App() {
  const [theme, toggleTheme] = useTheme()
  const [hidden, togglePrivacy] = usePrivacy()
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
        <div className="hidden px-3 py-4 text-lg font-semibold text-emerald-400 md:block">{t('app.name')}</div>
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
            {t(label)}
          </NavLink>
        ))}
        <button
          type="button"
          onClick={togglePrivacy}
          aria-pressed={hidden}
          aria-label={hidden ? t('privacy.show') : t('privacy.hide')}
          className="flex min-h-11 min-w-11 flex-none flex-col items-center justify-center gap-1 px-3 py-2 text-xs text-slate-400 hover:text-slate-200 md:mt-auto md:flex-row md:justify-start md:gap-3 md:rounded-xl md:text-sm"
        >
          {hidden ? <EyeOff size={20} /> : <Eye size={20} />}
          <span className="hidden md:inline">{hidden ? t('privacy.show') : t('privacy.hide')}</span>
        </button>
        <button
          type="button"
          onClick={toggleTheme}
          aria-label={theme === 'light' ? t('theme.toDark') : t('theme.toLight')}
          className="flex min-h-11 min-w-11 flex-none flex-col items-center justify-center gap-1 px-3 py-2 text-xs text-slate-400 hover:text-slate-200 md:flex-row md:justify-start md:gap-3 md:rounded-xl md:text-sm"
        >
          {theme === 'light' ? <Moon size={20} /> : <Sun size={20} />}
          <span className="hidden md:inline">{theme === 'light' ? t('theme.dark') : t('theme.light')}</span>
        </button>
      </nav>
      <main className="mx-auto w-full max-w-6xl flex-1 p-4 pb-24 md:pb-6" key={`${epoch}-${hidden ? 1 : 0}`}>
        <Routes>
          {TABS.map(({ path, el }) => (
            <Route key={path} path={path === '/chat' ? '/chat/:sessionId?' : path} element={el} />
          ))}
          <Route path="/actions" element={<Actions />} />
          <Route path="/onboarding" element={<Onboarding />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </div>
  )
}
