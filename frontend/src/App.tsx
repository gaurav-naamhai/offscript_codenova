import { useState, useEffect, useCallback } from 'react'
import type { ReactNode } from 'react'
import ReviewLibrary from './ReviewLibrary'
import BrandKnowledge from './BrandKnowledge'
import Insights from './Insights'
import NewReview from './NewReview'
import ReviewWorkspace from './ReviewWorkspace'
import { serverApi } from './serverApi'
import type { SubmissionSummary } from './serverApi'
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

function Sidebar({ page, onNavigate }: { page: Page; onNavigate: (page: Page) => void }) {
  const nav: { label: string; icon: IconName; target: Page }[] = [
    { label: 'Dashboard', icon: 'home', target: 'dashboard' },
    { label: 'New review', icon: 'plus', target: 'review' },
    { label: 'Review library', icon: 'layers', target: 'library' },
    { label: 'Brand knowledge', icon: 'book', target: 'knowledge' },
    { label: 'Insights', icon: 'chart', target: 'insights' },
  ]
  return (
    <aside className="sidebar">
      <div className="brand">
        <img className="brand-mark" src={`${import.meta.env.BASE_URL}assets/inkloom-mark-silver.png`} alt="" />
        <span>Inkloom AI</span>
      </div>
      <div className="workspace">
        <span className="eyebrow">WORKSPACE</span>
        <div>
          Your workspace <Icon name="chevron" />
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
        <span className="nav-item unavailable">
          <Icon name="settings" />
          Settings <span className="sr-only">(coming soon)</span>
        </span>
        <div className="profile">
          <span className="avatar">
            <Icon name="user" />
          </span>
          <span>Guest</span>
          <Icon name="chevron" />
        </div>
      </div>
    </aside>
  )
}

function Header({ page, hasActiveReview }: { page: Page; hasActiveReview: boolean }) {
  return (
    <header className="topbar">
      <div className="eyebrow">
        WORKSPACE <span>/</span>{' '}
        {page === 'dashboard'
          ? 'OVERVIEW'
          : page === 'library'
          ? 'REVIEW LIBRARY'
          : page === 'knowledge'
          ? 'BRAND KNOWLEDGE'
          : page === 'insights'
          ? 'INSIGHTS'
          : hasActiveReview
          ? 'REVIEW WORKSPACE'
          : 'NEW REVIEW'}
      </div>
      <div className="top-actions">
        <span className="demo-badge">DEMO DATA</span>
        <span className="top-divider" />
        <span className="header-icon" title="Search coming soon">
          <Icon name="search" />
          <span className="sr-only">Search coming soon</span>
        </span>
        <span className="header-icon notification" title="Notifications coming soon">
          <Icon name="bell" />
          <span className="sr-only">Notifications coming soon</span>
        </span>
      </div>
    </header>
  )
}

function Hero({ onStart, onLibrary }: { onStart: () => void; onLibrary: () => void }) {
  return (
    <section className="hero">
      <div className="hero-copy">
        <h1>
          Clarity before
          <br />
          the spotlight.
        </h1>
        <p>Review your content. See the evidence. Keep the final say.</p>
        <div className="hero-actions">
          <button className="primary-button" onClick={onStart}>
            Start a review <Icon name="arrow" />
          </button>
          <button className="hero-library-link" onClick={onLibrary}>
            Open review library
          </button>
        </div>
        <div className="eyebrow formats">TEXT · IMAGES · PDF</div>
      </div>
      <img
        className="hero-art"
        src={`${import.meta.env.BASE_URL}assets/hero-ribbon-document-wide.png`}
        alt="Silver ribbon surrounding a document with a highlighted passage"
      />
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
        <div className="summary-item" key={item.label}>
          <Icon name={item.icon} className={item.tone} />
          <strong>{String(item.count).padStart(2, '0')}</strong>
          <span>{item.label}</span>
        </div>
      ))}
    </section>
  )
}

function RecentReviews({
  submissions,
  loading,
  onLibrary,
  onOpen,
}: {
  submissions: SubmissionSummary[]
  loading?: boolean
  onLibrary: () => void
  onOpen: (id: string) => void
}) {
  return (
    <section className="panel desk">
      <div className="desk-heading">
        <h2>On your desk</h2>
        <button className="reviews-link" onClick={onLibrary}>
          View all reviews <Icon name="arrow" />
        </button>
      </div>
      {loading ? (
        <p>Loading submissions...</p>
      ) : submissions.length ? (
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Draft</th>
                <th>Format</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {submissions.slice(0, 3).map(sub => (
                <tr key={sub.id}>
                  <td>
                    <button className="record-open" onClick={() => onOpen(sub.id)}>
                      {sub.title || `Review #${sub.id.slice(0, 8)}`}
                    </button>
                  </td>
                  <td>{sub.content_type.toUpperCase()}</td>
                  <td>
                    <span
                      className={`status ${
                        sub.status === 'approved'
                          ? 'sage'
                          : sub.status === 'draft'
                          ? 'amber'
                          : 'lavender'
                      }`}
                    >
                      {sub.status.replace('_', ' ')}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p>No saved reviews yet. Start a review to add one.</p>
      )}
    </section>
  )
}

function App() {
  const [submissions, setSubmissions] = useState<SubmissionSummary[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [page, setPage] = useState<Page>('dashboard')
  const [activeId, setActiveId] = useState<string | null>(null)

  const fetchSubmissions = useCallback(async () => {
    setLoading(true)
    try {
      const list = await serverApi.list()
      setSubmissions(list)
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to connect to backend server')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void fetchSubmissions()
  }, [fetchSubmissions])

  function navigate(next: Page) {
    if (next === 'review') {
      setActiveId(null)
    }
    if (next === 'dashboard' || next === 'library') {
      void fetchSubmissions()
    }
    setPage(next)
  }

  function open(id: string) {
    setActiveId(id)
    setPage('review')
  }

  return (
    <div className="app" id="dashboard">
      <Sidebar page={page} onNavigate={navigate} />
      <main className="main">
        <Header page={page} hasActiveReview={Boolean(activeId)} />
        {error && (
          <div className="storage-error" role="alert" style={{ margin: '16px 25px 0' }}>
            {error}
          </div>
        )}
        {page === 'knowledge' ? (
          <BrandKnowledge />
        ) : page === 'insights' ? (
          <Insights />
        ) : page === 'library' ? (
          <ReviewLibrary
            onOpen={open}
            onNew={() => {
              setActiveId(null)
              setPage('review')
            }}
          />
        ) : page === 'review' ? (
          activeId ? (
            <ReviewWorkspace
              submissionId={activeId}
              onReturn={() => {
                setActiveId(null)
                setPage('library')
                void fetchSubmissions()
              }}
              onNewReview={() => {
                setActiveId(null)
                setPage('review')
              }}
              onRefreshList={fetchSubmissions}
            />
          ) : (
            <NewReview
              onCreated={id => {
                setActiveId(id)
                setPage('review')
                void fetchSubmissions()
              }}
            />
          )
        ) : (
          <>
            <Hero onStart={() => navigate('review')} onLibrary={() => navigate('library')} />
            <StatusSummary submissions={submissions} />
            <div className="dashboard-grid">
              <RecentReviews
                submissions={submissions}
                loading={loading}
                onLibrary={() => navigate('library')}
                onOpen={open}
              />
            </div>
          </>
        )}
      </main>
    </div>
  )
}

export default App
