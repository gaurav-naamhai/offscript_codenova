import { useCallback, useEffect, useRef, useState } from 'react'
import { serverApi } from './serverApi'
import { guidanceCategories } from './knowledgeData'
import { listBrandDocuments } from './brandDocuments'
import type {
  AuthUser,
  BrandConstitution,
  BrandDocument,
  GuidelineRectification,
} from './serverApi'
import './KnowledgeInsights.css'

export default function BrandKnowledge({
  user,
  initialSelectedId,
  initialTab = 'docs',
  focusUpload = false,
  onSwitchAccount,
}: {
  user: AuthUser
  initialSelectedId?: string | null
  initialTab?: 'docs' | 'rectify'
  focusUpload?: boolean
  onSwitchAccount?: () => void
}) {
  const uploadInput = useRef<HTMLInputElement>(null)
  const [tab, setTab] = useState<'docs' | 'rectify'>(initialTab)
  const [docs, setDocs] = useState<BrandDocument[]>([])
  const [docVersions, setDocVersions] = useState<Record<string, BrandDocument[]>>({})
  const [constitution, setConstitution] = useState<BrandConstitution | null>(null)
  const [rectifications, setRectifications] = useState<GuidelineRectification[]>([])
  const [editedWording, setEditedWording] = useState<Record<string, string>>({})
  const [loading, setLoading] = useState(true)
  const [uploading, setUploading] = useState(false)
  const [scanning, setScanning] = useState(false)
  const [busyId, setBusyId] = useState('')
  const [error, setError] = useState('')
  const [loadError, setLoadError] = useState('')
  const [feedback, setFeedback] = useState('')
  const [search, setSearch] = useState('')
  const [category, setCategory] = useState('All')
  const [selected, setSelected] = useState<string | null>(initialSelectedId || null)
  const [title, setTitle] = useState('')
  const [group, setGroup] = useState<string>('guideline')
  const [version, setVersion] = useState('1.0')
  const [file, setFile] = useState<File | null>(null)
  const [deleting, setDeleting] = useState(false)

  useEffect(() => {
    if (focusUpload && tab === 'docs') {
      uploadInput.current?.focus()
      uploadInput.current?.scrollIntoView({ block: 'center' })
    }
  }, [focusUpload, tab])

  const fetchAll = useCallback(async () => {
    setLoading(true)
    try {
      const [list, constData, rectList] = await Promise.all([
        listBrandDocuments(),
        serverApi.brandConstitution().catch(() => null),
        serverApi.listRectifications().catch(() => []),
      ])
      setDocs(list)
      setConstitution(constData)
      setRectifications(rectList)
      setLoadError('')
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : 'Could not load brand documents from server.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void fetchAll()
    }, 0)
    return () => window.clearTimeout(timer)
  }, [fetchAll, user.org_id])

  async function loadVersions(docId: string) {
    try {
      const list = await serverApi.brandDocVersions(docId)
      setDocVersions(prev => ({ ...prev, [docId]: list }))
    } catch {
      /* ignore */
    }
  }

  function matches(item: BrandDocument) {
    const q = search.toLowerCase().trim()
    const matchText = !q || item.title.toLowerCase().includes(q) || (item.source_filename || '').toLowerCase().includes(q)
    const matchCat = category === 'All' || item.category.toLowerCase() === category.toLowerCase()
    return matchText && matchCat
  }

  async function save() {
    if (!file) {
      setError('Choose a PDF, image, or text file.')
      return
    }
    const uploadTitle = title.trim() || file.name.replace(/\.[^.]+$/, '') || file.name
    setUploading(true)
    setError('')
    setFeedback('Extracting, compiling Brand Constitution & indexing vectors…')
    try {
      const form = new FormData()
      form.append('title', uploadTitle)
      form.append('category', group.toLowerCase())
      form.append('version', version.trim() || '1.0')
      form.append('file', file)

      const created = await serverApi.uploadBrandDoc(form)
      setFeedback(`Uploaded "${created.title}" (v${created.version}) with ${created.chunks_count ?? 0} indexed chunks.`)
      setTitle('')
      setVersion('1.0')
      setFile(null)
      await fetchAll()
      setSelected(created.id)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to ingest brand document.')
      setFeedback('')
    } finally {
      setUploading(false)
    }
  }

  async function remove(docId: string) {
    setError('')
    try {
      await serverApi.deactivateBrandDoc(docId)
      setDeleting(false)
      setSelected(null)
      setFeedback('Document archived (kept in version history, excluded from active RAG checks).')
      await fetchAll()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not deactivate document.')
    }
  }

  async function handleScanRectifications() {
    setScanning(true)
    setError('')
    setFeedback('')
    try {
      const res = await serverApi.scanRectifications()
      setRectifications(res.rectifications)
      setFeedback(`Scanned ${res.scanned_chunks} active rule chunks: ${res.rectifications.length} rectification item(s) surfaced.`)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Guideline scan failed.')
    } finally {
      setScanning(false)
    }
  }

  async function handleApproveRect(rect: GuidelineRectification) {
    const wording = (editedWording[rect.id] ?? rect.suggested_wording).trim()
    if (!wording) return
    setBusyId(rect.id)
    setError('')
    try {
      const res = await serverApi.approveRectification(rect.id, wording)
      setFeedback(
        `Published rectified guideline "${res.new_document.title}" as v${res.new_document.version}. Previous version preserved in history.`
      )
      await fetchAll()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not approve guideline rectification.')
    } finally {
      setBusyId('')
    }
  }

  async function handleDismissRect(rect: GuidelineRectification) {
    setBusyId(rect.id)
    setError('')
    try {
      await serverApi.dismissRectification(rect.id)
      setFeedback('Guideline rectification dismissed.')
      await fetchAll()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not dismiss rectification.')
    } finally {
      setBusyId('')
    }
  }

  const canManageDocs = user.role === 'manager' || user.role === 'authorised_reviewer'
  const canApproveRect = user.role === 'manager'
  const activeDoc = docs.find(d => d.id === selected)
  const filtered = docs.filter(matches)
  const pendingCount = rectifications.filter(r => r.status === 'pending').length

  return (
    <div className="knowledge-page">
      <p className="judge-note">
        ★ For the judges:{' '}
        {tab === 'rectify'
          ? '{ AI scans your chunked brand rules for conflicts, unclear wording, or expired claims — Managers can edit and atomically publish a cleaner version, then test it in New Review. }'
          : '{ We use Hybrid RAG (pgvector + lexical search) to chunk out verified details from the PDFs/docs you upload. Next, head to New Review to test content against your verified brand guidelines. }'}
      </p>
      <header className="ki-heading">
        <h1>Brand knowledge.</h1>
        <p className="page-guidance">Add and manage the guidelines your team uses for reviews.</p>
      </header>

      <div className="ki-subtabs" role="tablist">
        <button
          type="button"
          role="tab"
          aria-selected={tab === 'docs'}
          className={`ki-subtab${tab === 'docs' ? ' active' : ''}`}
          onClick={() => setTab('docs')}
        >
          Guidelines &amp; Constitution ({docs.length})
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === 'rectify'}
          className={`ki-subtab${tab === 'rectify' ? ' active' : ''}`}
          onClick={() => setTab('rectify')}
        >
          Guideline Rectification {pendingCount > 0 ? `(${pendingCount} pending)` : ''}
        </button>
      </div>

      {error && <p className="validation" role="alert">{error}</p>}
      {feedback && <p className="ki-feedback" role="status">{feedback}</p>}

      {tab === 'docs' ? (
        <>
          {/* Compiled Brand Constitution Card */}
          {constitution && (
            <section className="panel ki-constitution stagger-card">
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '8px' }}>
                <div>
                  <span className="workspace-kicker">Auto-Compiled Brand Constitution</span>
                  <h2 style={{ margin: '6px 0 0' }}>{user.brand_name} Truth Snapshot</h2>
                </div>
                <span className="meta-chip">{constitution.documents_count} active document(s)</span>
              </div>

              <div className="constitution-grid">
                <div>
                  <h3>Approved Facts ({constitution.approved_facts.length})</h3>
                  {constitution.approved_facts.length ? (
                    <ul className="constitution-list">
                      {constitution.approved_facts.slice(0, 5).map((f, idx) => <li key={idx}>{f}</li>)}
                    </ul>
                  ) : (
                    <p className="workspace-muted">No structured facts extracted yet.</p>
                  )}
                </div>

                <div>
                  <h3>Forbidden Terms ({constitution.forbidden_terms.length})</h3>
                  {constitution.forbidden_terms.length ? (
                    <div className="chip-wrap">
                      {constitution.forbidden_terms.slice(0, 10).map((t, idx) => (
                        <span className="term-chip forbidden" key={idx}>{t}</span>
                      ))}
                    </div>
                  ) : (
                    <p className="workspace-muted">None specified.</p>
                  )}

                  {constitution.brand_colors.length > 0 && (
                    <div style={{ marginTop: '12px' }}>
                      <h3>Official Palette</h3>
                      <div className="chip-wrap">
                        {constitution.brand_colors.map((hex, idx) => (
                          <span className="color-swatch-chip" key={idx}>
                            <span className="swatch-dot" style={{ background: hex }} />
                            {hex}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              </div>
            </section>
          )}

          <div className="ki-grid">
            <section className="panel ki-panel">
              <h2>Upload guidelines</h2>
              {!canManageDocs ? (
                <div className="workspace-notice" style={{ background: '#fef3c7', color: '#78350f' }}>
                  <p style={{ margin: '0 0 10px' }}>
                    Signed in as <strong>Creator</strong>. Managers or Authorised Reviewers manage official brand documents.
                  </p>
                  {onSwitchAccount && (
                    <button type="button" className="outline-button" onClick={onSwitchAccount}>
                      Switch to Manager
                    </button>
                  )}
                </div>
              ) : (
                <>
                  <label className="ki-field">Choose file (PDF, image, or txt)
                    <input
                      ref={uploadInput}
                      key={selected ?? 'new'}
                      type="file"
                      accept=".pdf,.png,.jpg,.jpeg,.webp,.txt"
                      onChange={e => {
                        const next = e.target.files?.[0] || null
                        setFile(next)
                        setTitle(next ? next.name.replace(/\.[^.]+$/, '') || next.name : '')
                      }}
                    />
                  </label>
                  {file && (
                    <label className="ki-field">Title
                      <input value={title} onChange={e => setTitle(e.target.value)} />
                    </label>
                  )}
                  <details>
                    <summary>Category &amp; version</summary>
                    <label className="ki-field">Category
                      <select value={group} onChange={e => setGroup(e.target.value)}>
                        <option value="guideline">Guideline (default)</option>
                        {guidanceCategories.map(x => <option key={x}>{x}</option>)}
                      </select>
                    </label>
                    <label className="ki-field">Version
                      <input value={version} onChange={e => setVersion(e.target.value)} placeholder="1.0" />
                    </label>
                  </details>
                  <button type="button" className="primary-button" disabled={uploading} onClick={() => void save()} style={{ marginTop: '12px' }}>
                    {uploading ? 'Indexing…' : 'Upload guidelines'}
                  </button>
                </>
              )}
            </section>

            <section className="panel ki-panel">
              <h2>Active {user.brand_name} documents</h2>
              {docs.length > 0 && (
                <div className="ki-filters">
                  <label>Search documents<input type="search" value={search} onChange={e => setSearch(e.target.value)} /></label>
                  <label>Category
                    <select value={category} onChange={e => setCategory(e.target.value)}>
                      <option>All</option>
                      <option>Guideline</option>
                      {guidanceCategories.map(x => <option key={x}>{x}</option>)}
                    </select>
                  </label>
                </div>
              )}

              {loading ? (
                <p>Loading documents…</p>
              ) : loadError ? (
                <div role="alert">
                  <p>Could not load documents: {loadError}</p>
                  <button type="button" onClick={() => void fetchAll()}>Retry</button>
                </div>
              ) : filtered.length ? (
                filtered.map(item => (
                  <details
                    className="ki-document"
                    key={item.id}
                    open={selected === item.id}
                    onToggle={e => {
                      if (e.currentTarget.open) {
                        setSelected(item.id)
                        setDeleting(false)
                        void loadVersions(item.id)
                      } else if (selected === item.id) {
                        setSelected(null)
                      }
                    }}
                  >
                    <summary className="ki-doc">
                      <strong>{item.title}</strong>
                      <span>v{item.version} · {item.is_active ? 'Active' : 'Archived'} · {item.source_filename || 'File'}</span>
                    </summary>
                    <div style={{ padding: '0 14px 14px' }}>
                      <p style={{ margin: '6px 0', fontSize: '13px' }}>
                        Category: <strong>{item.category}</strong> · Version: <strong>v{item.version}</strong>
                      </p>

                      {docVersions[item.id] && docVersions[item.id].length > 0 && (
                        <div style={{ margin: '8px 0', fontSize: '12px' }}>
                          <strong>Version history:</strong>
                          <ul style={{ margin: '4px 0 0', paddingLeft: '18px' }}>
                            {docVersions[item.id].map(v => (
                              <li key={v.id}>
                                v{v.version} — {v.is_active ? 'Active (used by reviews)' : 'Archived previous version'}
                              </li>
                            ))}
                          </ul>
                        </div>
                      )}

                      {canManageDocs && (
                        deleting && activeDoc?.id === item.id ? (
                          <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                            <span>Archive this version?</span>
                            <button type="button" onClick={() => void remove(item.id)}>Confirm</button>
                            <button type="button" onClick={() => setDeleting(false)}>Cancel</button>
                          </div>
                        ) : (
                          <button type="button" onClick={() => { setSelected(item.id); setDeleting(true) }}>
                            Deactivate version
                          </button>
                        )
                      )}
                    </div>
                  </details>
                ))
              ) : (
                <p>{docs.length ? 'No documents match your filter.' : `No ${user.brand_name} documents uploaded yet.`}</p>
              )}
            </section>
          </div>
        </>
      ) : (
        /* Guideline Rectification Tab */
        <section className="panel ki-panel page-enter">
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '12px', flexWrap: 'wrap', marginBottom: '16px' }}>
            <div>
              <h2 style={{ margin: 0 }}>Guideline Rectification</h2>
              <p style={{ margin: '4px 0 0', fontSize: '14px', color: '#5f4841' }}>
                Detect unclear, conflicting, duplicate, or expired rules. Approved edits publish a new active version while keeping the previous version intact.
              </p>
            </div>
            {canManageDocs ? (
              <button type="button" className="primary-button" disabled={scanning} onClick={() => void handleScanRectifications()}>
                {scanning ? 'Scanning guidelines…' : 'Scan guidelines for issues'}
              </button>
            ) : onSwitchAccount ? (
              <button type="button" className="outline-button" onClick={onSwitchAccount}>
                Switch to Manager to scan &amp; approve
              </button>
            ) : null}
          </div>

          {rectifications.length === 0 ? (
            <p className="workspace-muted">
              No rectification issues queued. Click &ldquo;Scan guidelines for issues&rdquo; to audit active {user.brand_name} rules.
            </p>
          ) : (
            <div className="rect-list">
              {rectifications.map(r => {
                const draftWording = editedWording[r.id] ?? r.suggested_wording
                return (
                  <article className="rect-card stagger-card" key={r.id}>
                    <div className="rect-card-head">
                      <div style={{ display: 'flex', gap: '8px', alignItems: 'center', flexWrap: 'wrap' }}>
                        <span className={`rect-badge type-${r.issue_type}`}>{r.issue_type}</span>
                        <span className={`rect-badge sev-${r.severity}`}>{r.severity} priority</span>
                        <strong>{r.document_title} (v{r.document_version})</strong>
                        {r.section && <span className="meta-chip">{r.section}</span>}
                      </div>
                      <span className={`rect-status status-${r.status}`}>{r.status}</span>
                    </div>

                    <p className="rect-problem">{r.problem_explanation}</p>

                    <div className="rect-compare">
                      <div>
                        <span className="verbatim-label">Current rule text</span>
                        <p className="rect-original">{r.original_text}</p>
                      </div>
                      {r.conflicting_text && (
                        <div>
                          <span className="verbatim-label" style={{ color: '#991b1b' }}>
                            Related / conflicting rule ({r.conflicting_document})
                          </span>
                          <p className="rect-original">{r.conflicting_text}</p>
                        </div>
                      )}
                    </div>

                    {r.status === 'pending' ? (
                      canApproveRect ? (
                        <div className="rect-edit-area">
                          <label htmlFor={`rect-${r.id}`}>Proposed clearer wording (Manager editable)</label>
                          <textarea
                            id={`rect-${r.id}`}
                            rows={3}
                            value={draftWording}
                            onChange={e => setEditedWording(prev => ({ ...prev, [r.id]: e.target.value }))}
                            disabled={busyId === r.id}
                          />
                          <div style={{ display: 'flex', gap: '10px', marginTop: '8px', flexWrap: 'wrap' }}>
                            <button
                              type="button"
                              className="primary-button"
                              disabled={busyId === r.id || !draftWording.trim()}
                              onClick={() => void handleApproveRect(r)}
                              style={{ padding: '8px 16px', fontSize: '13px' }}
                            >
                              {busyId === r.id ? 'Publishing…' : 'Approve & publish new version'}
                            </button>
                            <button
                              type="button"
                              className="outline-button"
                              disabled={busyId === r.id}
                              onClick={() => void handleDismissRect(r)}
                            >
                              Dismiss
                            </button>
                          </div>
                        </div>
                      ) : (
                        <p className="workspace-muted">
                          Suggested wording: &ldquo;{r.suggested_wording}&rdquo; — Manager approval required to publish a new guideline version.
                        </p>
                      )
                    ) : r.status === 'approved' ? (
                      <div className="workspace-notice" style={{ background: '#f0fdf4', color: '#166534', marginTop: '8px', fontSize: '13px' }}>
                        Approved by <strong>{r.reviewed_by || 'Manager'}</strong> → Published as <strong>v{r.new_version}</strong>: &ldquo;{r.approved_wording}&rdquo;
                      </div>
                    ) : (
                      <p className="workspace-muted">Dismissed by {r.reviewed_by || 'Manager'}.</p>
                    )}
                  </article>
                )
              })}
            </div>
          )}
        </section>
      )}
    </div>
  )
}
