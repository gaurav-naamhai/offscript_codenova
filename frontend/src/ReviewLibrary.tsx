import { useCallback, useEffect, useState } from 'react'
import { serverApi } from './serverApi'
import type { SubmissionSummary } from './serverApi'
import './ReviewLibrary.css'

export default function ReviewLibrary({
  onOpen,
  onNew,
}: {
  onOpen: (id: string) => void
  onNew: () => void
}) {
  const [items, setItems] = useState<SubmissionSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [feedback, setFeedback] = useState('')
  const [query, setQuery] = useState('')
  const [format, setFormat] = useState('All')
  const [status, setStatus] = useState('All')

  const fetchSubmissions = useCallback(async () => {
    try {
      setError('')
      const data = await serverApi.list()
      setItems(data)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not fetch submissions from server.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void fetchSubmissions()
  }, [fetchSubmissions])

  async function handleSeed() {
    setBusy(true)
    setError('')
    setFeedback('Seeding sample submissions for demonstration...')
    try {
      await serverApi.seed()
      await fetchSubmissions()
      setFeedback('Sample submissions seeded successfully.')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to seed demo submissions.')
      setFeedback('')
    } finally {
      setBusy(false)
    }
  }

  const filtered = items.filter(r => {
    const titleMatch = (r.title || 'Untitled submission').toLowerCase().includes(query.trim().toLowerCase())
    const formatMatch = format === 'All' || r.content_type.toLowerCase() === format.toLowerCase()
    const statusMatch = status === 'All' || r.status.toLowerCase() === status.toLowerCase()
    return titleMatch && formatMatch && statusMatch
  })

  return (
    <section className="library">
      <header className="library-heading">
        <div>
          <h1>Review library.</h1>
          <p>Governance pipeline tracking pre-publication brand compliance reviews.</p>
        </div>
        <div style={{ display: 'flex', gap: '10px' }}>
          <button type="button" className="outline-button" onClick={handleSeed} disabled={busy || loading} title="Seed 3 sample submissions into the server">
            {busy ? 'Seeding...' : 'Seed demo submissions'}
          </button>
          <button type="button" className="primary-button" onClick={onNew}>
            New review <span aria-hidden="true">→</span>
          </button>
        </div>
      </header>

      {feedback && <p className="library-note" role="status" style={{ color: '#e3c8f4' }}>{feedback}</p>}
      {error && <div className="validation" role="alert" style={{ margin: '12px 0' }}>{error}</div>}

      <div className="panel library-panel">
        <div className="library-filters">
          <label>
            Search by title
            <input
              type="search"
              value={query}
              onChange={e => setQuery(e.target.value)}
              placeholder="Search reviews..."
            />
          </label>
          <label>
            Content type
            <select value={format} onChange={e => setFormat(e.target.value)}>
              <option value="All">All formats</option>
              <option value="text">Text</option>
              <option value="image">Image</option>
              <option value="pdf">PDF</option>
            </select>
          </label>
          <label>
            Review status
            <select value={status} onChange={e => setStatus(e.target.value)}>
              <option value="All">All states</option>
              <option value="draft">Draft</option>
              <option value="ai_review">AI Review</option>
              <option value="manager_review">Manager Review</option>
              <option value="final_approval">Final Approval</option>
              <option value="approved">Approved</option>
            </select>
          </label>
        </div>

        {loading ? (
          <p style={{ padding: '24px', textAlign: 'center' }}>Connecting to compliance backend...</p>
        ) : filtered.length ? (
          <div className="library-list">
            {filtered.map(r => (
              <article className="library-row" key={r.id}>
                <div>
                  <h2>{r.title || 'Untitled submission'}</h2>
                  <p>
                    {r.content_type.toUpperCase()} · Status:{' '}
                    <strong style={{ color: r.status === 'approved' ? '#2e7d32' : '#6a1b9a' }}>
                      {r.status.replace('_', ' ').toUpperCase()}
                    </strong>{' '}
                    · v{r.version} · {r.flag_count} findings ({r.needs_human_count} need human review)
                  </p>
                  <small style={{ color: '#6d5b56' }}>
                    Created: {new Date(r.created_at).toLocaleString()} · ID: {r.id.slice(0, 8)}...
                  </small>
                </div>
                <div className="library-actions">
                  <button type="button" onClick={() => onOpen(r.id)}>Open / review</button>
                </div>
              </article>
            ))}
          </div>
        ) : (
          <div className="library-empty">
            {items.length
              ? 'No reviews match these filters.'
              : 'No submissions in server database. Click "Seed demo submissions" above or start your first review.'}
          </div>
        )}
      </div>
    </section>
  )
}
