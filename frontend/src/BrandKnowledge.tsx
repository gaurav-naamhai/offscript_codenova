import { useEffect, useState } from 'react'
import { apiBase } from './serverApi'
import { guidanceCategories } from './knowledgeData'
import './KnowledgeInsights.css'

type ServerBrandDoc = {
  id: string
  title: string
  category: string
  version: string
  is_active: boolean
  source_filename?: string | null
  created_at?: string
  chunks_count?: number
}

export default function BrandKnowledge() {
  const [docs, setDocs] = useState<ServerBrandDoc[]>([])
  const [loading, setLoading] = useState(true)
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState('')
  const [feedback, setFeedback] = useState('')
  const [search, setSearch] = useState('')
  const [category, setCategory] = useState('All')
  const [selected, setSelected] = useState<string | null>(null)
  const [title, setTitle] = useState('')
  const [group, setGroup] = useState<string>(guidanceCategories[0])
  const [version, setVersion] = useState('1.0')
  const [file, setFile] = useState<File | null>(null)
  const [deleting, setDeleting] = useState(false)

  async function fetchDocs() {
    setLoading(true)
    try {
      const res = await fetch(`${apiBase}/brand-docs`)
      if (!res.ok) throw new Error(`Server returned ${res.status}`)
      const data = await res.json()
      const list: ServerBrandDoc[] = Array.isArray(data.documents) ? data.documents : []
      setDocs(list)
      setError('')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not load brand documents from server.')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void fetchDocs()
  }, [])

  function matches(item: ServerBrandDoc) {
    const q = search.toLowerCase().trim()
    const matchText = !q || item.title.toLowerCase().includes(q) || (item.source_filename || '').toLowerCase().includes(q)
    const matchCat = category === 'All' || item.category.toLowerCase() === category.toLowerCase()
    return matchText && matchCat
  }

  async function save() {
    if (!title.trim() || !file) {
      setError('Enter a title and choose a PDF, image, or text file.')
      return
    }
    setUploading(true)
    setError('')
    setFeedback('Extracting, chunking, embedding, and storing in Supabase RAG...')
    try {
      const form = new FormData()
      form.append('title', title.trim())
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
      const created: ServerBrandDoc = await res.json()
      setFeedback(`Ingested "${created.title}" (${created.chunks_count ?? 0} chunks stored in Supabase RAG).`)
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
      setFeedback('Document deactivated (excluded from RAG search).')
      await fetchDocs()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not deactivate document.')
    }
  }

  const activeDoc = docs.find((d) => d.id === selected)
  const filtered = docs.filter(matches)

  return (
    <div className="knowledge-page">
      <header className="ki-heading">
        <h1>Brand knowledge.</h1>
        <p>Upload approved brand guidelines, identity rules, and facts to Supabase pgvector RAG.</p>
      </header>
      <p className="ki-disclosure">
        Connected to {apiBase}. Uploaded files are extracted, chunked, embedded with Gemini, and stored in Supabase.
      </p>
      {error && (
        <p className="validation" role="alert">
          {error}
        </p>
      )}
      {feedback && (
        <p className="ki-feedback" role="status">
          {feedback}
        </p>
      )}
      <div className="ki-grid">
        <section className="panel ki-panel">
          <h2>Active brand documents ({docs.length})</h2>
          <div className="ki-filters">
            <label>
              Search documents
              <input type="search" value={search} onChange={(e) => setSearch(e.target.value)} />
            </label>
            <label>
              Category
              <select value={category} onChange={(e) => setCategory(e.target.value)}>
                <option>All</option>
                {guidanceCategories.map((x) => (
                  <option key={x}>{x}</option>
                ))}
              </select>
            </label>
          </div>
          {loading ? (
            <p>Loading brand documents from Supabase...</p>
          ) : filtered.length ? (
            filtered.map((item) => (
              <button
                className="ki-doc"
                key={item.id}
                onClick={() => {
                  setSelected(item.id)
                  setDeleting(false)
                }}
              >
                <strong>{item.title}</strong>
                <span>
                  {item.category} · v{item.version} · {item.source_filename || 'uploaded'}
                </span>
              </button>
            ))
          ) : (
            <p>{docs.length ? 'No documents match your filter.' : 'No brand documents uploaded yet. Add one on the right!'}</p>
          )}
        </section>

        <div className="ki-side">
          <section className="panel ki-panel">
            <h2>Document details</h2>
            {activeDoc ? (
              <>
                <span className="format-badge">INDEXED IN SUPABASE RAG</span>
                <h3>{activeDoc.title}</h3>
                <p>
                  Category: {activeDoc.category} · Version: v{activeDoc.version}
                </p>
                <p>Source file: {activeDoc.source_filename || 'N/A'}</p>
                {deleting ? (
                  <div>
                    <p>Deactivate this brand document from RAG search?</p>
                    <button onClick={() => void remove(activeDoc.id)}>Confirm deactivate</button>{' '}
                    <button onClick={() => setDeleting(false)}>Cancel</button>
                  </div>
                ) : (
                  <button onClick={() => setDeleting(true)}>Deactivate document</button>
                )}
              </>
            ) : (
              <p>Select a document to view its details.</p>
            )}
          </section>

          <section className="panel ki-panel">
            <h2>Upload brand document</h2>
            <label className="ki-field">
              Title
              <input
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="e.g. Nike Brand Guidelines"
              />
            </label>
            <label className="ki-field">
              Category
              <select value={group} onChange={(e) => setGroup(e.target.value)}>
                {guidanceCategories.map((x) => (
                  <option key={x}>{x}</option>
                ))}
              </select>
            </label>
            <label className="ki-field">
              Version
              <input value={version} onChange={(e) => setVersion(e.target.value)} placeholder="1.0" />
            </label>
            <label className="ki-field">
              Choose file (PDF, image, or txt)
              <input
                key={selected ?? 'new'}
                type="file"
                accept=".pdf,.png,.jpg,.jpeg,.webp,.txt"
                onChange={(e) => setFile(e.target.files?.[0] || null)}
              />
            </label>
            <button className="primary-button" disabled={uploading} onClick={() => void save()}>
              {uploading ? 'Ingesting into RAG...' : 'Upload & index in Supabase'}
            </button>
          </section>
        </div>
      </div>
    </div>
  )
}
