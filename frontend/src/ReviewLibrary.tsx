import { useEffect, useState } from 'react'
import { apiBase, serverApi } from './serverApi'
import type { SubmissionSummary } from './serverApi'
import { deleteMetadata, readAllMetadata } from './metadataStore'
import type { ClientMetadata } from './metadataStore'
import './ReviewLibrary.css'

export default function ReviewLibrary({
  onOpen,
  onNew,
}: {
  onOpen: (id: string) => void
  onNew: () => void
}) {
  const [submissions, setSubmissions] = useState<SubmissionSummary[]>([])
  const [metadata, setMetadata] = useState<Record<string, ClientMetadata>>({})
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  const [query, setQuery] = useState('')
  const [format, setFormat] = useState('All')
  const [status, setStatus] = useState('All')
  const [deletingId, setDeletingId] = useState<string | null>(null)

  async function fetchList() {
    setLoading(true)
    setError('')
    try {
      const list = await serverApi.list()
      setSubmissions(list)
      setMetadata(readAllMetadata())
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : 'Could not load server submissions. The server may still be spinning up.'
      )
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void fetchList()
  }, [])

  function handleLocalDelete(id: string) {
    const result = deleteMetadata(id)
    if (result.error) {
      setError(result.error)
    } else {
      setMetadata(readAllMetadata())
      setNotice('Removed metadata from this browser. The submission remains on the server.')
    }
    setDeletingId(null)
  }

  const filtered = submissions.filter(item => {
    const title = metadata[item.id]?.title || 'Untitled submission'
    const matchesQuery =
      title.toLowerCase().includes(query.trim().toLowerCase()) ||
      item.id.toLowerCase().includes(query.trim().toLowerCase())
    const matchesFormat = format === 'All' || item.content_type.toLowerCase() === format.toLowerCase()
    const matchesStatus = status === 'All' || item.status.toLowerCase() === status.toLowerCase()
    return matchesQuery && matchesFormat && matchesStatus
  })

  return (
    <section className="library">
      <header className="library-heading">
        <div>
          <h1>Review library.</h1>
          <p>Server submissions and local browser metadata.</p>
        </div>
        <div style={{ display: 'flex', gap: '10px' }}>
          <button type="button" className="outline-button" onClick={() => void fetchList()} disabled={loading}>
            {loading ? 'Refreshing…' : 'Refresh list'}
          </button>
          <button type="button" className="primary-button" onClick={onNew}>
            New review <span aria-hidden="true">→</span>
          </button>
        </div>
      </header>

      <div className="workspace-banner" style={{ margin: '14px 0' }}>
        <strong>Placeholder checks. No live AI analysis.</strong>
        <span> Submissions are stored on {apiBase}. Free-tier server data resets periodically.</span>
      </div>

      {notice && (
        <p className="workspace-notice" role="status">
          {notice}
        </p>
      )}

      {error && (
        <div className="validation" role="alert" style={{ marginBottom: '14px' }}>
          <strong>Error:</strong> {error}
          <div style={{ marginTop: '8px' }}>
            <button type="button" onClick={() => void fetchList()}>
              Retry
            </button>
          </div>
        </div>
      )}

      <div className="panel library-panel">
        <div className="library-filters">
          <label>
            Search by title or ID
            <input
              type="search"
              value={query}
              onChange={e => setQuery(e.target.value)}
              placeholder="Search reviews…"
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
            Workflow status
            <select value={status} onChange={e => setStatus(e.target.value)}>
              <option value="All">All statuses</option>
              <option value="draft">Draft</option>
              <option value="manager_review">Manager review</option>
              <option value="final_approval">Final approval</option>
              <option value="approved">Approved</option>
            </select>
          </label>
        </div>

        {loading ? (
          <div className="library-empty">
            Connecting to the server. The first request can take up to a minute…
          </div>
        ) : filtered.length > 0 ? (
          <div className="library-list">
            {filtered.map(item => {
              const meta = metadata[item.id]
              const title = meta?.title || 'Untitled submission'
              return (
                <article className="library-row" key={item.id}>
                  <div>
                    <h2>{title}</h2>
                    <p>
                      <strong>{item.content_type.toUpperCase()}</strong> · Status:{' '}
                      <span className="status lavender" style={{ padding: '2px 8px', fontSize: '13px' }}>
                        {item.status}
                      </span>{' '}
                      · v{item.version} · {item.flag_count} findings ({item.needs_human_count} need human review)
                    </p>
                    <p className="workspace-muted" style={{ fontSize: '12px', marginTop: '4px' }}>
                      ID: {item.id} · Created {new Date(item.created_at).toLocaleString()}
                    </p>
                  </div>
                  <div className="library-actions">
                    <button type="button" onClick={() => onOpen(item.id)}>
                      Open / review
                    </button>
                    {deletingId === item.id ? (
                      <span className="delete-confirm">
                        Remove from this browser?
                        <button type="button" onClick={() => handleLocalDelete(item.id)}>
                          Confirm remove
                        </button>
                        <button type="button" onClick={() => setDeletingId(null)}>
                          Cancel
                        </button>
                      </span>
                    ) : (
                      <button
                        type="button"
                        onClick={() => setDeletingId(item.id)}
                        title="Removes metadata from this browser only (server has no delete endpoint)"
                      >
                        Remove from browser
                      </button>
                    )}
                  </div>
                </article>
              )
            })}
          </div>
        ) : (
          <div className="library-empty">
            {submissions.length > 0
              ? 'No reviews match these filters.'
              : 'No submissions found on the server. Click "New review" to create one.'}
          </div>
        )}
      </div>

      <p className="library-note" style={{ marginTop: '12px' }}>
        Removing a submission removes its title and metadata from this browser only. The server does
        not implement deletion, and reset occurs periodically on the hosting provider.
      </p>
    </section>
  )
}
