import { useEffect, useState } from 'react'
import { HashRouter, NavLink, Route, Routes, useLocation, useNavigate } from 'react-router-dom'
import { api, CATEGORY_LABELS, type Health, type Stats } from './api'
import { DriveBanner } from './components/DriveBanner'
import { Icon } from './components/Icon'
import { JobPill } from './components/JobPill'
import { AppProvider } from './hooks/app'
import { JobProvider, useJob } from './hooks/job'
import { Dashboard } from './pages/Dashboard'
import { Library } from './pages/Library'
import { People } from './pages/People'
import { Person } from './pages/Person'
import { Sources } from './pages/Sources'

export default function App() {
  const [health, setHealth] = useState<Health | null>(null)
  const [offline, setOffline] = useState<'down' | 'locked' | null>(null)

  useEffect(() => {
    api.health().then(setHealth).catch((e: Error & { status?: number }) => setOffline(e.status === 401 ? 'locked' : 'down'))
  }, [])

  if (offline) {
    return (
      <main className="offline">
        <h1>PixSift</h1>
        {offline === 'locked'
          ? <p>This page isn't signed in to PixSift. Use the link PixSift printed when it started (it ends in <code>?token=…</code>), or just open the PixSift app.</p>
          : <p>Can't reach the PixSift engine. Start it with <code>python -m pixsift</code> in <code>backend/</code>.</p>}
      </main>
    )
  }
  if (!health) return null

  return (
    <AppProvider revealLabel={health.reveal_label}>
      <JobProvider>
        <HashRouter>
          <Shell />
        </HashRouter>
      </JobProvider>
    </AppProvider>
  )
}

function Shell() {
  const { version } = useJob()
  const [stats, setStats] = useState<Stats | null>(null)
  const [cats, setCats] = useState<Record<string, number>>({})
  const [search, setSearch] = useState('')
  const navigate = useNavigate()
  const loc = useLocation()
  const category = new URLSearchParams(loc.search).get('category')
  const onLibrary = loc.pathname === '/library'

  useEffect(() => {
    api.dashboard().then((d) => {
      setStats(d.stats)
      setCats(Object.fromEntries(d.categories.map((c) => [c.key, c.count])))
    })
  }, [version])

  return (
    <div className="shell">
      <nav className="sidebar" aria-label="Main">
        <div className="brand"><img src="/favicon.svg" className="logo" alt="" />PixSift</div>
        <NavLink to="/" end><Icon name="home" /> Dashboard</NavLink>
        <NavLink to="/library" end className={() => (onLibrary && !category ? 'active' : '')}><Icon name="grid" /> Library <span className="count">{stats?.total.toLocaleString()}</span></NavLink>
        <NavLink to="/people"><Icon name="people" /> People
          {!!stats?.unnamed_groups && <span className="dot" title={`${stats.unnamed_groups} unnamed groups`} />}
        </NavLink>
        <NavLink to="/sources"><Icon name="drive" /> Sources</NavLink>
        <h4>Types</h4>
        {(['photo', 'document', 'screenshot', 'graphic'] as const).map((c) => (
          <NavLink key={c} to={`/library?category=${c}`} className={() => (onLibrary && category === c ? 'active' : '')}>
            <Icon name={({ photo: 'photo', document: 'doc', screenshot: 'screen', graphic: 'graphic' } as const)[c]} />
            {CATEGORY_LABELS[c]} <span className="count">{cats[c]?.toLocaleString() ?? ''}</span>
          </NavLink>
        ))}
      </nav>
      <div className="main">
        <header className="topbar">
          <form className="search" role="search" onSubmit={(e) => { e.preventDefault(); navigate(`/library?q=${encodeURIComponent(search)}`) }}>
            <Icon name="search" />
            <input type="search" placeholder="Search file names and tags" value={search} onChange={(e) => setSearch(e.target.value)} aria-label="Search pictures" />
          </form>
          <JobPill />
        </header>
        <DriveBanner />
        <main className="content">
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/library" element={<Library />} />
            <Route path="/people" element={<People />} />
            <Route path="/people/:id" element={<Person />} />
            <Route path="/sources" element={<Sources />} />
          </Routes>
        </main>
      </div>
    </div>
  )
}
