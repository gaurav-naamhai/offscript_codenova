import { useState } from 'react'
import { loadRecords, newId, writeRecords } from './reviewStore'
import type { ReviewRecord } from './reviewStore'
import type { Draft } from './NewReview'
import ReviewLibrary from './ReviewLibrary'
import ServerDemo from './ServerDemo'
import BrandKnowledge from './BrandKnowledge'
import Insights from './Insights'
import { readGuidanceDocuments } from './knowledgeData'
import './App.css'
import NewReview from './NewReview'

type Page = 'dashboard' | 'review' | 'library' | 'knowledge' | 'insights'
type IconName = 'home' | 'plus' | 'layers' | 'book' | 'chart' | 'settings' | 'chevron' | 'arrow' | 'search' | 'bell' | 'alert' | 'check' | 'image' | 'file' | 'mail' | 'text' | 'user'
const paths: Record<IconName, React.ReactNode> = {
  user: <><circle cx="12" cy="8" r="4"/><path d="M4 21c0-4 3-7 8-7s8 3 8 7"/></>,
  home: <><path d="m3 10 9-7 9 7v10h-6v-6H9v6H3z" /></>,
  plus: <path d="M12 3v18M3 12h18" />,
  layers: <><path d="m12 3 9 5-9 5-9-5 9-5ZM3 12l9 5 9-5M3 16l9 5 9-5" /></>,
  book: <path d="M12 6c-3-3-6-3-9-2v14c3-1 6-1 9 2m0-14c3-3 6-3 9-2v14c-3-1-6-1-9 2m0-14v14" />,
  chart: <path d="M4 20v-6m7 6V9m7 11V4" />,
  settings: <><circle cx="12" cy="12" r="3"/><path d="m19 13 2-1-1-3-2 .1-1.4-1.4.1-2-3-1-1 2h-2l-1-2-3 1 .1 2L5.4 9 3.4 9l-1 3 2 1v2l-1 1.7 2.2 2.2 1.8-1 1.8.7.8 2h3l.8-2 1.8-.7 1.8 1 2.2-2.2-1-1.7z"/></>,
  chevron: <path d="m5 9 7 7 7-7" />,
  arrow: <path d="M3 12h17m-7-7 7 7-7 7" />,
  search: <><circle cx="10.5" cy="10.5" r="7"/><path d="m16 16 5 5"/></>,
  bell: <path d="M18 8a6 6 0 0 0-12 0c0 7-2 7-2 9h16c0-2-2-2-2-9ZM10 20h4" />,
  alert: <><circle cx="12" cy="12" r="9"/><path d="M12 7v6m0 4h.01"/></>,
  check: <><circle cx="12" cy="12" r="9"/><path d="m8 12 3 3 5-6"/></>,
  image: <><rect x="3" y="3" width="18" height="18" rx="1"/><circle cx="9" cy="9" r="1.3"/><path d="m4 18 5-5 3 3 3-4 5 6"/></>,
  file: <><path d="M5 2h9l5 5v15H5zM14 2v5h5M8 12h8M8 16h8"/></>,
  mail: <><rect x="3" y="5" width="18" height="14" rx="1"/><path d="m4 6 8 6 8-6"/></>,
  text: <path d="M3 6h18M3 12h18M3 18h11" />,
}
function Icon({ name, className = '' }: { name: IconName; className?: string }) { return <svg className={`icon ${className}`} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name]}</svg> }

function Sidebar({ page, onNavigate }: { page: Page; onNavigate: (page: Page) => void }) {
  const nav: { label: string; icon: IconName }[] = [{ label: 'Dashboard', icon: 'home' }, { label: 'New review', icon: 'plus' }, { label: 'Review library', icon: 'layers' }, { label: 'Brand knowledge', icon: 'book' }, { label: 'Insights', icon: 'chart' }]
  return <aside className="sidebar"><div className="brand"><span className="brand-mark" aria-hidden="true">∞</span><span>Inkloom AI</span></div><div className="workspace"><span className="eyebrow">WORKSPACE</span><div>Your workspace <Icon name="chevron" /></div></div><nav aria-label="Main navigation">{nav.map(item => <button type="button" className={`nav-item nav-button ${page === (item.label === 'Dashboard' ? 'dashboard' : item.label === 'New review' ? 'review' : item.label === 'Review library' ? 'library' : item.label === 'Brand knowledge' ? 'knowledge' : 'insights') ? 'active' : ''}`} aria-current={page === (item.label === 'Dashboard' ? 'dashboard' : item.label === 'New review' ? 'review' : item.label === 'Review library' ? 'library' : item.label === 'Brand knowledge' ? 'knowledge' : 'insights') ? 'page' : undefined} onClick={() => onNavigate(item.label === 'Dashboard' ? 'dashboard' : item.label === 'New review' ? 'review' : item.label === 'Review library' ? 'library' : item.label === 'Brand knowledge' ? 'knowledge' : 'insights')} key={item.label}><Icon name={item.icon}/>{item.label}</button>)}</nav><div className="sidebar-bottom"><span className="nav-item unavailable"><Icon name="settings"/>Settings <span className="sr-only">(coming soon)</span></span><div className="profile"><span className="avatar"><Icon name="user"/></span><span>Guest</span><Icon name="chevron"/></div></div></aside>
}
function Header({ page }: { page: Page }) { return <header className="topbar"><div className="eyebrow">WORKSPACE <span>/</span> {page === 'dashboard' ? 'OVERVIEW' : page === 'library' ? 'REVIEW LIBRARY' : page === 'knowledge' ? 'BRAND KNOWLEDGE' : page === 'insights' ? 'INSIGHTS' : 'NEW REVIEW'}</div><div className="top-actions"><span className="demo-badge">DEMO DATA</span><span className="top-divider"/><span className="header-icon" title="Search coming soon"><Icon name="search"/><span className="sr-only">Search coming soon</span></span><span className="header-icon notification" title="Notifications coming soon"><Icon name="bell"/><span className="sr-only">Notifications coming soon</span></span></div></header> }
function Hero({ onStart, onLibrary }: { onStart: () => void; onLibrary: () => void }) { return <section className="hero"><div className="hero-copy"><h1>Clarity before<br/>the spotlight.</h1><p>Review your content. See the evidence. Keep the final say.</p><div className="hero-actions"><button className="primary-button" onClick={onStart}>Start a review <Icon name="arrow"/></button><button className="hero-library-link" onClick={onLibrary}>Open review library</button></div><div className="eyebrow formats">TEXT · IMAGES · PDF</div></div><img className="hero-art" src={`${import.meta.env.BASE_URL}assets/hero-ribbon-document-wide.png`} alt="Silver ribbon surrounding a document with a highlighted passage" /></section> }
function StatusSummary({ records }: { records: ReviewRecord[] }) { const items: { count: number; label: string; icon: IconName; tone: string }[] = [{ count: records.length, label: 'Saved reviews', icon: 'layers', tone: 'purple' }, { count: records.filter(r => r.status === 'Draft').length, label: 'Drafts', icon: 'file', tone: 'orange' }, { count: records.filter(r => r.status === 'Unreviewed').length, label: 'Unreviewed', icon: 'alert', tone: 'green' }]; return <section className="summary" aria-label="Local review summary">{items.map(item => <div className="summary-item" key={item.label}><Icon name={item.icon} className={item.tone}/><strong>{String(item.count).padStart(2, '0')}</strong><span>{item.label}</span></div>)}</section> }
function RecentReviews({ records, onLibrary, onOpen }: { records: ReviewRecord[]; onLibrary: () => void; onOpen: (id: string) => void }) { return <section className="panel desk"><div className="desk-heading"><h2>On your desk</h2><button className="reviews-link" onClick={onLibrary}>View all reviews <Icon name="arrow"/></button></div>{records.length ? <div className="table-scroll"><table><thead><tr><th>Draft</th><th>Format</th><th>Status</th></tr></thead><tbody>{records.slice(0, 2).map(record => <tr key={record.id}><td><button className="record-open" onClick={() => onOpen(record.id)}>{record.draft.title || 'Untitled draft'}</button></td><td>{record.draft.format}</td><td><span className="status lavender">{record.status}</span></td></tr>)}</tbody></table></div> : <p>No saved reviews yet. Start a review to add one.</p>}</section> }
function InfoCards({ onKnowledge }: { onKnowledge: () => void }) { const { docs, error } = readGuidanceDocuments(); const latest = docs[0]; return <div className="info-cards"><section className="panel attention"><h2>Needs your attention</h2><div className="info-content"><Icon name="alert"/><div><p>Demo guidance only</p><span className="card-link">Review findings <Icon name="arrow"/><small>Coming soon</small></span></div></div></section><section className="panel knowledge"><h2>Brand knowledge</h2><div className="info-content"><Icon name="book"/><div><p>{error ? 'Guidance metadata unavailable' : latest ? latest.title : 'No brand guidance added'}</p>{latest && <small>{latest.category} · Not processed</small>}<button className="card-link knowledge-link" onClick={onKnowledge}>Open Brand Knowledge <Icon name="arrow"/></button></div></div></section></div> }
function App() {
  const [mode, setMode] = useState<'local' | 'server'>('local')
  const [loaded] = useState(loadRecords)
  const [records, setRecords] = useState<ReviewRecord[]>(loaded.records)
  const [error, setError] = useState(loaded.error)
  const [files, setFiles] = useState<Record<string, File | null>>({})
  const [page, setPage] = useState<Page>('dashboard')
  const [activeId, setActiveId] = useState<string | null>(null)
  const [formKey, setFormKey] = useState(0)
  const sorted = [...records].sort((a, b) => b.updatedAt.localeCompare(a.updatedAt))
  function navigate(next: Page) { if (next === 'review') { setActiveId(null); setFormKey(value => value + 1) } setPage(next) }
  function open(id: string) { setActiveId(id); setFormKey(value => value + 1); setPage('review') }
  function persist(next: ReviewRecord[]) { setRecords(next); if (!loaded.error) setError(writeRecords(next)); }
  function save(draft: Draft, status: ReviewRecord['status'], file: File | null, review?: ReviewRecord['review']): { id: string; error: string } {
    const id = activeId || newId(); const previous = records.find(r => r.id === id)
    const next: ReviewRecord = { id, draft, status, updatedAt: new Date().toISOString(), review: review !== undefined ? review : previous && (previous.draft.text !== draft.text || previous.draft.format !== draft.format) ? undefined : previous?.review, fileName: file?.name ?? previous?.fileName }
    const updated = [next, ...records.filter(r => r.id !== id)]
    setRecords(updated); setActiveId(id); if (draft.format !== 'Text') setFiles(current => ({ ...current, [id]: file }))
    const message = loaded.error || writeRecords(updated); setError(message); return { id, error: message }
  }
  function remove(id: string) { persist(records.filter(record => record.id !== id)); setFiles(current => { const next = { ...current }; delete next[id]; return next }) }
  const active = records.find(record => record.id === activeId)
  return <div className="app" id="dashboard"><Sidebar page={page} onNavigate={navigate}/><main className="main"><Header page={page}/><div className="mode-switch" role="group" aria-label="Data mode"><button type="button" aria-pressed={mode === 'local'} onClick={() => { setMode('local'); setPage('dashboard') }}>Local demo</button><button type="button" aria-pressed={mode === 'server'} onClick={() => { setMode('server'); setPage('dashboard') }}>Server demo</button></div>{page === 'knowledge' ? <BrandKnowledge/> : page === 'insights' ? <Insights mode={mode}/> : mode === 'server' ? <ServerDemo page={page} navigate={setPage}/> : <>{error && <div className="storage-error" role="alert">{error}</div>}{page === 'review' ? <NewReview key={formKey} record={active} sessionFile={activeId ? files[activeId] ?? null : null} onSave={save}/> : page === 'library' ? <ReviewLibrary records={sorted} onOpen={open} onDelete={remove} onNew={() => navigate('review')}/> : <><Hero onStart={() => navigate('review')} onLibrary={() => navigate('library')}/><StatusSummary records={sorted}/><div className="dashboard-grid"><RecentReviews records={sorted} onLibrary={() => navigate('library')} onOpen={open}/><InfoCards onKnowledge={() => navigate('knowledge')}/></div></>}</>}</main></div>
}
export default App
