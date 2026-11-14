import { useEffect, useState } from 'react'
import { apiBase } from './serverApi'
import { guidanceCategories } from './knowledgeData'
import { listBrandDocuments } from './brandDocuments'
import type { BrandDocument } from './brandDocuments'
import './KnowledgeInsights.css'

export default function BrandKnowledge({ initialSelectedId }: { initialSelectedId?: string | null }) {
  const [docs, setDocs] = useState<BrandDocument[]>([])
  const [loading, setLoading] = useState(true)
  const [uploading, setUploading] = useState(false)
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

  async function fetchDocs() {
    setLoading(true)
    try {
      const list = await listBrandDocuments()
      setDocs(list)
      setLoadError('')
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : 'Could not load brand documents from server.')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void fetchDocs()
  }, [])

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
    setFeedback('Uploading guidelines...')
    try {
      const form = new FormData()
      form.append('title', uploadTitle)
      form.append('category', group.toLowerCase())
      form.append('version', version.trim() || '1.0')
      form.append('file', file)

      const res = await fetch(`${apiBase}/brand-docs`, {
        method: 'POST',
        body: form,
      })
      if (!res.ok) {
        const errBody = await res.json().catch(() => ({}))
        throw new Error(errBody.detail || `Upload failed (${res.status})`)
      }
      const created: BrandDocument = await res.json()
      setFeedback(`Upload completed: "${created.title}". Check the document list for its current status.`)
      setTitle('')
      setVersion('1.0')
      setFile(null)
      await fetchDocs()
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
      const res = await fetch(`${apiBase}/brand-docs/${docId}`, { method: 'DELETE' })
      if (!res.ok) throw new Error(`Delete failed (${res.status})`)
      setDeleting(false)
      setSelected(null)
      setFeedback('Document deactivated.')
      await fetchDocs()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not deactivate document.')
    }
  }

  const activeDoc = docs.find((d) => d.id === selected)
  const filtered = docs.filter(matches)

  return (
    <div className="knowledge-page">
      <header className="ki-heading"><h1>Brand knowledge.</h1><p>Upload and manage your brand guidelines.</p></header>
      <details className="ki-disclosure"><summary>Technical details</summary><p>Connected to {apiBase}. The server extracts and indexes uploaded files using its configured providers.</p></details>
      {error && <p className="validation" role="alert">{error}</p>}
      {feedback && <p className="ki-feedback" role="status">{feedback}</p>}
      <div className="ki-grid">
        <section className="panel ki-panel">
          <h2>Upload guidelines</h2>
          <label className="ki-field">Choose file (PDF, image, or txt)
            <input key={selected ?? 'new'} type="file" accept=".pdf,.png,.jpg,.jpeg,.webp,.txt" onChange={e => { const next = e.target.files?.[0] || null; setFile(next); setTitle(next ? next.name.replace(/\.[^.]+$/, '') || next.name : '') }} />
          </label>
          {file && <label className="ki-field">Title (optional rename)<input value={title} onChange={e => setTitle(e.target.value)} /></label>}
          <details><summary>Optional details</summary>
            <label className="ki-field">Category<select value={group} onChange={e => setGroup(e.target.value)}><option value="guideline">Guideline (default)</option>{guidanceCategories.map(x => <option key={x}>{x}</option>)}</select></label>
            <label className="ki-field">Version<input value={version} onChange={e => setVersion(e.target.value)} placeholder="1.0" /></label>
          </details>
          <button className="primary-button" disabled={uploading} onClick={() => void save()}>{uploading ? 'Uploading...' : 'Upload guidelines'}</button>
        </section>
        <section className="panel ki-panel">
          <h2>Brand documents</h2>
          {docs.length > 0 && <div className="ki-filters"><label>Search documents<input type="search" value={search} onChange={e => setSearch(e.target.value)} /></label><label>Category<select value={category} onChange={e => setCategory(e.target.value)}><option>All</option><option>Guideline</option>{guidanceCategories.map(x => <option key={x}>{x}</option>)}</select></label></div>}
          {loading ? <p>Loading documents...</p> : loadError ? <div role="alert"><p>Could not load documents: {loadError}</p><button type="button" onClick={() => void fetchDocs()}>Retry</button></div> : filtered.length ? filtered.map(item => <details className="ki-document" key={item.id} open={selected === item.id} onToggle={e => { if (e.currentTarget.open) { setSelected(item.id); setDeleting(false) } else if (selected === item.id) setSelected(null) }}>
            <summary className="ki-doc"><strong>{item.title}</strong><span>{item.is_active ? 'Active' : 'Inactive'} · {item.source_filename || 'Filename unavailable'}</span></summary>
            <div><p>Category: {item.category} · Version: {item.version}</p><p>Processing readiness is not reported by the document list.</p>
              {deleting && activeDoc?.id === item.id ? <div><p>Deactivate this document?</p><button type="button" onClick={() => void remove(item.id)}>Confirm deactivate</button> <button type="button" onClick={() => setDeleting(false)}>Cancel</button></div> : <button type="button" onClick={() => { setSelected(item.id); setDeleting(true) }}>Deactivate document</button>}
            </div></details>) : <p>{docs.length ? 'No documents match your filter.' : 'No documents returned. Upload guidelines to get started.'}</p>}
        </section>
      </div>
    </div>
  )
}
