import { useState, useEffect, useCallback } from 'react'
import type { ReactNode } from 'react'
import ReviewLibrary from './ReviewLibrary'
import BrandKnowledge from './BrandKnowledge'
import Insights from './Insights'
import NewReview from './NewReview'
import ReviewWorkspace from './ReviewWorkspace'
import GlobalSearch from './GlobalSearch'
import ReviewWorkflow from './ReviewWorkflow'
import AuthModal from './AuthModal'
import {
  AUTH_SESSION_EVENT,
  isAuthStorageKey,
  clearAuthSession,
  DEFAULT_DEMO_ACCOUNT,
  getStoredToken,
  getStoredUser,
  serverApi,
} from './serverApi'
import type { AuthUser, DemoRole, SubmissionSummary } from './serverApi'
import './App.css'
import './ReviewLibrary.css'

type Page = 'dashboard' | 'review' | 'library' | 'knowledge' | 'insights'
type IconName =
  | 'home'
  | 'plus'
  | 'layers'
  | 'book'
  | 'chart'
  | 'settings'
  | 'chevron'
  | 'arrow'
  | 'search'
  | 'bell'
  | 'alert'
  | 'check'
  | 'image'
  | 'file'
  | 'mail'
  | 'text'
  | 'user'

const ROLE_LABELS: Record<DemoRole, string> = {
  creator: 'Creator',
  manager: 'Manager',
  authorised_reviewer: 'Final Reviewer',
}

function parseHashRoute(): { page: Page; activeId: string | null; knowledgeTab: 'docs' | 'rectify' } {
  const hash = (window.location.hash || '').replace(/^#\/?/, '')
  const parts = hash.split('/').filter(Boolean)
  if (parts[0] === 'review') {
    if (parts[1] && parts[1] !== 'new') {
      return { page: 'review', activeId: parts[1], knowledgeTab: 'docs' }
    }
    return { page: 'review', activeId: null, knowledgeTab: 'docs' }
  }
  if (parts[0] === 'library') return { page: 'library', activeId: null, knowledgeTab: 'docs' }
  if (parts[0] === 'knowledge') {
    return {
      page: 'knowledge',
      activeId: null,
      knowledgeTab: parts[1] === 'rectify' ? 'rectify' : 'docs',
    }
  }
  if (parts[0] === 'insights') return { page: 'insights', activeId: null, knowledgeTab: 'docs' }
  return { page: 'dashboard', activeId: null, knowledgeTab: 'docs' }
}

function writeHashRoute(page: Page, activeId: string | null, knowledgeTab: 'docs' | 'rectify' = 'docs') {
  let next = '#/dashboard'
  if (page === 'review') next = activeId ? `#/review/${activeId}` : '#/review/new'
  else if (page === 'library') next = '#/library'
  else if (page === 'knowledge') next = knowledgeTab === 'rectify' ? '#/knowledge/rectify' : '#/knowledge'
  else if (page === 'insights') next = '#/insights'
  if (window.location.hash !== next) {
    window.location.hash = next
  }
}

const paths: Record<IconName, ReactNode> = {
  user: (
    <>
      <circle cx="12" cy="8" r="4" />
      <path d="M4 21c0-4 3-7 8-7s8 3 8 7" />
    </>
  ),
  home: (
    <>
      <path d="m3 10 9-7 9 7v10h-6v-6H9v6H3z" />
    </>
  ),
  plus: <path d="M12 3v18M3 12h18" />,
  layers: (
    <>
      <path d="m12 3 9 5-9 5-9-5 9-5ZM3 12l9 5 9-5M3 16l9 5 9-5" />
    </>
  ),
  book: <path d="M12 6c-3-3-6-3-9-2v14c3-1 6-1 9 2m0-14c3-3 6-3 9-2v14c-3-1-6-1-9 2m0-14v14" />,
  chart: <path d="M4 20v-6m7 6V9m7 11V4" />,
  settings: (
    <>
      <circle cx="12" cy="12" r="3" />
      <path d="m19 13 2-1-1-3-2 .1-1.4-1.4.1-2-3-1-1 2h-2l-1-2-3 1 .1 2L5.4 9 3.4 9l-1 3 2 1v2l-1 1.7 2.2 2.2 1.8-1 1.8.7.8 2h3l.8-2 1.8-.7 1.8 1 2.2-2.2-1-1.7z" />
    </>
  ),
  chevron: <path d="m5 9 7 7 7-7" />,
  arrow: <path d="M3 12h17m-7-7 7 7-7 7" />,
  search: (
    <>
      <circle cx="10.5" cy="10.5" r="7" />
      <path d="m16 16 5 5" />
    </>
  ),
  bell: <path d="M18 8a6 6 0 0 0-12 0c0 7-2 7-2 9h16c0-2-2-2-2-9ZM10 20h4" />,
  alert: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7v6m0 4h.01" />
    </>
  ),
  check: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="m8 12 3 3 5-6" />
    </>
  ),
  image: (
    <>
      <rect x="3" y="3" width="18" height="18" rx="1" />
      <circle cx="9" cy="9" r="1.3" />
      <path d="m4 18 5-5 3 3 3-4 5 6" />
    </>
  ),
  file: (
    <>
      <path d="M5 2h9l5 5v15H5zM14 2v5h5M8 12h8M8 16h8" />
    </>
  ),
  mail: (
    <>
      <rect x="3" y="5" width="18" height="14" rx="1" />
      <path d="m4 6 8 6 8-6" />
    </>
  ),
  text: <path d="M3 6h18M3 12h18M3 18h11" />,
}

function Icon({ name, className = '' }: { name: IconName; className?: string }) {
  return (
    <svg
      className={`icon ${className}`}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {paths[name]}
    </svg>
  )
}

function Sidebar({
  page,
  user,
  onNavigate,
  onOpenAuth,
  onSignOut,
}: {
  page: Page
  user: AuthUser
  onNavigate: (page: Page) => void
  onOpenAuth: () => void
  onSignOut: () => void
}) {
  const nav: { label: string; icon: IconName; target: Page }[] = [
    { label: 'Dashboard', icon: 'home', target: 'dashboard' },
    { label: 'Brand Knowledge', icon: 'book', target: 'knowledge' },
    { label: 'New Review', icon: 'plus', target: 'review' },
    { label: 'Review Library', icon: 'layers', target: 'library' },
    { label: 'Insights', icon: 'chart', target: 'insights' },
  ]
  return (
    <aside className="sidebar">
      <div className="brand">
        <img className="brand-mark" src={`${import.meta.env.BASE_URL}assets/inkloom-mark-silver.png`} alt="" />
        <span>Inkloom AI</span>
      </div>
      <div className="workspace">
        <span className="eyebrow">Active Brand</span>
        <div>
          {user.org_name} <Icon name="chevron" />
        </div>
      </div>
      <nav aria-label="Main navigation">
        {nav.map(item => (
          <button
            type="button"
            className={`nav-item nav-button ${page === item.target ? 'active' : ''}`}
            aria-current={page === item.target ? 'page' : undefined}
            onClick={() => onNavigate(item.target)}
            key={item.label}
          >
            <Icon name={item.icon} />
            {item.label}
          </button>
        ))}
      </nav>

      <div className="sidebar-bottom">
        <div className="profile">
          <div className="avatar" aria-hidden="true">
            {user.name
              .split(' ')
              .map(n => n[0])
              .slice(0, 2)
              .join('')
              .toUpperCase()}
          </div>
          <div className="profile-meta">
            <strong>{user.name}</strong>
            <span className={`sidebar-role-pill role-${user.role}`}>{ROLE_LABELS[user.role]}</span>
          </div>
        </div>
        <div className="sidebar-auth-actions">
          <button type="button" className="sidebar-mini-btn" onClick={onOpenAuth}>
            Switch account
          </button>
          <button type="button" className="sidebar-mini-btn ghost" onClick={onSignOut}>
            Sign out
          </button>
        </div>
      </div>
    </aside>
  )
}

function Header({
  page,
  hasActiveReview,
  user,
  onSearch,
  onOpenAuth,
}: {
  page: Page
  hasActiveReview: boolean
  user: AuthUser
  onSearch: () => void
  onOpenAuth: () => void
}) {
  return (
    <header className="topbar">
      <div className="eyebrow">
        {user.brand_name} <span>/</span>{' '}
        {page === 'dashboard'
          ? 'Overview'
          : page === 'library'
          ? 'Review Library'
          : page === 'knowledge'
          ? 'Brand Knowledge'
          : page === 'insights'
          ? 'Insights'
          : hasActiveReview
          ? 'Review Workspace'
          : 'New Review'}
      </div>
      <div className="top-actions">
        <button type="button" className="header-role-pill" onClick={onOpenAuth} title="Switch organisation or role">
          <Icon name="user" />
          <span>{user.name} · {ROLE_LABELS[user.role]}</span>
        </button>
        <button
          type="button"
          className="header-icon search-trigger"
          onClick={onSearch}
          aria-label="Search workspace"
          aria-keyshortcuts="Control+K Meta+K"
        >
          <Icon name="search" />
        </button>
      </div>
    </header>
  )
}

function Hero({ onStart, onLibrary }: { onStart: () => void; onLibrary: () => void; brandName: string }) {
  return (
    <section className="hero">
      <div className="hero-copy">
        <h1>
          Clarity before
          <br />
          the spotlight.
        </h1>
        <p className="page-guidance">Start a review or return to your recent work.</p>
        <div className="hero-actions">
          <button type="button" className="primary-button" onClick={onStart}>
            Start a review <Icon name="arrow" />
          </button>
          <button type="button" className="hero-library-link" onClick={onLibrary}>
            Open review library
          </button>
        </div>
        <div className="eyebrow formats">Text · Images · PDF</div>
      </div>
      <span className="hero-art">
        <img
          className="hero-art-image"
          src={`${import.meta.env.BASE_URL}assets/hero-ribbon-document-wide.png`}
          alt="Silver ribbon surrounding a document with a highlighted passage"
        />
        <span className="hero-ribbon-glint" aria-hidden="true" />
      </span>
    </section>
  )
}

function StatusSummary({ submissions }: { submissions: SubmissionSummary[] }) {
  const drafts = submissions.filter(s => s.status === 'draft').length
  const inReview = submissions.filter(
    s => s.status === 'manager_review' || s.status === 'final_approval' || s.status === 'ai_review'
  ).length
  const approved = submissions.filter(s => s.status === 'approved').length

  const items: { count: number; label: string; icon: IconName; tone: string }[] = [
    { count: drafts, label: 'Drafts', icon: 'file', tone: 'orange' },
    { count: inReview, label: 'In Review', icon: 'alert', tone: 'purple' },
    { count: approved, label: 'Approved', icon: 'check', tone: 'green' },
  ]
  return (
    <section className="summary" aria-label="Review status summary">
      {items.map(item => (
        <div className="summary-item stagger-card" key={item.label}>
          <Icon name={item.icon} className={item.tone} />
          <strong>{String(item.count).padStart(2, '0')}</strong>
          <span>{item.label}</span>
        </div>
      ))}
    </section>
  )
}

function App() {
  const initial = parseHashRoute()
  const [user, setUser] = useState<AuthUser | null>(() => getStoredUser() || DEFAULT_DEMO_ACCOUNT.user)
  const [authModalOpen, setAuthModalOpen] = useState(false)
  const [backendPhase, setBackendPhase] = useState<'waking' | 'authenticating' | 'ready'>('waking')
  const [showWakeBanner, setShowWakeBanner] = useState(true)
  const [wakeElapsedSec, setWakeElapsedSec] = useState(0)
  const [wakePingCount, setWakePingCount] = useState(0)
  const [wakeLatencyMs, setWakeLatencyMs] = useState<number | null>(null)
  const [submissions, setSubmissions] = useState<SubmissionSummary[]>([])
  const [error, setError] = useState<string | null>(null)
  const [page, setPage] = useState<Page>(initial.page)
  const [activeId, setActiveId] = useState<string | null>(initial.activeId)
  const [knowledgeTab, setKnowledgeTab] = useState<'docs' | 'rectify'>(initial.knowledgeTab)
  const [searchOpen, setSearchOpen] = useState(false)
  const [selectedDocument, setSelectedDocument] = useState<string | null>(null)
  const [focusKnowledgeUpload, setFocusKnowledgeUpload] = useState(false)

  const fetchSubmissions = useCallback(async () => {
    if (!getStoredToken()) {
      setSubmissions([])
      return
    }
    try {
      const list = await serverApi.list()
      setSubmissions(list)
      setError(null)
    } catch (err) {
      if (backendPhase === 'ready') {
        setError(err instanceof Error ? err.message : 'Failed to connect to backend server')
      }
    }
  }, [backendPhase])

  // Dynamic Render backend wake-up monitor + automatic demo login
  useEffect(() => {
    let active = true
    const startedAt = Date.now()
    const tickTimer = window.setInterval(() => {
      if (active) {
        setWakeElapsedSec(Math.floor((Date.now() - startedAt) / 1000))
      }
    }, 1000)

    let retryTimer: number | null = null

    async function probeAndConnect() {
      if (!active) return
      setWakePingCount(c => c + 1)
      const res = await serverApi.pingHealth(5000)
      if (!active) return

      if (!res.ok) {
        retryTimer = window.setTimeout(() => void probeAndConnect(), 2500)
        return
      }

      setWakeLatencyMs(res.latencyMs)
      setBackendPhase('authenticating')

      const tok = getStoredToken()
      try {
        if (tok) {
          const verified = await serverApi.me()
          if (active) setUser(verified)
        } else {
          const loginRes = await serverApi.login(
            DEFAULT_DEMO_ACCOUNT.email,
            DEFAULT_DEMO_ACCOUNT.password
          )
          if (active) setUser(loginRes.user)
        }
      } catch {
        try {
          const fallback = await serverApi.login(
            DEFAULT_DEMO_ACCOUNT.email,
            DEFAULT_DEMO_ACCOUNT.password
          )
          if (active) setUser(fallback.user)
        } catch {
          // keep demo preview user if login fails
        }
      }

      if (!active) return
      setBackendPhase('ready')
      window.clearInterval(tickTimer)
      try {
        const list = await serverApi.list()
        if (active) {
          setSubmissions(list)
          setError(null)
        }
      } catch {
        // handled by fetchSubmissions
      }
      window.setTimeout(() => {
        if (active) setShowWakeBanner(false)
      }, 3000)
    }

    void probeAndConnect()

    return () => {
      active = false
      window.clearInterval(tickTimer)
      if (retryTimer !== null) window.clearTimeout(retryTimer)
    }
  }, [])

  // Auth changes in another tab invalidate its old role, organisation, and open record here.
  useEffect(() => {
    let timer: number | undefined
    const reconcile = () => {
      window.clearTimeout(timer)
      timer = window.setTimeout(() => {
        const token = getStoredToken()
        const next = token ? getStoredUser() : null
        if (!next) {
          setUser(null)
          setSubmissions([])
          setActiveId(null)
          setSearchOpen(false)
          setAuthModalOpen(false)
          setError(null)
          return
        }
        if (next.user_id !== user?.user_id || next.org_id !== user?.org_id || next.role !== user?.role) {
          setSubmissions([])
          setActiveId(null)
          setSelectedDocument(null)
          setSearchOpen(false)
          setError(null)
          setPage('dashboard')
          writeHashRoute('dashboard', null)
        }
        setUser(next)
        void serverApi.me().then(verified => {
          if (getStoredToken() === token) setUser(verified)
        }).catch(() => {
          if (getStoredToken() === token) clearAuthSession()
        })
      }, 0)
    }
    const onStorage = (event: StorageEvent) => { if (isAuthStorageKey(event.key)) reconcile() }
    window.addEventListener('storage', onStorage)
    window.addEventListener(AUTH_SESSION_EVENT, reconcile)
    return () => {
      window.clearTimeout(timer)
      window.removeEventListener('storage', onStorage)
      window.removeEventListener(AUTH_SESSION_EVENT, reconcile)
    }
  }, [user?.user_id, user?.org_id, user?.role])

  // Sync URL hash changes (supports browser back/forward & page refresh on saved reviews)
  useEffect(() => {
    const onHash = () => {
      const parsed = parseHashRoute()
      setPage(parsed.page)
      setActiveId(parsed.activeId)
      setKnowledgeTab(parsed.knowledgeTab)
    }
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])

  useEffect(() => {
    const shortcut = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault()
        setSearchOpen(true)
      }
    }
    window.addEventListener('keydown', shortcut)
    return () => window.removeEventListener('keydown', shortcut)
  }, [])

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void fetchSubmissions()
    }, 0)
    return () => window.clearTimeout(timer)
  }, [fetchSubmissions, user?.user_id, user?.org_id])

  function navigate(next: Page, nextKnowledgeTab: 'docs' | 'rectify' = 'docs') {
    if (next === 'knowledge') {
      setSelectedDocument(null)
      setKnowledgeTab(nextKnowledgeTab)
    }
    setFocusKnowledgeUpload(false)
    const nextActiveId = next === 'review' ? null : activeId
    if (next === 'review') {
      setActiveId(null)
    }
    if (next === 'dashboard' || next === 'library') {
      void fetchSubmissions()
    }
    setPage(next)
    writeHashRoute(next, next === 'review' ? null : nextActiveId, nextKnowledgeTab)
  }

  function open(id: string) {
    setActiveId(id)
    setPage('review')
    writeHashRoute('review', id)
  }

  function handleAuthenticated(nextUser: AuthUser) {
    const orgChanged = user && user.org_id !== nextUser.org_id
    setUser(nextUser)
    setError(null)
    if (orgChanged) {
      setActiveId(null)
      if (page === 'review') {
        setPage('library')
        writeHashRoute('library', null)
      }
    }
    void fetchSubmissions()
  }

  function handleSignOut() {
    clearAuthSession()
    setUser(null)
    setSubmissions([])
    setActiveId(null)
  }

  if (!user) {
    return (
      <div className="app auth-gate" id="dashboard">
        <AuthModal inline currentUser={null} onAuthenticated={handleAuthenticated} />
      </div>
    )
  }

  return (
    <div className="app" id="dashboard">
      <Sidebar
        page={page}
        user={user}
        onNavigate={next => navigate(next)}
        onOpenAuth={() => setAuthModalOpen(true)}
        onSignOut={handleSignOut}
      />
      <main className="main">
        <Header
          page={page}
          hasActiveReview={Boolean(activeId)}
          user={user}
          onSearch={() => setSearchOpen(true)}
          onOpenAuth={() => setAuthModalOpen(true)}
        />
        {showWakeBanner && (
          <div
            className={`backend-wakeup-banner ${backendPhase === 'ready' ? 'ready' : ''}`}
            role="status"
            aria-live="polite"
          >
            <div className="backend-wakeup-top">
              <strong>
                {backendPhase === 'ready'
                  ? `Backend connected (${wakeLatencyMs != null ? `${(wakeLatencyMs / 1000).toFixed(1)}s` : 'ready'}) — live demo session synced`
                  : backendPhase === 'authenticating'
                    ? 'Backend awake — signing into BrightLeaf demo workspace…'
                    : 'Waking up Render backend (free-tier cold start)…'}
              </strong>
              <div className="backend-wakeup-meta">
                {backendPhase === 'waking' && (
                  <>
                    <span>
                      {wakeElapsedSec < 55
                        ? `~${55 - wakeElapsedSec}s est. remaining`
                        : 'Finalizing startup…'}
                    </span>
                    <span>•</span>
                    <span>{wakeElapsedSec}s elapsed</span>
                    <span>•</span>
                    <span>Live /health ping #{wakePingCount}</span>
                  </>
                )}
                {backendPhase === 'ready' && (
                  <button
                    type="button"
                    className="sidebar-mini-btn ghost"
                    onClick={() => setShowWakeBanner(false)}
                  >
                    Dismiss
                  </button>
                )}
              </div>
            </div>
            {backendPhase !== 'ready' && (
              <div className="backend-wakeup-track" aria-hidden="true">
                <div
                  className="backend-wakeup-fill"
                  style={{
                    width:
                      backendPhase === 'authenticating'
                        ? '96%'
                        : `${Math.min(92, Math.max(6, Math.round((wakeElapsedSec / 55) * 92)))}%`,
                  }}
                />
              </div>
            )}
          </div>
        )}
        {error && (
          <div className="storage-error" role="alert" style={{ margin: '16px 25px 0' }}>
            {error}
          </div>
        )}
        <div key={`${page}-${activeId || 'new'}-${user.org_id}`} className="page-enter">
          {page === 'knowledge' ? (
            <BrandKnowledge
              key={`${user.org_id}-${selectedDocument || 'all'}-${knowledgeTab}`}
              user={user}
              initialSelectedId={selectedDocument}
              initialTab={knowledgeTab}
              focusUpload={focusKnowledgeUpload}
              onSwitchAccount={() => setAuthModalOpen(true)}
            />
          ) : page === 'insights' ? (
            <Insights
              user={user}
              onOpenRectification={() => navigate('knowledge', 'rectify')}
            />
          ) : page === 'library' ? (
            <ReviewLibrary
              onOpen={open}
              onNew={() => {
                setActiveId(null)
                setPage('review')
                writeHashRoute('review', null)
              }}
            />
          ) : page === 'review' ? (
            activeId ? (
              <ReviewWorkspace
                submissionId={activeId}
                user={user}
                onSwitchAccount={() => setAuthModalOpen(true)}
                onReturn={() => {
                  setActiveId(null)
                  setPage('library')
                  writeHashRoute('library', null)
                  void fetchSubmissions()
                }}
                onNewReview={() => {
                  setActiveId(null)
                  setPage('review')
                  writeHashRoute('review', null)
                }}
                onRefreshList={fetchSubmissions}
              />
            ) : (
              <NewReview
                user={user}
                onSwitchAccount={() => setAuthModalOpen(true)}
                onCreated={id => {
                  setActiveId(id)
                  setPage('review')
                  writeHashRoute('review', id)
                  void fetchSubmissions()
                }}
              />
            )
          ) : (
            <>
              <Hero
                brandName={user.brand_name}
                onStart={() => navigate('review')}
                onLibrary={() => navigate('library')}
              />
              <StatusSummary submissions={submissions} />
              <div className="dashboard-grid">
                <ReviewWorkflow
                  onGuidelines={() => {
                    navigate('knowledge')
                    setFocusKnowledgeUpload(true)
                  }}
                  onContent={() => navigate('review')}
                  onLibrary={() => navigate('library')}
                />
              </div>
            </>
          )}
        </div>
      </main>
      {searchOpen && (
        <GlobalSearch
          onClose={() => setSearchOpen(false)}
          onReview={id => {
            setSearchOpen(false)
            open(id)
          }}
          onDocument={id => {
            setSearchOpen(false)
            setSelectedDocument(id)
            setPage('knowledge')
            writeHashRoute('knowledge', null)
          }}
        />
      )}
      {authModalOpen && (
        <AuthModal
          currentUser={user}
          onAuthenticated={handleAuthenticated}
          onClose={() => setAuthModalOpen(false)}
        />
      )}
    </div>
  )
}

export default App
