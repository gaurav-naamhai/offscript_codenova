import { useCallback, useEffect, useState } from 'react'
import { serverApi } from './serverApi'
import type { AuditEvent, RecheckResult, ServerDetail, ServerFlag, VersionInfo } from './serverApi'
import './ReviewWorkspace.css'

function compareText(original: string, correction: string) {
  const tokenize = (text: string) => text.match(/[\p{L}\p{M}\p{N}]+|[^\p{L}\p{M}\p{N}\s]|\s+/gu) || []
  const before = tokenize(original), after = tokenize(correction)
  const removed = new Set<number>(), added = new Set<number>()
  // Avoid expensive comparisons for unusually long passages.
  if (before.length * after.length > 1_000_000) return { before, after, removed, added }
  const rows = Array.from({ length: before.length + 1 }, () => new Uint32Array(after.length + 1))
  for (let i = before.length - 1; i >= 0; i--) for (let j = after.length - 1; j >= 0; j--)
    rows[i][j] = before[i] === after[j] ? 1 + rows[i + 1][j + 1] : Math.max(rows[i + 1][j], rows[i][j + 1])
  let i = 0, j = 0
  while (i < before.length && j < after.length) {
    if (before[i] === after[j]) { i++; j++ }
    else if (rows[i + 1][j] >= rows[i][j + 1]) { removed.add(i++); }
    else { added.add(j++); }
  }
  while (i < before.length) removed.add(i++)
  while (j < after.length) added.add(j++)
  return { before, after, removed, added }
}

function DiffText({ tokens, changes, kind }: { tokens: string[]; changes: Set<number>; kind: 'removed' | 'added' }) {
  return <>{tokens.map((token, index) => changes.has(index) && !/^\s+$/.test(token) ? <span className={`diff-${kind}`} key={index}>{token}</span> : token)}</>
}

export default function ReviewWorkspace({
  submissionId,
  onReturn,
  onNewReview,
  onRefreshList,
}: {
  submissionId: string
  onReturn: () => void
  onNewReview?: () => void
  onRefreshList?: () => void
}) {
  const [detail, setDetail] = useState<ServerDetail | null>(null)
  const [versions, setVersions] = useState<VersionInfo[]>([])
  const [audit, setAudit] = useState<AuditEvent[]>([])
  const [fileUrl, setFileUrl] = useState('')
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [editing, setEditing] = useState(false)
  const [editValue, setEditValue] = useState('')
  const [commentText, setCommentText] = useState('')
  const [decisionComment, setDecisionComment] = useState('')
  const [recheckPreview, setRecheckPreview] = useState<{ flagId: string; result: RecheckResult } | null>(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  const loadData = useCallback(async () => {
    try {
      setError('')
      const [d, v, a] = await Promise.all([
        serverApi.detail(submissionId),
        serverApi.versions(submissionId).catch(() => []),
        serverApi.audit(submissionId).catch(() => []),
      ])
      setDetail(d)
      setVersions(v)
      setAudit(a)
      setEditValue(d.submission.text || '')

      if (d.submission.content_type !== 'text') {
        try {
          const blob = await serverApi.file(submissionId, d.submission.content_type)
          setFileUrl(URL.createObjectURL(blob))
        } catch {
          // File preview unavailable
        }
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not load submission.')
    } finally {
      setLoading(false)
    }
  }, [submissionId])

  useEffect(() => {
    void loadData()
  }, [loadData])

  useEffect(() => {
    return () => {
      if (fileUrl) URL.revokeObjectURL(fileUrl)
    }
  }, [fileUrl])

  async function handleResolve(flag: ServerFlag, action: 'accept' | 'dismiss') {
    setBusy(action === 'accept' ? 'Applying suggested correction...' : 'Dismissing finding...')
    setError('')
    setNotice('')
    try {
      await serverApi.resolve(submissionId, flag.id, action, 'creator')
      await loadData()
      onRefreshList?.()
      setNotice(action === 'accept' ? 'Suggested correction applied to text.' : 'Finding dismissed.')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Resolution action failed.')
    } finally {
      setBusy('')
    }
  }

  async function handleRecheck(flag: ServerFlag) {
    setBusy('Running recheck simulation on candidate text...')
    setError('')
    try {
      const result = await serverApi.recheck(submissionId, flag.id, 'creator')
      setRecheckPreview({ flagId: flag.id, result })
      setNotice('Recheck preview computed: see results below finding.')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Recheck failed.')
    } finally {
      setBusy('')
    }
  }

  async function handleSaveEdit() {
    if (!detail) return
    setBusy('Updating draft text...')
    setError('')
    try {
      await serverApi.revise(
        submissionId,
        'text',
        editValue,
        null,
        detail.submission.title || undefined,
        detail.submission.audience || undefined,
        detail.submission.channel || undefined,
        detail.submission.context || undefined
      )
      setEditing(false)
      await loadData()
      onRefreshList?.()
      setNotice('Draft revised. Run compliance check to re-evaluate.')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to update draft.')
    } finally {
      setBusy('')
    }
  }

  async function handleAddComment() {
    if (!commentText.trim()) return
    setBusy('Adding review comment...')
    setError('')
    try {
      await serverApi.comment(submissionId, 'creator', commentText.trim())
      setCommentText('')
      await loadData()
      setNotice('Comment recorded in audit log.')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to add comment.')
    } finally {
      setBusy('')
    }
  }

  async function handleCheck() {
    setBusy('Running brand guideline & claim verification checks...')
    setError('')
    try {
      await serverApi.check(submissionId)
      await loadData()
      onRefreshList?.()
      setNotice('Compliance check completed. Submission moved to Manager Review.')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Check pipeline failed.')
    } finally {
      setBusy('')
    }
  }

  async function handleDecision(role: 'manager' | 'authorised_reviewer', decision: 'approve' | 'request_changes') {
    const actionLabel = decision === 'approve'
      ? (role === 'manager' ? 'Recording Manager approval...' : 'Granting Authorised Reviewer sign-off...')
      : 'Requesting revisions from creator...'
    setBusy(actionLabel)
    setError('')
    try {
      await serverApi.decide(submissionId, role, decision, decisionComment.trim())
      setDecisionComment('')
      await loadData()
      onRefreshList?.()
      setNotice(
        decision === 'approve'
          ? (role === 'manager' ? 'Manager approval granted. Ready for final reviewer sign-off.' : 'Final legal & brand approval granted. Publication authorized.')
          : 'Changes requested. Submission returned to creator as draft (version bumped).'
      )
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to record decision.')
    } finally {
      setBusy('')
    }
  }

  if (loading) {
    return (
      <div className="review-workspace">
        <p className="workspace-notice" role="status">Preparing results…</p>
      </div>
    )
  }

  if (!detail) {
    return (
      <div className="review-workspace">
        <p className="workspace-notice" role="alert">{error || 'Submission not found.'}</p>
        <button type="button" className="workspace-outline" onClick={onReturn}>Back to review library</button>
      </div>
    )
  }

  const sub = detail.submission
  const flags = detail.flags
  const otherChecks = flags.filter(f => ['aligned', 'supported'].includes(f.state) && f.origin !== 'error')
  const findings = flags.filter(f => !otherChecks.includes(f))
  const label = (state: string) => ({ aligned: 'Aligned', supported: 'Supported', potential_issue: 'Potential issue', unclear: 'Unclear', contradicted: 'Contradicted', insufficient_evidence: 'Insufficient evidence' } as Record<string, string>)[state] || state.replaceAll('_', ' ')
  const selectedFlag = flags.find(f => f.id === selectedId)

  // Location is free-form. A unique occurrence in the submitted text is the only
  // location we can identify safely without inventing offsets or file coordinates.
  const groupFindings = (items: ServerFlag[]) => {
    const groups: ServerFlag[][] = []
    const byPassage = new Map<string, ServerFlag[]>()
    for (const f of items) {
      const version = (f as ServerFlag & { version?: number }).version
      const text = sub.text || ''
      const first = f.passage ? text.indexOf(f.passage) : -1
      const unique = sub.content_type === 'text' && f.origin !== 'error' && f.passage.trim().toLowerCase() !== '(whole submission)' && first >= 0 && text.indexOf(f.passage, first + 1) < 0 && (version == null || version === sub.version)
      const existing = unique ? byPassage.get(f.passage) : undefined
      if (existing) existing.push(f)
      else { const group = [f]; groups.push(group); if (unique) byPassage.set(f.passage, group) }
    }
    return groups
  }

  const renderFindingCard = (f: ServerFlag, index?: number) => {
    const isError = f.origin === 'error'
    const wholeDraft = f.passage.trim().toLowerCase() === '(whole submission)'

    // Evidence resolution
    const internalList = f.internal_evidence?.length
      ? f.internal_evidence
      : f.guideline_refs?.length
      ? f.guideline_refs
      : f.guideline_ref
      ? [f.guideline_ref]
      : []

    const externalList = f.external_evidence?.length
      ? f.external_evidence
      : f.external_sources || []

    const isInsufficient =
      f.evidence_mode === 'insufficient_evidence' ||
      f.state === 'insufficient_evidence' ||
      (internalList.length === 0 && externalList.length === 0)

    // Flagged text resolution
    const span = f.flagged_span
    const surrounding = span?.surrounding_passage || f.passage || ''
    const exactOffending = span?.exact_text || ''
    let renderedFlaggedContent: React.ReactNode = surrounding
    if (exactOffending && surrounding && exactOffending !== surrounding) {
      const idx = surrounding.indexOf(exactOffending)
      if (idx >= 0) {
        renderedFlaggedContent = (
          <>
            {surrounding.slice(0, idx)}
            <mark className="offending-words-highlight">{exactOffending}</mark>
            {surrounding.slice(idx + exactOffending.length)}
          </>
        )
      }
    }

    // Diff resolution
    const diff =
      f.suggested_correction && !wholeDraft && f.passage
        ? compareText(f.passage, f.suggested_correction)
        : null

    const modeLabel =
      f.evidence_mode === 'combined'
        ? 'Combined Evidence'
        : f.evidence_mode === 'external_only'
        ? 'External Evidence'
        : f.evidence_mode === 'internal_only'
        ? 'Internal Guideline'
        : isInsufficient
        ? 'Insufficient Evidence'
        : f.finding_type === 'brand'
        ? 'Internal Guideline'
        : 'External Evidence'

    return (
      <article
        className={`evidence-first-card${isError ? ' finding-incomplete' : ''}`}
        key={f.id}
      >
        {/* Header Bar */}
        <div className="finding-header-bar">
          <div className="finding-header-left">
            {index != null && (
              <span className="finding-title-badge">Finding {index + 1}</span>
            )}
            <span className="finding-type-pill">
              {f.finding_type === 'brand' ? 'Brand Guideline' : 'Fact / Claim'}
            </span>
            <span className={`finding-state-pill ${f.state}`}>{label(f.state)}</span>
            <span className="finding-mode-pill">{modeLabel}</span>
          </div>
          <div>
            <span
              className="finding-mode-pill"
              style={{
                textTransform: 'capitalize',
                background: f.status === 'resolved' ? '#bbf7d0' : '#f1ebe8',
                color: f.status === 'resolved' ? '#166534' : '#4b5563',
              }}
            >
              Status: {f.status}
            </span>
          </div>
        </div>

        {/* Section 1: Supporting Evidence (Top) */}
        <div className="finding-section evidence-section">
          <div className="finding-section-heading">
            <span>1. Supporting Evidence</span>
            {internalList.length > 0 && externalList.length > 0 && (
              <span style={{ fontSize: '11px', color: '#6d5b56' }}>
                {internalList.length} internal · {externalList.length} external
              </span>
            )}
          </div>

          <div className="evidence-group-container">
            {/* Internal Evidence (Supabase RAG) */}
            {internalList.map((ie, i) => (
              <div className="evidence-block internal" key={`int-${i}`}>
                <div className="evidence-badge-row">
                  <span className="evidence-source-tag internal">
                    Supabase RAG Guideline
                  </span>
                  <strong>{ie.document}</strong>
                </div>

                <div className="evidence-meta-chips">
                  {ie.section && (
                    <span className="meta-chip">Section: {ie.section}</span>
                  )}
                  {ie.passage_ref && ie.passage_ref !== ie.section && (
                    <span className="meta-chip">Ref: {ie.passage_ref}</span>
                  )}
                  {ie.page_number != null && (
                    <span className="meta-chip">Page {ie.page_number}</span>
                  )}
                  {ie.chunk_id && (
                    <span className="meta-chip">Chunk #{ie.chunk_id}</span>
                  )}
                  {ie.similarity != null && (
                    <span className="meta-chip">
                      {Math.round(ie.similarity * 100)}% match
                    </span>
                  )}
                  {ie.source_reference && (
                    <span className="meta-chip">
                      {/^(https?:\/\/)/i.test(ie.source_reference) ? (
                        <a
                          href={ie.source_reference}
                          target="_blank"
                          rel="noreferrer"
                        >
                          Source link
                        </a>
                      ) : (
                        `Source: ${ie.source_reference}`
                      )}
                    </span>
                  )}
                </div>

                {/* Exact Violated Guideline Rule (Verbatim only) */}
                {ie.exact_violated_passage && (
                  <div className="verbatim-guideline-box">
                    <span className="verbatim-label">
                      Exact Violated Guideline Rule
                    </span>
                    <blockquote className="verbatim-text">
                      "{ie.exact_violated_passage}"
                    </blockquote>
                  </div>
                )}

                {/* Retrieved Guideline Chunk Context */}
                {ie.excerpt &&
                  (ie.exact_violated_passage ? (
                    <details className="retrieved-chunk-details">
                      <summary>View full retrieved guideline chunk context</summary>
                      <p>{ie.excerpt}</p>
                    </details>
                  ) : (
                    <div style={{ marginTop: '6px' }}>
                      <span
                        className="verbatim-label"
                        style={{ color: '#6d5b56' }}
                      >
                        Retrieved Guideline Passage
                      </span>
                      <p
                        style={{
                          fontSize: '13px',
                          color: '#28110f',
                          margin: '4px 0',
                          lineHeight: '1.4',
                        }}
                      >
                        {ie.excerpt}
                      </p>
                    </div>
                  ))}
              </div>
            ))}

            {/* External Evidence (Exa / Web) */}
            {externalList.map((ee, i) => (
              <div className="evidence-block external" key={`ext-${i}`}>
                <div className="evidence-badge-row">
                  <span className="evidence-source-tag external">
                    Exa / Web Evidence
                  </span>
                  <strong>{ee.title || ee.domain || 'External Reference'}</strong>
                </div>

                <div className="evidence-meta-chips">
                  {ee.domain && (
                    <span className="meta-chip">Domain: {ee.domain}</span>
                  )}
                  {ee.published_date && (
                    <span className="meta-chip">Date: {ee.published_date}</span>
                  )}
                  {ee.evidence_quality && (
                    <span className="meta-chip">Quality: {ee.evidence_quality}</span>
                  )}
                </div>

                {ee.excerpt && (
                  <p className="external-excerpt-box">"{ee.excerpt}"</p>
                )}

                {ee.url && (
                  <a
                    className="external-url-link"
                    href={ee.url}
                    target="_blank"
                    rel="noreferrer"
                  >
                    {ee.url}
                  </a>
                )}
              </div>
            ))}

            {/* Insufficient Evidence Callout */}
            {isInsufficient && (
              <div className="evidence-block insufficient">
                <div className="evidence-badge-row">
                  <span className="evidence-source-tag insufficient">
                    Evidence Gap
                  </span>
                  <strong>Insufficient Supporting Evidence</strong>
                </div>
                <p
                  style={{
                    fontSize: '13px',
                    margin: '4px 0',
                    color: '#713f12',
                    lineHeight: '1.4',
                  }}
                >
                  No internal guidelines or verified external evidence were found to
                  establish compliance or truthfulness for this statement. Human
                  verification is required.
                </p>
              </div>
            )}
          </div>
        </div>

        {/* Section 2: Flagged Content */}
        <div className="finding-section flagged-section">
          <div className="finding-section-heading">
            <span>2. Flagged Content</span>
            {f.location && <span className="meta-chip">{f.location}</span>}
          </div>

          {wholeDraft ? (
            <p style={{ fontStyle: 'italic', color: '#6d5b56', margin: '4px 0' }}>
              Applies to the whole draft submission.
            </p>
          ) : f.passage ? (
            <button
              type="button"
              className="flagged-text-display"
              aria-pressed={selectedId === f.id}
              onClick={() => setSelectedId(selectedId === f.id ? null : f.id)}
              title="Click to highlight location in draft text"
            >
              {renderedFlaggedContent}
            </button>
          ) : (
            <p style={{ fontStyle: 'italic', color: '#6d5b56', margin: '4px 0' }}>
              Exact text location unavailable.
            </p>
          )}
        </div>

        {/* Section 3: Explanation & Impact */}
        <div className="finding-section explanation-section">
          <div className="finding-section-heading">
            <span>3. Conflict Explanation &amp; Impact</span>
          </div>

          <p className="explanation-body">{f.explanation}</p>

          {f.why_it_matters && (
            <div className="why-matters-body">
              <strong>Why it matters:</strong> {f.why_it_matters}
            </div>
          )}

          {f.uncertainty_note && (
            <div className="uncertainty-box">
              <strong>Uncertainty Note:</strong> {f.uncertainty_note}
            </div>
          )}

          {f.needs_human && (
            <div style={{ marginTop: '8px' }}>
              <span className="finding-state-pill insufficient_evidence">
                Human Review Required
              </span>
            </div>
          )}
        </div>

        {/* Section 4: Suggestions & Actions */}
        <div className="finding-section suggestions-section">
          <div className="finding-section-heading">
            <span>4. Suggestions &amp; Actions</span>
          </div>

          {f.suggested_correction ? (
            <div className="suggestion-block">
              <div className="suggestion-title">Suggested Minimal Correction</div>
              <div className="suggestion-diff-box">
                {diff ? (
                  <DiffText
                    tokens={diff.after}
                    changes={diff.added}
                    kind="added"
                  />
                ) : (
                  <strong>{f.suggested_correction}</strong>
                )}
              </div>

              {f.suggestion?.change_rationale && (
                <p className="suggestion-rationale">
                  {f.suggestion.change_rationale}
                </p>
              )}

              {f.suggestion?.preserved_entities &&
                f.suggestion.preserved_entities.length > 0 && (
                  <div className="preserved-entities-row">
                    <span>Preserved entities:</span>
                    {f.suggestion.preserved_entities.map((ent, ei) => (
                      <span className="preserved-entity-chip" key={ei}>
                        {ent}
                      </span>
                    ))}
                  </div>
                )}
            </div>
          ) : (
            <p
              style={{
                fontSize: '13px',
                color: '#6d5b56',
                margin: '0 0 10px 0',
              }}
            >
              No automated correction suggested. Manual adjustment or human decision
              required.
            </p>
          )}

          {/* Action buttons */}
          <div className="action-buttons-row">
            {f.status === 'open' &&
              f.suggested_correction &&
              sub.content_type === 'text' && (
                <button
                  type="button"
                  className="btn-accept"
                  onClick={() => handleResolve(f, 'accept')}
                  disabled={!!busy}
                >
                  Accept change
                </button>
              )}

            {sub.content_type === 'text' && (
              <button
                type="button"
                className="btn-recheck"
                onClick={() => handleRecheck(f)}
                disabled={!!busy}
              >
                Preview recheck
              </button>
            )}

            {f.origin !== 'error' && f.status === 'open' && (
              <button
                type="button"
                className="btn-dismiss"
                onClick={() => handleResolve(f, 'dismiss')}
                disabled={!!busy}
              >
                Dismiss finding
              </button>
            )}

            {sub.content_type === 'text' && sub.status === 'draft' && (
              <button
                type="button"
                onClick={() => {
                  setEditValue(sub.text || '')
                  setEditing(true)
                }}
                disabled={!!busy || editing}
              >
                Edit manually
              </button>
            )}
          </div>

          {/* Inline Recheck Preview */}
          {recheckPreview && recheckPreview.flagId === f.id && (
            <div className="recheck-result-box">
              <strong>Recheck simulation results:</strong>
              <p style={{ margin: '4px 0' }}>
                Original issue resolved:{' '}
                <strong>
                  {recheckPreview.result.original_flag_gone
                    ? 'Yes (resolved)'
                    : 'No (still flagged)'}
                </strong>
              </p>
              <p style={{ margin: '4px 0' }}>
                Remaining findings: {recheckPreview.result.new_flags.length} (
                {recheckPreview.result.has_needs_human
                  ? 'Requires human review'
                  : 'No human-review flags'}
                )
              </p>
            </div>
          )}
        </div>
      </article>
    )
  }

  const renderGroup = (group: ServerFlag[]) => {
    if (group.length === 1) {
      return renderFindingCard(group[0])
    }

    const first = group[0]
    const suggestions = [
      ...new Set(
        group.map(f => f.suggested_correction).filter((v): v is string => !!v)
      ),
    ]
    const conflict = suggestions.length > 1

    return (
      <div key={first.id} style={{ marginTop: '16px' }}>
        {conflict && (
          <div
            className="workspace-notice"
            style={{
              background: '#fef3c7',
              color: '#92400e',
              marginBottom: '10px',
            }}
          >
            <strong>Multiple findings apply to this passage with different suggestions.</strong>
          </div>
        )}
        {group.map((f, i) => renderFindingCard(f, i))}
      </div>
    )
  }

  return (
    <div className="review-workspace">
      <header className="workspace-intro">
        <div>
          <span className="workspace-kicker">Review workspace</span>
          <h1>{sub.title || 'Untitled submission'}</h1>
          <p>
            Format: <strong>{sub.content_type.toUpperCase()}</strong> · Status:{' '}
            <strong style={{ color: sub.status === 'approved' ? '#6be092' : '#dec9f2' }}>
              {sub.status.replace('_', ' ').toUpperCase()}
            </strong>{' '}
            · Version <strong>v{sub.version}</strong>
          </p>
        </div>
        <div style={{ display: 'flex', gap: '8px' }}>
          {onNewReview && (
            <button type="button" className="workspace-outline" onClick={onNewReview}>
              New review
            </button>
          )}
          <button type="button" className="workspace-outline" onClick={onReturn}>
            Review library
          </button>
        </div>
      </header>

      {busy && <div className="workspace-banner" role="status">{busy}</div>}
      {notice && <p className="workspace-notice" role="status">{notice}</p>}
      {error && <div className="workspace-notice" role="alert" style={{ background: '#45181b', color: '#ffc5c8' }}>{error}</div>}

      <div className="workspace-grid">
        {/* Left column: Submitted Draft & Context */}
        <section className="panel workspace-panel">
          <h2>Your draft</h2>
          <div className="workspace-toolbar">
            <span className="format-badge">{sub.content_type.toUpperCase()}</span>
            <span className="format-badge" style={{ background: '#f5e4d5', color: '#422115' }}>
              v{sub.version}
            </span>
          </div>

          <div className="workspace-paper">
            <h3>{sub.title || 'Untitled submission'}</h3>
            {editing ? (
              <>
                <label htmlFor="workspace-edit">Edit draft text</label>
                <textarea
                  id="workspace-edit"
                  value={editValue}
                  onChange={e => setEditValue(e.target.value)}
                  rows={10}
                  disabled={!!busy}
                />
                <div className="workspace-actions">
                  <button type="button" onClick={handleSaveEdit} disabled={!!busy}>Save edit</button>
                  <button type="button" onClick={() => setEditing(false)} disabled={!!busy}>Cancel</button>
                </div>
              </>
            ) : sub.content_type === 'text' ? (
              <p className="workspace-text">
                {selectedFlag ? (
                  (() => {
                    const text = sub.text || ''
                    const span = selectedFlag.flagged_span
                    if (
                      span?.start_char != null &&
                      span?.end_char != null &&
                      span.start_char >= 0 &&
                      span.end_char <= text.length &&
                      span.start_char < span.end_char
                    ) {
                      return (
                        <>
                          {text.slice(0, span.start_char)}
                          <mark>{text.slice(span.start_char, span.end_char)}</mark>
                          {text.slice(span.end_char)}
                        </>
                      )
                    }
                    if (selectedFlag.passage && text.includes(selectedFlag.passage)) {
                      const idx = text.indexOf(selectedFlag.passage)
                      return (
                        <>
                          {text.slice(0, idx)}
                          <mark>{selectedFlag.passage}</mark>
                          {text.slice(idx + selectedFlag.passage.length)}
                        </>
                      )
                    }
                    return text || 'No text content.'
                  })()
                ) : (
                  sub.text || 'No text content.'
                )}
              </p>
            ) : fileUrl ? (
              sub.content_type === 'image' ? (
                <img className="workspace-image" src={fileUrl} alt={sub.file_name || 'Uploaded image'} />
              ) : (
                <object className="pdf-preview" data={fileUrl} type="application/pdf" aria-label="PDF preview">
                  <p>PDF preview is unavailable. <a href={fileUrl} target="_blank" rel="noreferrer">Open PDF</a>.</p>
                </object>
              )
            ) : (
              <p className="workspace-muted">File: {sub.file_name || 'Binary asset uploaded'}</p>
            )}
          </div>

          {sub.content_type === 'text' && sub.status === 'draft' && !editing && (
            <div className="workspace-actions" style={{ marginTop: '12px' }}>
              <button type="button" onClick={() => { setEditValue(sub.text || ''); setEditing(true) }}>
                Edit manually
              </button>
            </div>
          )}

          {/* Version and Audit History details */}
          <details className="workspace-panel" style={{ marginTop: '16px', background: 'transparent', padding: '8px 0' }}>
            <summary>Version &amp; Audit Trail ({audit.length} events)</summary>
            {versions.length > 0 && (
              <div style={{ marginTop: '8px' }}>
                <h4>Recorded versions</h4>
                <ul>
                  {versions.map(v => (
                    <li key={v.version}>
                      Version {v.version}: {v.flag_count} findings ({v.needs_human_count} require human attention)
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {audit.length > 0 && (
              <div style={{ marginTop: '8px' }}>
                <h4>Audit timeline</h4>
                <ul style={{ fontSize: '13px', lineHeight: '1.5' }}>
                  {audit.map((evt, idx) => (
                    <li key={idx}>
                      <span style={{ color: '#6d5b56' }}>{new Date(evt.timestamp).toLocaleTimeString()}</span> ·{' '}
                      <strong>{evt.actor || evt.actor_role}</strong> — {evt.action}: {evt.detail}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </details>
        </section>

        {/* Right column: Findings & Evidence */}
        <section className="panel workspace-panel">
          <h2>Findings &amp; evidence</h2>
          {flags.length === 0 && <p>No findings returned. This does not mean the whole draft passed.</p>}
          {flags.some(f => f.origin === 'error') && <p className="stale-label" role="status">Some checks are incomplete. Review the findings below.</p>}
          {flags.some(f => f.origin === 'fixture') && <p>Some findings come from placeholder checks.</p>}
          {groupFindings(findings).map(renderGroup)}
          {otherChecks.length > 0 && <details><summary>Other checks ({otherChecks.length})</summary><p>These results do not establish that the whole draft passed.</p>{groupFindings(otherChecks).map(renderGroup)}</details>}

          {/* Comments section */}
          <details className="local-records">
            <summary>Review comments</summary>
            <label htmlFor="comment">Add review feedback</label>
            <textarea
              id="comment"
              value={commentText}
              onChange={e => setCommentText(e.target.value)}
              rows={2}
              placeholder="Leave feedback or guidance for creators/approvers..."
              disabled={!!busy}
            />
            <button
              type="button"
              onClick={handleAddComment}
              disabled={!commentText.trim() || !!busy}
            >
              Post comment
            </button>

            {detail.comments && detail.comments.length > 0 && (
              <ul style={{ marginTop: '12px' }}>
                {detail.comments.map(c => (
                  <li key={c.id}>
                    <strong>{c.role}</strong> (v{c.version}): {c.text}
                  </li>
                ))}
              </ul>
            )}
          </details>
        </section>
      </div>

      {/* Streamlined One-Click Role Approvals in Footer */}
      <div className="workspace-footer">
        <div>
          <span>Workflow governance status: <strong>{sub.status.replace('_', ' ').toUpperCase()}</strong></span>
          {(sub.status === 'manager_review' || sub.status === 'final_approval') && <p>Reviewer roles are simulated; no sign-in is provided.</p>}
        </div>

        <div className="workspace-actions">
          {sub.status === 'draft' && (
            <button
              type="button"
              onClick={handleCheck}
              disabled={!!busy}
              style={{ background: '#dec9f2', fontWeight: 700 }}
            >
              Run Compliance Check →
            </button>
          )}

          {sub.status === 'manager_review' && (
            <div style={{ display: 'flex', gap: '8px', alignItems: 'center', flexWrap: 'wrap' }}>
              <input
                type="text"
                placeholder="Optional manager approval notes..."
                value={decisionComment}
                onChange={e => setDecisionComment(e.target.value)}
                style={{ padding: '8px 12px', borderRadius: '8px', border: '1px solid #b8aaa4' }}
                disabled={!!busy}
              />
              <button
                type="button"
                onClick={() => handleDecision('manager', 'approve')}
                disabled={!!busy}
                style={{ background: '#dec9f2', fontWeight: 700 }}
              >
                Approve as Manager
              </button>
              <button
                type="button"
                onClick={() => handleDecision('manager', 'request_changes')}
                disabled={!!busy}
              >
                Request Changes
              </button>
            </div>
          )}

          {sub.status === 'final_approval' && (
            <div style={{ display: 'flex', gap: '8px', alignItems: 'center', flexWrap: 'wrap' }}>
              <input
                type="text"
                placeholder="Optional final sign-off notes..."
                value={decisionComment}
                onChange={e => setDecisionComment(e.target.value)}
                style={{ padding: '8px 12px', borderRadius: '8px', border: '1px solid #b8aaa4' }}
                disabled={!!busy}
              />
              <button
                type="button"
                onClick={() => handleDecision('authorised_reviewer', 'approve')}
                disabled={!!busy}
                style={{ background: '#6be092', color: '#13351d', fontWeight: 700 }}
              >
                Final Sign-Off (Authorised Reviewer)
              </button>
              <button
                type="button"
                onClick={() => handleDecision('authorised_reviewer', 'request_changes')}
                disabled={!!busy}
              >
                Request Changes
              </button>
            </div>
          )}

          {sub.status === 'approved' && (
            <span
              style={{
                background: '#6be092',
                color: '#13351d',
                padding: '8px 16px',
                borderRadius: '8px',
                fontWeight: 700,
              }}
            >
              ✓ Publication Approved
            </span>
          )}

          <button type="button" onClick={onReturn}>
            Return to library
          </button>
        </div>
      </div>
    </div>
  )
}
