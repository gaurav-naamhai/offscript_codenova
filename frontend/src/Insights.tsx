import { useCallback, useEffect, useState } from 'react'
import { serverApi } from './serverApi'
import type { RecurringInsights } from './serverApi'
import './KnowledgeInsights.css'

export default function Insights() {
  const [data, setData] = useState<RecurringInsights | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      setData(await serverApi.insights())
    } catch (e) {
      setData(null)
      setError(e instanceof Error ? e.message : 'Insights unavailable.')
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
        <p>Live recurring compliance metrics across all evaluated content drafts.</p>
      </header>
      <p className="ki-disclosure">Aggregated guideline violations and factual verification states across the submission pipeline.</p>
      <button className="ki-retry" onClick={() => void load()} disabled={loading}>
        {loading ? 'Refreshing...' : 'Refresh insights'}
      </button>
      {loading && <p role="status">Loading insights from compliance backend...</p>}
      {error && <p className="validation" role="alert">{error}</p>}
      {!loading && data && (
        <>
          <div className="panel ki-total">
            <span>Total compliance flags</span>
            <strong>{data.total_flags}</strong>
          </div>
          <div className="insight-grid">
            <section className="panel ki-panel">
              <h2>Most violated guidelines</h2>
              {data.top_guidelines.length ? (
                <ul className="insight-list">
                  {data.top_guidelines.map((item, index) => (
                    <li key={index}>
                      <span>{typeof item.guideline === 'string' ? item.guideline : 'Unspecified guideline'}</span>
                      <strong>{typeof item.count === 'number' ? item.count : 'Unavailable'}</strong>
                    </li>
                  ))}
                </ul>
              ) : (
                <p>No recurring guidelines recorded yet.</p>
              )}
            </section>
            <section className="panel ki-panel">
              <h2>Assessment distributions</h2>
              {Object.keys(data.state_counts).length ? (
                <ul className="insight-list">
                  {Object.entries(data.state_counts).map(([state, count]) => (
                    <li key={state}>
                      <span>{state.replaceAll('_', ' ').toUpperCase()}</span>
                      <strong>{count}</strong>
                    </li>
                  ))}
                </ul>
              ) : (
                <p>No assessment counts available.</p>
              )}
            </section>
          </div>
        </>
      )}
    </div>
  )
}
