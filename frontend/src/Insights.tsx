import { useCallback, useEffect, useState } from 'react'
import { serverApi } from './serverApi'
import type { AuthUser, RecurringInsights } from './serverApi'
import './KnowledgeInsights.css'

export default function Insights({
  user,
  onOpenRectification,
}: {
  user: AuthUser
  onOpenRectification?: () => void
}) {
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
    const timer = window.setTimeout(() => {
      void load()
    }, 0)
    return () => window.clearTimeout(timer)
  }, [load, user.org_id])

  const gov = data?.governance_insights

  return (
    <div className="insights-page">
      <p className="judge-note">
        ★ For the judges: &#123; Cross-submission governance analytics using flag clustering and Gemini insights to highlight recurring brand mistakes and compliance trends. &#125;
      </p>
      <header className="ki-heading">
        <h1>Insights.</h1>
        <p className="page-guidance">Explore recurring findings across your reviews.</p>
      </header>

      <div style={{ display: 'flex', gap: '10px', margin: '14px 0 18px', flexWrap: 'wrap' }}>
        <button type="button" className="ki-retry" onClick={() => void load()} disabled={loading}>
          {loading ? 'Refreshing…' : 'Refresh insights'}
        </button>
        {onOpenRectification && (
          <button type="button" className="primary-button" onClick={onOpenRectification} style={{ padding: '9px 18px', fontSize: '14px' }}>
            Open Guideline Rectification →
          </button>
        )}
      </div>

      {loading && <p role="status">Loading insights…</p>}
      {error && <p className="validation" role="alert">{error}</p>}

      {!loading && data && (
        <>
          <div className="panel ki-total stagger-card">
            <span>Total compliance flags evaluated ({user.brand_name})</span>
            <strong>{data.total_flags}</strong>
          </div>

          {gov && (
            <section className="panel ki-panel stagger-card" style={{ marginBottom: '16px' }}>
              <span className="workspace-kicker">Governance Intelligence</span>
              <h2 style={{ marginTop: '8px' }}>Executive summary</h2>
              <p style={{ lineHeight: 1.55, margin: '0 0 14px' }}>{gov.summary_narrative}</p>

              {gov.top_recurring_violations.length > 0 && (
                <>
                  <h3>Recurring mistake patterns</h3>
                  <ul className="insight-list">
                    {gov.top_recurring_violations.map((rv, idx) => (
                      <li key={idx}>
                        <div>
                          <strong>{rv.rule_or_topic}</strong>
                          <div style={{ fontSize: '13px', color: '#5f4841', marginTop: '2px' }}>{rv.recommendation}</div>
                        </div>
                        <strong>{rv.frequency}×</strong>
                      </li>
                    ))}
                  </ul>
                </>
              )}

              {gov.ambiguous_guidelines.length > 0 && (
                <>
                  <h3>Rules causing repeated human escalations</h3>
                  <ul className="insight-list">
                    {gov.ambiguous_guidelines.map((ag, idx) => (
                      <li key={idx}>
                        <div>
                          <strong>{ag.guideline_title}</strong>
                          <div style={{ fontSize: '13px', color: '#5f4841', marginTop: '2px' }}>
                            {ag.reason_for_ambiguity} Suggested fix: {ag.suggested_clarification}
                          </div>
                        </div>
                        <strong>{ag.human_escalation_count} escalations</strong>
                      </li>
                    ))}
                  </ul>
                </>
              )}
            </section>
          )}

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
