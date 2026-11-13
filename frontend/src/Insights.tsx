import { useCallback, useEffect, useState } from 'react'
import { apiBase, serverApi } from './serverApi'
import type { RecurringInsights } from './serverApi'
import './KnowledgeInsights.css'

export default function Insights() {
  const [data, setData] = useState<RecurringInsights | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      setData(await serverApi.insights())
    } catch (e) {
      setData(null)
      setError(
        e instanceof Error
          ? e.message
          : 'Could not load recurring insights. The server may be starting up.'
      )
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  return (
    <div className="insights-page">
      <header className="ki-heading">
        <h1>Insights.</h1>
        <p>Server recurring findings · includes placeholder review findings from {apiBase}.</p>
      </header>

      <div className="workspace-banner" style={{ margin: '14px 0' }}>
        <strong>Placeholder checks. No live AI analysis.</strong>
        <span> Free-tier server data resets periodically.</span>
      </div>

      <p className="ki-disclosure">
        Counts describe findings, not approved content or proof that checks passed.
      </p>

      <button
        type="button"
        className="ki-retry"
        onClick={() => void load()}
        disabled={loading}
        style={{ marginBottom: '16px' }}
      >
        {loading ? 'Refreshing…' : 'Refresh insights'}
      </button>

      {loading && (
        <p role="status">Connecting to the server. The first request can take up to a minute…</p>
      )}

      {error && (
        <div className="validation" role="alert" style={{ marginBottom: '16px' }}>
          <strong>Error:</strong> {error}
        </div>
      )}

      {!loading && data && (
        <>
          <div className="panel ki-total">
            <span>Total findings recorded</span>
            <strong>{data.total_flags}</strong>
          </div>

          <div className="insight-grid">
            <section className="panel ki-panel">
              <h2>Recurring guidelines</h2>
              {data.top_guidelines.length ? (
                <ul className="insight-list">
                  {data.top_guidelines.map((item, index) => (
                    <li key={index}>
                      <span>
                        {typeof item.guideline === 'string'
                          ? item.guideline
                          : 'Unspecified guideline'}
                      </span>
                      <strong>
                        {typeof item.count === 'number' ? item.count : 'Unavailable'}
                      </strong>
                    </li>
                  ))}
                </ul>
              ) : (
                <p>No guideline counts available on the server.</p>
              )}
            </section>

            <section className="panel ki-panel">
              <h2>Assessment states</h2>
              {Object.keys(data.state_counts).length ? (
                <ul className="insight-list">
                  {Object.entries(data.state_counts).map(([state, count]) => (
                    <li key={state}>
                      <span>{state.replaceAll('_', ' ')}</span>
                      <strong>{count}</strong>
                    </li>
                  ))}
                </ul>
              ) : (
                <p>No assessment counts recorded on the server.</p>
              )}
            </section>
          </div>
        </>
      )}
    </div>
  )
}
