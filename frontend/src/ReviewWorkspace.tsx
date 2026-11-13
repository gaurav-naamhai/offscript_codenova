import { useEffect, useState } from 'react'
import { apiBase, serverApi } from './serverApi'
import type {
  AuditEvent,
  ContentType,
  DemoRole,
  RecheckResult,
  ServerDetail,
  ServerFlag,
  VersionInfo,
} from './serverApi'
import { readMetadata } from './metadataStore'
import './ReviewWorkspace.css'

type Props = {
  submissionId: string
  onReturn: () => void
  onNewReview: () => void
}

export default function ReviewWorkspace({ submissionId, onReturn, onNewReview }: Props) {
  const [detail, setDetail] = useState<ServerDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [warning, setWarning] = useState('')
  const [degraded, setDegraded] = useState<{ module: string; error: string }[]>([])

  const [role, setRole] = useState<DemoRole>('creator')
  const [filter, setFilter] = useState<'All' | 'Brand' | 'Claims'>('All')
  const [selectedFlagId, setSelectedFlagId] = useState<string | null>(null)

  // Revision state
  const [revisionText, setRevisionText] = useState('')
  const [revisionFile, setRevisionFile] = useState<File | null>(null)
  const [isEditing, setIsEditing] = useState(false)

  // Flag action states
  const [confirmFlag, setConfirmFlag] = useState<string | null>(null)
  const [preview, setPreview] = useState<{ flag: string; result: RecheckResult } | null>(null)

  // Comments and Decisions
  const [commentText, setCommentText] = useState('')
  const [decisionComment, setDecisionComment] = useState('')

  // History & versions
  const [versions, setVersions] = useState<VersionInfo[]>([])
  const [audit, setAudit] = useState<AuditEvent[]>([])
  const [historyError, setHistoryError] = useState('')

  const metadata = readMetadata(submissionId)

  async function loadDetail(id: string) {
    setLoading(true)
    setError('')
    try {
      const res = await serverApi.detail(id)
      setDetail(res)
      setRevisionText(res.submission.text || '')
      void loadHistory(id)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load submission details.')
    } finally {
      setLoading(false)
    }
  }

  async function refreshDetail() {
    if (!submissionId) return
    try {
      const res = await serverApi.detail(submissionId)
      setDetail(res)
      setRevisionText(res.submission.text || '')
      void loadHistory(submissionId)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to refresh submission details.')
    }
  }

  async function loadHistory(id: string) {
    try {
      const [v, a] = await Promise.all([serverApi.versions(id), serverApi.audit(id)])
      setVersions(v)
      setAudit(a)
      setHistoryError('')
    } catch (e) {
      setHistoryError(e instanceof Error ? e.message : 'History unavailable.')
    }
  }

  useEffect(() => {
    void loadDetail(submissionId)
  }, [submissionId])

  async function runCheck() {
    if (!detail || role !== 'creator') return
    setBusy('Running placeholder checks…')
    setError('')
    try {
      const res = await serverApi.check(submissionId)
      setDegraded(res.degraded_modules || [])
      await refreshDetail()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Check failed.')
      await refreshDetail()
    } finally {
      setBusy('')
    }
  }

  async function runAction(label: string, action: () => Promise<unknown>, onSuccess?: () => void) {
    setBusy(label)
    setError('')
    setWarning('')
    try {
      await action()
      await refreshDetail()
      onSuccess?.()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Action failed.')
      await refreshDetail()
    } finally {
      setBusy('')
    }
  }

  function occurrences(passage: string): number {
    if (!passage || !detail?.submission.text) return 0
    return detail.submission.text.split(passage).length - 1
  }

  function resolveFlag(flag: ServerFlag, action: 'accept' | 'dismiss') {
    const isText = detail?.submission.content_type === 'text'
    if (
      action === 'accept' &&
      isText &&
      flag.suggested_correction &&
      occurrences(flag.passage) > 1 &&
      confirmFlag !== flag.id
    ) {
      setConfirmFlag(flag.id)
      return
    }
    setConfirmFlag(null)
    void runAction(
      `Resolving finding (${action})…`,
      () => serverApi.resolve(submissionId, flag.id, action, role),
      () => setSelectedFlagId(null)
    )
  }

  async function previewRecheck(flag: ServerFlag) {
    setBusy('Running recheck preview…')
    setError('')
    setPreview(null)
    try {
      const result = await serverApi.recheck(submissionId, flag.id, role)
      await refreshDetail()
      setPreview({ flag: flag.id, result })
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Recheck failed.')
    } finally {
      setBusy('')
    }
  }

  function submitRevision() {
    if (!detail) return
    const type = detail.submission.content_type as ContentType
    if (type === 'text') {
      if (!revisionText.trim()) return setError('Enter revised text.')
      if (revisionText.length > 10000) return setError('Text exceeds the 10,000 character limit.')
    } else {
      if (!revisionFile) return setError(`Select a replacement ${type} file.`)
      if (type === 'image') {
        const allowed = ['image/png', 'image/jpeg', 'image/webp']
        if (!allowed.includes(revisionFile.type)) return setError('Choose a PNG, JPEG or WebP image.')
        if (revisionFile.size > 5 * 1024 * 1024) return setError('Image exceeds 5 MiB.')
      } else {
        const isPdf =
          revisionFile.type === 'application/pdf' || revisionFile.name.toLowerCase().endsWith('.pdf')
        if (!isPdf) return setError('Choose a valid PDF file.')
        if (revisionFile.size > 10 * 1024 * 1024) return setError('PDF exceeds 10 MiB.')
      }
    }

    void runAction(
      'Submitting revised draft…',
      () => serverApi.revise(submissionId, type, revisionText, revisionFile),
      () => {
        setIsEditing(false)
        setRevisionFile(null)
      }
    )
  }

  function addComment() {
    if (!commentText.trim()) return
    void runAction(
      'Adding comment…',
      () => serverApi.comment(submissionId, role, commentText.trim()),
      () => setCommentText('')
    )
  }

  function submitDecision(decision: 'approve' | 'request_changes') {
    void runAction(
      `Submitting decision (${decision})…`,
      () => serverApi.decide(submissionId, role, decision, decisionComment.trim()),
      () => setDecisionComment('')
    )
  }

  if (loading) {
    return (
      <div className="review-workspace">
        <p className="workspace-banner">
          Connecting to the server. The first request can take up to a minute…
        </p>
      </div>
    )
  }

  if (!detail) {
    return (
      <div className="review-workspace">
        <div className="validation" role="alert">
          {error || 'Submission could not be loaded.'}
        </div>
        <div className="workspace-actions" style={{ marginTop: '16px' }}>
          <button type="button" onClick={() => void loadDetail(submissionId)}>
            Retry loading
          </button>
          <button type="button" onClick={onReturn}>
            Return to library
          </button>
        </div>
      </div>
    )
  }

  const { submission, flags } = detail
  const isCreator = role === 'creator'
  const isDraft = submission.status === 'draft'
  const canCheck = isCreator && isDraft
  const canActOnFindings = isCreator && submission.status === 'manager_review'
  const canDecide =
    (role === 'manager' && submission.status === 'manager_review') ||
    (role === 'authorised_reviewer' && submission.status === 'final_approval')

  const visibleFlags = flags.filter(f => {
    if (filter === 'Brand') return f.finding_type === 'brand'
    if (filter === 'Claims') return f.finding_type === 'claim'
    return true
  })

  const hasErrorFlags = flags.some(f => f.origin === 'error')
  const fileUrl = serverApi.fileUrl(submission.id)

  return (
    <div className="review-workspace">
      <header className="workspace-intro">
        <div>
          <span className="workspace-kicker">PLACEHOLDER CHECKS — not live AI analysis</span>
          <h1>{metadata.title || 'Untitled submission'}</h1>
          <p>
            Format: <strong>{submission.content_type.toUpperCase()}</strong> · Status:{' '}
            <strong>{submission.status}</strong> · Version {submission.version}
          </p>
        </div>
        <div className="workspace-actions">
          <button type="button" className="workspace-outline" onClick={onReturn}>
            Review library
          </button>
          <button type="button" className="workspace-outline" onClick={onNewReview}>
            New review
          </button>
        </div>
      </header>

      {/* Role Simulator */}
      <div
        className="panel"
        style={{
          padding: '12px 20px',
          marginBottom: '16px',
          display: 'flex',
          alignItems: 'center',
          gap: '14px',
          flexWrap: 'wrap',
        }}
      >
        <label
          htmlFor="demo-role-select"
          style={{ fontWeight: 700, display: 'flex', alignItems: 'center', gap: '8px' }}
        >
          Demo role:
          <select
            id="demo-role-select"
            value={role}
            onChange={e => setRole(e.target.value as DemoRole)}
            style={{ padding: '6px 10px', borderRadius: '6px', font: 'inherit' }}
          >
            <option value="creator">Creator</option>
            <option value="manager">Manager</option>
            <option value="authorised_reviewer">Authorised reviewer</option>
          </select>
        </label>
        <span style={{ fontSize: '13px', color: '#6d5b56' }}>
          Role simulation only — this is not authentication.
        </span>
      </div>

      <div className="workspace-banner">
        <strong>Placeholder checks. No live AI analysis.</strong>
        <span>
          {' '}
          Submissions are sent to {apiBase}. Server data resets periodically on free-tier hosting.
        </span>
      </div>

      {busy && (
        <p className="workspace-notice" role="status" style={{ marginTop: '12px' }}>
          {busy}
        </p>
      )}
      {error && (
        <div className="validation" role="alert" style={{ marginTop: '12px' }}>
          {error}
        </div>
      )}
      {warning && (
        <div className="workspace-notice" role="status" style={{ marginTop: '12px' }}>
          {warning}
        </div>
      )}

      <div className="workspace-grid">
        {/* LEFT COLUMN: Draft Content and Revisions */}
        <section className="panel workspace-panel">
          <h2>Submission content</h2>
          <div className="workspace-toolbar">
            <span className="format-badge">{submission.content_type.toUpperCase()}</span>
            <span className="status lavender">{submission.status}</span>
          </div>

          <div className="workspace-paper">
            <h3>{metadata.title || 'Untitled submission'}</h3>
            {submission.content_type === 'text' ? (
              <p className="workspace-text">{submission.text || 'No text content.'}</p>
            ) : submission.content_type === 'image' ? (
              <div>
                <img
                  className="workspace-image"
                  src={fileUrl}
                  alt={`Submission ${submission.file_name || ''}`}
                />
                <p className="workspace-muted" style={{ marginTop: '10px' }}>
                  {submission.file_name} ·{' '}
                  <a href={fileUrl} target="_blank" rel="noreferrer">
                    Open image in new tab
                  </a>
                </p>
              </div>
            ) : (
              <div>
                <object
                  className="pdf-preview"
                  data={fileUrl}
                  type="application/pdf"
                  aria-label="Submitted PDF"
                  style={{ width: '100%', height: '400px' }}
                >
                  <p>
                    PDF preview unavailable.{' '}
                    <a href={fileUrl} target="_blank" rel="noreferrer">
                      Open PDF
                    </a>
                    .
                  </p>
                </object>
                <p className="workspace-muted" style={{ marginTop: '10px' }}>
                  {submission.file_name} ·{' '}
                  <a href={fileUrl} target="_blank" rel="noreferrer">
                    Open PDF in new tab
                  </a>{' '}
                  ·{' '}
                  <a href={fileUrl} download>
                    Download
                  </a>
                </p>
              </div>
            )}
          </div>

          {/* Local client metadata */}
          <div className="changes" style={{ marginTop: '18px' }}>
            <h3>Context &amp; audience</h3>
            <p style={{ fontSize: '14px', margin: '4px 0' }}>
              <strong>Audience:</strong> {metadata.audience || 'Not specified'}
            </p>
            <p style={{ fontSize: '14px', margin: '4px 0' }}>
              <strong>Purpose / channel:</strong> {metadata.channel || 'Not specified'}
            </p>
            {metadata.context && (
              <p style={{ fontSize: '14px', margin: '4px 0' }}>
                <strong>Additional context:</strong> {metadata.context}
              </p>
            )}
            <p style={{ fontSize: '14px', margin: '4px 0' }}>
              <strong>Guidance reference:</strong> {metadata.guidance || 'No brand guidance'}
            </p>
            <p className="workspace-muted" style={{ marginTop: '6px' }}>
              Stored in this browser only. Not sent to or processed by the server.
            </p>
          </div>

          {/* Draft Revision section for creator while in draft */}
          {isCreator && isDraft && (
            <div className="changes" style={{ marginTop: '18px' }}>
              <h3>Revise draft</h3>
              <p className="workspace-muted">
                Creator may revise while the submission is in draft status. After revision, run the
                check again.
              </p>
              {!isEditing ? (
                <button
                  type="button"
                  onClick={() => {
                    setRevisionText(submission.text || '')
                    setIsEditing(true)
                  }}
                >
                  Edit / replace content
                </button>
              ) : (
                <div style={{ marginTop: '10px' }}>
                  {submission.content_type === 'text' ? (
                    <div>
                      <label htmlFor="revised-text" style={{ fontWeight: 700, display: 'block' }}>
                        Revised text (max 10,000 chars)
                      </label>
                      <textarea
                        id="revised-text"
                        value={revisionText}
                        onChange={e => setRevisionText(e.target.value)}
                        rows={6}
                        maxLength={10000}
                        style={{ width: '100%', margin: '8px 0' }}
                      />
                      <small>{revisionText.length.toLocaleString()} / 10,000 characters</small>
                    </div>
                  ) : (
                    <div>
                      <label htmlFor="revised-file" style={{ fontWeight: 700, display: 'block' }}>
                        Replacement {submission.content_type} file
                      </label>
                      <input
                        id="revised-file"
                        type="file"
                        accept={
                          submission.content_type === 'image'
                            ? 'image/png,image/jpeg,image/webp'
                            : 'application/pdf,.pdf'
                        }
                        onChange={e => setRevisionFile(e.target.files?.[0] || null)}
                        style={{ margin: '8px 0' }}
                      />
                      <p className="workspace-muted">
                        {submission.content_type === 'image'
                          ? 'PNG, JPEG, WebP up to 5 MiB'
                          : 'PDF up to 10 MiB'}
                      </p>
                    </div>
                  )}
                  <div className="workspace-actions" style={{ marginTop: '10px' }}>
                    <button type="button" onClick={submitRevision} disabled={!!busy}>
                      Submit revision
                    </button>
                    <button type="button" onClick={() => setIsEditing(false)}>
                      Cancel
                    </button>
                  </div>
                </div>
              )}
            </div>
          )}
        </section>

        {/* RIGHT COLUMN: Findings, Actions, Decisions */}
        <section className="panel workspace-panel">
          <h2>Findings &amp; evidence</h2>

          {/* Check Trigger */}
          <div style={{ marginBottom: '16px' }}>
            <button
              type="button"
              className="primary-button"
              onClick={runCheck}
              disabled={!!busy || !canCheck}
            >
              Run placeholder checks <span aria-hidden="true">→</span>
            </button>
            {!canCheck && (
              <p className="workspace-muted" style={{ marginTop: '6px' }}>
                {!isCreator
                  ? 'Running checks requires the creator demo role.'
                  : !isDraft
                  ? 'Checks can only be run while the submission is in draft status.'
                  : ''}
              </p>
            )}
          </div>

          {/* Degraded / Error Module Notice */}
          {(degraded.length > 0 || hasErrorFlags) && (
            <div className="validation" role="alert" style={{ marginBottom: '16px' }}>
              <strong>Incomplete checks — human review required</strong>
              <p style={{ margin: '6px 0' }}>
                One or more verification modules encountered errors or degraded. This is NOT a pass.
              </p>
              {degraded.map((d, i) => (
                <p key={i}>
                  <strong>{d.module}:</strong> {d.error}
                </p>
              ))}
            </div>
          )}

          {/* Filter Tabs */}
          <div className="workspace-tabs" role="group" aria-label="Filter findings">
            {(['All', 'Brand', 'Claims'] as const).map(item => (
              <button
                type="button"
                aria-pressed={filter === item}
                className={filter === item ? 'selected' : ''}
                onClick={() => setFilter(item)}
                key={item}
              >
                {item}
              </button>
            ))}
          </div>

          {/* Findings List */}
          {flags.length === 0 ? (
            <p className="workspace-muted" style={{ marginTop: '16px' }}>
              No findings available. Placeholder checks; zero findings do not prove the content
              passed.
            </p>
          ) : visibleFlags.length === 0 ? (
            <p className="workspace-muted" style={{ marginTop: '16px' }}>
              No findings in the &ldquo;{filter}&rdquo; filter.
            </p>
          ) : (
            visibleFlags.map(flag => {
              const isOpen = selectedFlagId === flag.id
              const isFlagOpen = flag.status === 'open'
              return (
                <article className="finding" key={flag.id}>
                  <button
                    className="finding-select"
                    type="button"
                    aria-expanded={isOpen}
                    onClick={() => setSelectedFlagId(isOpen ? null : flag.id)}
                  >
                    <strong>
                      {flag.finding_type.toUpperCase()}: {flag.state.replaceAll('_', ' ')}
                    </strong>
                    <span>
                      {flag.status} ·{' '}
                      {flag.origin === 'fixture'
                        ? 'Fixture placeholder'
                        : flag.origin === 'error'
                        ? 'Incomplete check'
                        : 'Module'}
                    </span>
                  </button>

                  {isOpen && (
                    <div className="finding-detail">
                      <p>
                        <strong>Assessment:</strong> {flag.state.replaceAll('_', ' ')} ·{' '}
                        <strong>Resolution:</strong> {flag.status}
                      </p>
                      <p>
                        <strong>Origin:</strong>{' '}
                        {flag.origin === 'fixture'
                          ? 'Fixture — placeholder check'
                          : flag.origin === 'error'
                          ? 'Error — incomplete check (needs human review)'
                          : 'Module — rule applied'}
                      </p>
                      {flag.needs_human && (
                        <p style={{ color: '#a05b10', fontWeight: 700 }}>
                          Requires human reviewer evaluation
                        </p>
                      )}
                      <p>
                        <strong>Passage:</strong> &ldquo;{flag.passage}&rdquo;
                      </p>
                      <p>
                        <strong>Location:</strong> {flag.location}
                      </p>
                      <p>{flag.explanation}</p>
                      {flag.why_it_matters && (
                        <p>
                          <strong>Why it matters:</strong> {flag.why_it_matters}
                        </p>
                      )}
                      {flag.guideline_ref && (
                        <div className="source-excerpt" style={{ margin: '8px 0' }}>
                          <strong>Guideline:</strong> {flag.guideline_ref.document} (
                          {flag.guideline_ref.passage_ref})
                          <p style={{ margin: '4px 0' }}>&ldquo;{flag.guideline_ref.excerpt}&rdquo;</p>
                        </div>
                      )}
                      {flag.external_sources && flag.external_sources.length > 0 && (
                        <div className="source-excerpt" style={{ margin: '8px 0' }}>
                          <strong>External sources:</strong>
                          <ul>
                            {flag.external_sources.map((s, i) => (
                              <li key={i}>
                                <a href={s.url} target="_blank" rel="noreferrer">
                                  {s.url}
                                </a>
                                : {s.excerpt}
                              </li>
                            ))}
                          </ul>
                        </div>
                      )}
                      {flag.suggested_correction && (
                        <p>
                          <strong>Suggested correction:</strong> &ldquo;
                          {flag.suggested_correction}&rdquo;
                        </p>
                      )}

                      {/* Flag Actions */}
                      <div className="workspace-actions" style={{ marginTop: '12px' }}>
                        <button
                          type="button"
                          disabled={!!busy || !canActOnFindings || !isFlagOpen}
                          onClick={() => resolveFlag(flag, 'accept')}
                        >
                          Accept finding
                        </button>
                        <button
                          type="button"
                          disabled={!!busy || !canActOnFindings || !isFlagOpen}
                          onClick={() => resolveFlag(flag, 'dismiss')}
                        >
                          Dismiss finding
                        </button>
                        {submission.content_type === 'text' && (
                          <button
                            type="button"
                            disabled={!!busy || !canActOnFindings}
                            onClick={() => void previewRecheck(flag)}
                          >
                            Preview recheck
                          </button>
                        )}
                      </div>

                      {confirmFlag === flag.id && (
                        <div className="validation" style={{ marginTop: '10px' }}>
                          <p>
                            This passage occurs {occurrences(flag.passage)} times. The server
                            replaces the first occurrence only.
                          </p>
                          <div className="workspace-actions" style={{ marginTop: '6px' }}>
                            <button
                              type="button"
                              onClick={() => {
                                setConfirmFlag(null)
                                void runAction('Resolving finding (accept)…', () =>
                                  serverApi.resolve(submissionId, flag.id, 'accept', role)
                                )
                              }}
                            >
                              Confirm replacement
                            </button>
                            <button type="button" onClick={() => setConfirmFlag(null)}>
                              Cancel
                            </button>
                          </div>
                        </div>
                      )}

                      {preview?.flag === flag.id && (
                        <div className="source-excerpt" style={{ marginTop: '10px' }}>
                          <strong>Recheck preview only — no saved revision or approval.</strong>
                          <p style={{ margin: '4px 0' }}>
                            Original flag gone:{' '}
                            {preview.result.original_flag_gone ? 'Yes' : 'No'} · Needs human:{' '}
                            {preview.result.has_needs_human ? 'Yes' : 'No'}
                          </p>
                          <p style={{ margin: '4px 0' }}>
                            {preview.result.new_flags.length} preview findings; placeholder and
                            error results are not a pass.
                          </p>
                          {preview.result.new_flags.length > 0 && (
                            <ul>
                              {preview.result.new_flags.map(f => (
                                <li key={f.id}>
                                  {f.finding_type}: {f.state} (
                                  {f.origin === 'error'
                                    ? 'incomplete check'
                                    : f.origin === 'fixture'
                                    ? 'fixture placeholder'
                                    : f.origin}
                                  )
                                </li>
                              ))}
                            </ul>
                          )}
                        </div>
                      )}
                    </div>
                  )}
                </article>
              )
            })
          )}

          {!canActOnFindings && (
            <p className="workspace-muted" style={{ marginTop: '12px' }}>
              Finding decisions (accept / dismiss / recheck) require the creator role and
              manager-review workflow state.
            </p>
          )}

          {/* Comments & Decisions Section */}
          <div className="local-records">
            <h3>Comments</h3>
            <label htmlFor="new-comment" className="sr-only">
              Add comment
            </label>
            <textarea
              id="new-comment"
              rows={2}
              value={commentText}
              onChange={e => setCommentText(e.target.value)}
              placeholder="Add a comment to this review version…"
            />
            <button
              type="button"
              disabled={!!busy || !commentText.trim()}
              onClick={addComment}
              style={{ marginTop: '8px' }}
            >
              Add comment
            </button>
            {detail.comments.length > 0 ? (
              <ul style={{ marginTop: '12px' }}>
                {detail.comments.map(c => (
                  <li key={c.id}>
                    <strong>
                      {c.role} (v{c.version}):
                    </strong>{' '}
                    {c.text}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="workspace-muted" style={{ marginTop: '6px' }}>
                No comments yet.
              </p>
            )}

            <h3>Human decision &amp; approval</h3>
            <p className="workspace-muted">
              Manager approves during manager review; Authorised Reviewer approves during final
              approval. Role selection is simulation, not authentication.
            </p>
            <label htmlFor="decision-comment" style={{ fontWeight: 700, display: 'block' }}>
              Decision note (optional)
            </label>
            <input
              id="decision-comment"
              type="text"
              value={decisionComment}
              onChange={e => setDecisionComment(e.target.value)}
              placeholder="e.g. Approved with updated claim wording"
              style={{
                width: '100%',
                padding: '8px',
                borderRadius: '6px',
                border: '1px solid #b8aaa4',
                margin: '6px 0',
              }}
            />
            <div className="workspace-actions" style={{ marginTop: '6px' }}>
              <button
                type="button"
                disabled={!!busy || !canDecide}
                onClick={() => submitDecision('request_changes')}
              >
                Request changes
              </button>
              <button
                type="button"
                disabled={!!busy || !canDecide}
                onClick={() => submitDecision('approve')}
              >
                Approve as {role.replaceAll('_', ' ')}
              </button>
            </div>
            {detail.decisions.length > 0 ? (
              <ul style={{ marginTop: '12px' }}>
                {detail.decisions.map(d => (
                  <li key={d.id}>
                    <strong>
                      {d.role}: {d.decision} (v{d.version})
                    </strong>
                    {d.comment ? ` — ${d.comment}` : ''}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="workspace-muted" style={{ marginTop: '6px' }}>
                No decisions recorded yet.
              </p>
            )}

            {/* Versions & Audit History */}
            <h3>Versions &amp; audit history</h3>
            {historyError && (
              <p className="validation" role="alert">
                {historyError}
              </p>
            )}
            <button
              type="button"
              disabled={!!busy}
              onClick={() => void loadHistory(submissionId)}
              style={{ marginBottom: '10px' }}
            >
              Refresh history
            </button>
            {versions.length > 0 && (
              <div>
                <strong>Versions:</strong>
                <ul>
                  {versions.map(v => (
                    <li key={v.version}>
                      Version {v.version}: {v.flag_count} findings, {v.needs_human_count} need human
                      review
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {audit.length > 0 && (
              <div style={{ marginTop: '8px' }}>
                <strong>Audit log:</strong>
                <ul>
                  {audit.map((ev, i) => (
                    <li key={i}>
                      <small>{new Date(ev.timestamp).toLocaleTimeString()}</small> ·{' '}
                      <strong>{ev.actor || ev.actor_role}:</strong> {ev.action} ({ev.detail})
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        </section>
      </div>

      <div className="workspace-footer">
        <span>Submissions are backed by the live server. Data resets periodically on free tier.</span>
        <div className="workspace-actions">
          <button type="button" onClick={refreshDetail} disabled={!!busy}>
            Refresh details
          </button>
          <button type="button" onClick={onReturn}>
            Return to library
          </button>
        </div>
      </div>
    </div>
  )
}
