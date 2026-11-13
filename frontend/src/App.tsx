import { useState } from 'react'
import { reviews, summary } from './demoData'
import './App.css'

type IconName = 'home' | 'plus' | 'layers' | 'book' | 'chart' | 'settings' | 'chevron' | 'arrow' | 'search' | 'bell' | 'alert' | 'check' | 'image' | 'file' | 'mail' | 'text'
const paths: Record<IconName, React.ReactNode> = {
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

function Sidebar() {
  const nav: { label: string; icon: IconName }[] = [{ label: 'Dashboard', icon: 'home' }, { label: 'New review', icon: 'plus' }, { label: 'Review library', icon: 'layers' }, { label: 'Brand knowledge', icon: 'book' }, { label: 'Insights', icon: 'chart' }]
  return <aside className="sidebar"><div className="brand"><span className="brand-mark" aria-hidden="true">∞</span><span>Inkloom AI</span></div><div className="workspace"><span className="eyebrow">WORKSPACE</span><div>Offscript Studio <Icon name="chevron" /></div></div><nav aria-label="Main navigation">{nav.map(item => item.label === 'Dashboard' ? <a className="nav-item active" href="#dashboard" aria-current="page" key={item.label}><Icon name={item.icon}/>{item.label}</a> : <span className="nav-item unavailable" key={item.label} title="Coming soon"><Icon name={item.icon}/>{item.label}<span className="sr-only"> (coming soon)</span></span>)}</nav><div className="sidebar-bottom"><span className="nav-item unavailable"><Icon name="settings"/>Settings <span className="sr-only">(coming soon)</span></span><div className="profile"><span className="avatar">AA</span><span>Alisha</span><Icon name="chevron"/></div></div></aside>
}
function Header() { return <header className="topbar"><div className="eyebrow">WORKSPACE <span>/</span> OVERVIEW</div><div className="top-actions"><span className="demo-badge">DEMO DATA</span><span className="top-divider"/><span className="header-icon" title="Search coming soon"><Icon name="search"/><span className="sr-only">Search coming soon</span></span><span className="header-icon notification" title="Notifications coming soon"><Icon name="bell"/><span className="sr-only">Notifications coming soon</span></span></div></header> }
function Hero({ onStart }: { onStart: () => void }) { return <section className="hero"><div className="hero-copy"><h1>Clarity before<br/>the spotlight.</h1><p>Review your content. See the evidence. Keep the final say.</p><div className="hero-actions"><button className="primary-button" onClick={onStart}>Start a review <Icon name="arrow"/></button><span className="text-link disabled-link">Open review library <small>Coming soon</small></span></div><div className="eyebrow formats">TEXT · IMAGES · PDF</div></div><img className="hero-art" src={`${import.meta.env.BASE_URL}assets/hero-ribbon-document-wide.png`} alt="Silver ribbon surrounding a document with a highlighted passage" /></section> }
function StatusSummary() { return <section className="summary" aria-label="Review summary, demo data">{summary.map(item => <div className="summary-item" key={item.label}><Icon name={item.icon} className={item.tone}/><strong>{item.count}</strong><span>{item.label}</span></div>)}</section> }
function RecentReviews({ showAll, onToggle }: { showAll: boolean; onToggle: () => void }) { return <section className="panel desk"><div className="desk-heading"><h2>{showAll ? "Review history" : "On your desk"}</h2><button className="reviews-link" onClick={onToggle}>{showAll ? "Show latest reviews" : "View all reviews"} <Icon name="arrow"/></button></div><div className="table-scroll"><table><thead><tr><th>Draft</th><th>Format</th><th>Status</th></tr></thead><tbody>{(showAll ? reviews : reviews.slice(0, 2)).map(review => <tr key={review.name}><td><span className="cell"><Icon name={review.icon}/>{review.name}</span></td><td><span className="cell"><Icon name={review.format === 'Text' ? 'text' : review.icon}/>{review.format}</span></td><td><span className={`status ${review.tone}`}><Icon name={review.tone === 'sage' ? 'check' : review.tone === 'amber' ? 'alert' : 'check'}/>{review.status}</span></td></tr>)}</tbody></table></div></section> }
function InfoCards() { return <div className="info-cards"><section className="panel attention"><h2>Needs your attention</h2><div className="info-content"><Icon name="alert"/><div><p>2 drafts need supporting<br className="desktop-only"/> evidence</p><span className="card-link">Review findings <Icon name="arrow"/><small>Coming soon</small></span></div></div></section><section className="panel knowledge"><h2>Brand knowledge</h2><div className="info-content"><Icon name="book"/><div><p>Mailchimp style guide</p><span className="card-link">View approved guidance <Icon name="arrow"/><small>Coming soon</small></span></div></div></section></div> }
function App() { const [placeholder, setPlaceholder] = useState(false); const [showAll, setShowAll] = useState(false); return <div className="app" id="dashboard"><Sidebar/><main className="main"><Header/>{placeholder ? <section className="placeholder panel"><h1>Start a review</h1><p>Review creation is coming soon.</p><button className="primary-button" onClick={() => setPlaceholder(false)}>Back to dashboard</button></section> : <><Hero onStart={() => setPlaceholder(true)}/><StatusSummary/><div className="dashboard-grid"><RecentReviews showAll={showAll} onToggle={() => setShowAll(!showAll)}/><InfoCards/></div></>}</main></div> }
export default App

