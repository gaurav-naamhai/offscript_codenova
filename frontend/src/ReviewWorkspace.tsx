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

  const renderGroup = (group: ServerFlag[]) => {
    const first = group[0]
    const wholeDraft = first.passage.trim().toLowerCase() === '(whole submission)'
    const incomplete = first.origin === 'error'
    const canEdit = sub.content_type === 'text' && sub.status === 'draft'
    const suggestions = [...new Set(group.map(f => f.suggested_correction).filter((v): v is string => !!v))]
    const conflict = suggestions.length > 1
    const canHighlight = (f: ServerFlag) => f.state !== 'unclear' && f.state !== 'insufficient_evidence' && !(f as ServerFlag & { uncertainty_note?: string | null }).uncertainty_note
    const sharedDiff = suggestions.length === 1 && !!first.passage && !wholeDraft && group.every(canHighlight) ? compareText(first.passage, suggestions[0]) : null
    const explain = (f: ServerFlag) => {
      const extra = f as ServerFlag & { uncertainty_note?: string | null; guideline_refs?: NonNullable<ServerFlag['guideline_ref']>[] }
      const refs = extra.guideline_refs?.length ? extra.guideline_refs : f.guideline_ref ? [f.guideline_ref] : []
      return <><p>{f.explanation}</p><p>{f.why_it_matters}</p>{refs.length ? refs.map((ref, i) => <p className="source-excerpt" key={i}><strong>{ref.document}</strong> · {ref.passage_ref}<br/>{ref.excerpt}{ref.source_reference && <> · {/^(https?:\/\/)/i.test(ref.source_reference) ? <a href={ref.source_reference} target="_blank" rel="noreferrer">Source</a> : ref.source_reference}</>}</p>) : <p>No guideline reference returned.</p>}{f.external_sources?.length ? f.external_sources.map((source, i) => <p className="source-excerpt" key={i}><a href={source.url} target="_blank" rel="noreferrer">{source.url}</a>: {source.excerpt}</p>) : <p>No external evidence returned.</p>}</>
    }
    const actions = (f: ServerFlag, index: number) => <div className="preview-finding" key={f.id}><strong>Finding {index + 1} · {f.finding_type === 'brand' ? 'Brand' : 'Claim'} · {label(f.state)} · {f.status}</strong>{explain(f)}{f.origin !== 'error' && f.status === 'open' && <div className="finding-secondary"><button type="button" onClick={() => handleResolve(f, 'dismiss')} disabled={!!busy}>Dismiss finding {index + 1}</button>{sub.content_type === 'text' && <button type="button" onClick={() => handleRecheck(f)} disabled={!!busy}>Preview recheck</button>}</div>}{recheckPreview && recheckPreview.flagId === f.id && <div className="source-excerpt"><strong>Recheck preview</strong><p>Original issue resolved: {recheckPreview.result.original_flag_gone ? 'Yes' : 'No'}</p><p>Remaining findings: {recheckPreview.result.new_flags.length} ({recheckPreview.result.has_needs_human ? 'Requires human review' : 'No human-review flag'})</p></div>}</div>
    const accept = (f: ServerFlag, index: number, numbered: boolean) => f.status === 'open' && f.suggested_correction && sub.content_type === 'text' ? <button type="button" onClick={() => handleResolve(f, 'accept')} disabled={!!busy} key={f.id}>{numbered ? `Accept for finding ${index + 1} (${f.finding_type === 'brand' ? 'Brand' : 'Claim'})` : 'Accept change'}</button> : null
    return <article className={`finding${incomplete ? ' finding-incomplete' : ''}`} key={first.id}><div className="finding-detail">
      {incomplete && <strong>Review incomplete</strong>}
      {group.some(f => f.origin === 'fixture') && <p className="finding-note">Placeholder check</p>}
      {group.some(f => f.state === 'insufficient_evidence') && <p className="finding-note">Needs supporting evidence.</p>}
      {group.map(f => <div key={f.id}>{(f as ServerFlag & { uncertainty_note?: string | null }).uncertainty_note && <p className="finding-note"><strong>Uncertainty:</strong> {(f as ServerFlag & { uncertainty_note?: string | null }).uncertainty_note}</p>}{f.needs_human && <p className="finding-note">Human review required.</p>}</div>)}
      {!incomplete && <>{wholeDraft ? <p>Applies to the whole draft</p> : first.passage ? <div className="finding-copy"><strong>Text to review</strong><button className="finding-passage" type="button" aria-pressed={group.some(f => f.id === selectedId)} onClick={() => setSelectedId(group.some(f => f.id === selectedId) ? null : first.id)}>{sharedDiff ? <DiffText tokens={sharedDiff.before} changes={sharedDiff.removed} kind="removed"/> : first.passage}</button></div> : <p>Exact text location unavailable.</p>}
      {conflict ? <><p><strong>Suggestions disagree</strong></p><details className="finding-source"><summary>Review options</summary>{suggestions.map((suggestion, n) => { const related = group.filter(f => f.suggested_correction === suggestion); const diff = !wholeDraft && related.every(canHighlight) ? compareText(first.passage, suggestion) : null; return <div className="preview-option" key={suggestion}><strong>Option {n + 1}</strong><p>{diff ? <DiffText tokens={diff.after} changes={diff.added} kind="added"/> : suggestion}</p>{related.map(f => <div key={f.id}><details><summary>{f.finding_type === 'brand' ? 'Brand' : 'Claim'} source &amp; explanation</summary>{explain(f)}</details><div className="workspace-actions finding-actions">{accept(f, group.indexOf(f), related.length > 1)}</div></div>)}</div>})}</details></> : suggestions.length === 1 && <div className="finding-copy"><strong>Suggested correction</strong><p>{sharedDiff ? <DiffText tokens={sharedDiff.after} changes={sharedDiff.added} kind="added"/> : suggestions[0]}</p>{sub.content_type !== 'text' && <p className="finding-note">This suggestion does not edit the uploaded file.</p>}</div>}</>}
      <details className="finding-source"><summary>Sources &amp; details</summary>{group.map(actions)}</details>
      {!incomplete && !conflict && <div className="workspace-actions finding-actions">{group.length > 1 && group.some(f => f.status === 'open' && f.suggested_correction) && sub.content_type === 'text' ? <details className="preview-accept"><summary>Accept change</summary><p>Choose one finding to resolve.</p><div className="workspace-actions">{group.map((f,i) => accept(f,i,true))}</div></details> : group.map((f,i) => accept(f,i,false))}{sub.content_type === 'text' && <button type="button" onClick={() => { setEditValue(sub.text || ''); setEditing(true) }} disabled={!!busy || !canEdit || editing}>Edit manually</button>}</div>}
      {!incomplete && conflict && sub.content_type === 'text' && <div className="workspace-actions finding-actions"><button type="button" onClick={() => { setEditValue(sub.text || ''); setEditing(true) }} disabled={!!busy || !canEdit || editing}>Edit manually</button></div>}
      {sub.content_type === 'text' && !canEdit && !incomplete && <p className="finding-note">Manual editing is available when the submission is a draft.</p>}
    </div></article>
  }

  return (
    <div className="review-workspace">
      <header className="workspace-intro">
        <div>
          <span className="workspace-kicker">COMPLIANCE REVIEW WORKSPACE</span>
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
                {selectedFlag && selectedFlag.passage && sub.text?.includes(selectedFlag.passage) ? (
                  <>
                    {sub.text.slice(0, sub.text.indexOf(selectedFlag.passage))}
                    <mark>{selectedFlag.passage}</mark>
                    {sub.text.slice(sub.text.indexOf(selectedFlag.passage) + selectedFlag.passage.length)}
                  </>
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
