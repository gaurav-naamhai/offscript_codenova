import { useCallback, useEffect, useRef, useState } from 'react'
import type { ChangeEvent } from 'react'
import { serverApi } from './serverApi'
import type {
  AuditEvent,
  AuthUser,
  RecheckResult,
  ServerDetail,
  ServerFlag,
  SubmissionStatus,
  VersionInfo,
} from './serverApi'
import { readinessExplanation, readinessLabel, reviewReadiness } from './reviewReadiness'
import './ReviewWorkspace.css'

type ReviewLens = 'brand' | 'claim' | 'all'

function compareText(original: string, correction: string) {
  const tokenize = (text: string) => text.match(/[\p{L}\p{M}\p{N}]+|[^\p{L}\p{M}\p{N}\s]|\s+/gu) || []
  const before = tokenize(original), after = tokenize(correction)
  const removed = new Set<number>(), added = new Set<number>()
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
  user,
  onSwitchAccount,
  onReturn,
  onNewReview,
  onRefreshList,
}: {
  submissionId: string
  user: AuthUser
  onSwitchAccount: () => void
  onReturn: () => void
  onNewReview?: () => void
  onRefreshList?: () => void
}) {
  const [detail, setDetail] = useState<ServerDetail | null>(null)
  const [versions, setVersions] = useState<VersionInfo[]>([])
  const [audit, setAudit] = useState<AuditEvent[]>([])
  const [viewingVersion, setViewingVersion] = useState<number | null>(null)
  const [fileUrl, setFileUrl] = useState('')
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [lens, setLens] = useState<ReviewLens>('brand')
  const [editing, setEditing] = useState(false)
  const [editValue, setEditValue] = useState('')
  const [replacementFile, setReplacementFile] = useState<File | null>(null)
  const replaceInputRef = useRef<HTMLInputElement>(null)
  const [commentText, setCommentText] = useState('')
  const [decisionComment, setDecisionComment] = useState('')
  const [overrideChecked, setOverrideChecked] = useState(false)
  const [overrideReason, setOverrideReason] = useState('')
  const [recheckPreview, setRecheckPreview] = useState<{ flagId: string; result: RecheckResult } | null>(null)
  const [liveStatus, setLiveStatus] = useState<SubmissionStatus | null>(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState('')
  const checkInFlight = useRef(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  const loadData = useCallback(async (targetVersion?: number | null) => {
    try {
      setError('')
      const vParam = targetVersion != null ? targetVersion : undefined
      const [d, v, a] = await Promise.all([
        serverApi.detail(submissionId, vParam),
        serverApi.versions(submissionId).catch(() => []),
        serverApi.audit(submissionId).catch(() => []),
      ])
      setDetail(d)
      setVersions(v)
      setAudit(a)
      setEditValue(d.version_snapshot?.text ?? d.submission.text ?? '')

      if (d.submission.content_type !== 'text') {
        try {
          const blob = await serverApi.file(submissionId, d.submission.content_type, vParam)
          setFileUrl(prev => {
            if (prev) URL.revokeObjectURL(prev)
            return URL.createObjectURL(blob)
          })
        } catch {
          setFileUrl(prev => {
            if (prev) URL.revokeObjectURL(prev)
            return ''
          })
        }
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not load submission.')
    } finally {
      setLoading(false)
    }
  }, [submissionId])

  useEffect(() => {
    setViewingVersion(null)
    setLoading(true)
    void loadData(null)
  }, [loadData])

  useEffect(() => {
    return () => {
      if (fileUrl) URL.revokeObjectURL(fileUrl)
    }
  }, [fileUrl])

  // Automatic status polling while background AI review runs
  const currentSubStatus = detail?.submission.status
  useEffect(() => {
    if (currentSubStatus !== 'ai_review') {
      const clearTimer = window.setTimeout(() => setLiveStatus(null), 0)
      return () => window.clearTimeout(clearTimer)
    }
    let active = true
    const poll = () => {
      void serverApi
        .status(submissionId)
        .then(st => {
          if (!active) return
          setLiveStatus(st)
          if (st.status !== 'ai_review') {
            void loadData(null)
            onRefreshList?.()
          }
        })
        .catch(() => {
          /* ignore transient poll error */
        })
    }
    poll()
    const interval = window.setInterval(poll, 1400)
    return () => {
      active = false
      window.clearInterval(interval)
    }
  }, [currentSubStatus, submissionId, loadData, onRefreshList])

  async function handleSelectVersion(v: number) {
    const next = detail && v === detail.submission.version ? null : v
    setViewingVersion(next)
    setSelectedId(null)
    await loadData(next)
  }

  async function handleResolve(flag: ServerFlag, action: 'accept' | 'dismiss') {
    setBusy(action === 'accept' ? 'Applying suggested correction…' : 'Dismissing finding…')
    setError('')
    setNotice('')
    try {
      await serverApi.resolve(submissionId, flag.id, action, user.role)
      setViewingVersion(null)
      await loadData(null)
      onRefreshList?.()
      setNotice(action === 'accept' ? 'Suggested correction applied.' : 'Finding dismissed.')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Resolution action failed.')
    } finally {
      setBusy('')
    }
  }

  async function handleRecheck(flag: ServerFlag) {
    setBusy('Simulating recheck on candidate text…')
    setError('')
    try {
      const result = await serverApi.recheck(submissionId, flag.id, user.role)
      setRecheckPreview({ flagId: flag.id, result })
      setNotice('Recheck preview ready below this finding.')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Recheck failed.')
    } finally {
      setBusy('')
    }
  }

  async function handleSaveEdit() {
    if (!detail) return
    setBusy('Saving revised draft…')
    setError('')
    try {
      const updated = await serverApi.revise(
        submissionId,
        'text',
        editValue,
        null,
        detail.submission.title || undefined,
        detail.submission.audience || undefined,
        detail.submission.channel || undefined,
        detail.submission.context || undefined,
        true
      )
      setEditing(false)
      setViewingVersion(null)
      await loadData(null)
      onRefreshList?.()
      setNotice(
        updated.version > detail.submission.version
          ? `Saved as v${updated.version} (v${detail.submission.version} preserved). Run Compliance Check to re-approve.`
          : 'Draft updated. Run Compliance Check to verify.'
      )
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to update draft.')
    } finally {
      setBusy('')
    }
  }

  function handleReplacementSelect(e: ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0] || null
    setReplacementFile(f)
    e.target.value = ''
  }

  async function handleUploadReplacement() {
    if (!detail || !replacementFile) return
    setBusy(`Uploading replacement ${detail.submission.content_type.toUpperCase()}…`)
    setError('')
    try {
      const updated = await serverApi.revise(
        submissionId,
        detail.submission.content_type as 'image' | 'pdf',
        '',
        replacementFile,
        detail.submission.title || undefined,
        detail.submission.audience || undefined,
        detail.submission.channel || undefined,
        detail.submission.context || undefined,
        true
      )
      setReplacementFile(null)
      setViewingVersion(null)
      await loadData(null)
      onRefreshList?.()
      setNotice(
        `Uploaded ${replacementFile.name} on v${updated.version}. Run Compliance Check to evaluate the updated asset.`
      )
    } catch (err) {
      setError(err instanceof Error ? err.message : 'File replacement failed.')
    } finally {
      setBusy('')
    }
  }

  async function handleAddComment() {
    if (!commentText.trim()) return
    setBusy('Posting review comment…')
    setError('')
    try {
      await serverApi.comment(submissionId, user.role, commentText.trim())
      setCommentText('')
      await loadData(viewingVersion)
      setNotice('Comment recorded.')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to add comment.')
    } finally {
      setBusy('')
    }
  }

  async function handleCheck(retry = false) {
    if (checkInFlight.current) return
    checkInFlight.current = true
    setBusy(retry ? 'Retrying compliance review…' : 'Starting compliance review…')
    setError('')
    setNotice('')
    try {
      if (retry) {
        await serverApi.retryCheck(submissionId, true)
      } else {
        await serverApi.checkAsync(submissionId)
      }
      setViewingVersion(null)
      await loadData(null)
      onRefreshList?.()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not start compliance check.')
    } finally {
      checkInFlight.current = false
      setBusy('')
    }
  }

  async function handleDecision(decision: 'approve' | 'request_changes') {
    if (!detail) return
    const role = user.role
    if (role !== 'manager' && role !== 'authorised_reviewer') return
    setBusy(decision === 'approve' ? 'Recording approval…' : 'Returning draft for changes…')
    setError('')
    try {
      await serverApi.decide(
        submissionId,
        role,
        decision,
        decisionComment.trim(),
        overrideChecked,
        overrideReason.trim()
      )
      setDecisionComment('')
      setOverrideChecked(false)
      setOverrideReason('')
      setViewingVersion(null)
      await loadData(null)
      onRefreshList?.()
      setNotice(
        decision === 'approve'
          ? role === 'manager'
            ? 'Manager approval recorded. Ready for Authorised Reviewer sign-off.'
            : 'Final approval granted. Content cleared for publication.'
          : 'Changes requested. Returned to Creator as draft with a new version.'
      )
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to record decision.')
    } finally {
      setBusy('')
    }
  }

  async function handleExportCertificate() {
    try {
      const cert = await serverApi.certificate(submissionId)
      const blob = new Blob([JSON.stringify(cert, null, 2)], { type: 'application/json' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `${cert.certificate_id}.json`
      a.click()
      URL.revokeObjectURL(url)
      setNotice(`Exported compliance certificate ${cert.certificate_id}.`)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not export certificate.')
    }
  }

  if (loading) {
    return (
      <div className="review-workspace">
        <p className="workspace-notice" role="status">Loading review workspace…</p>
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
  const activeSnapshot = detail.version_snapshot
  const isHistoricalView = viewingVersion != null && viewingVersion !== sub.version
  const displayedText = (activeSnapshot?.text ?? sub.text) || ''
  const displayedFileName = activeSnapshot?.file_name ?? sub.file_name
  const flags = detail.flags
  const recurringHints = detail.recurring_hints || []
  const blockingCount = detail.unresolved_blocking_count ?? flags.filter(f => f.status === 'open' && (f.origin === 'error' || ['potential_issue', 'contradicted', 'insufficient_evidence', 'unclear'].includes(f.state))).length
  const hasBlockingError = flags.some(f => f.status === 'open' && f.origin === 'error')
  const currentLiveStatus = liveStatus?.version === sub.version ? liveStatus : null
  const displayStatus = isHistoricalView ? activeSnapshot?.status || 'draft' : currentLiveStatus?.status || sub.status
  const displayStage = isHistoricalView ? (displayStatus === 'draft' ? null : 'completed') : currentLiveStatus?.processing_stage || sub.processing_stage
  const readiness = hasBlockingError && displayStatus !== 'draft' && displayStatus !== 'ai_review'
    ? 'review_incomplete'
    : reviewReadiness(detail.readiness_status, displayStatus, displayStage)
  const overrideDecisions = detail.decisions.filter(d => d.version === (isHistoricalView ? viewingVersion : sub.version) && d.decision === 'approve' && d.override_unresolved)
  const managerOverrides = overrideDecisions.filter(d => d.role === 'manager')
  const openRisks = flags.filter(f => f.status === 'open' && (f.origin === 'error' || ['potential_issue', 'contradicted', 'insufficient_evidence', 'unclear'].includes(f.state)))

  const otherChecks = flags.filter(f => ['aligned', 'supported'].includes(f.state) && f.origin !== 'error')
  const actionableFindings = flags.filter(f => !otherChecks.includes(f))
  const brandFindings = actionableFindings.filter(f => f.finding_type === 'brand')
  const claimFindings = actionableFindings.filter(f => f.finding_type === 'claim')
  const lensFindings =
    lens === 'brand' ? brandFindings : lens === 'claim' ? claimFindings : actionableFindings

  const label = (state: string) =>
    ({
      aligned: 'Aligned',
      supported: 'Supported',
      potential_issue: 'Potential issue',
      unclear: 'Unclear',
      contradicted: 'Contradicted',
      insufficient_evidence: 'Insufficient evidence',
    } as Record<string, string>)[state] || state.replaceAll('_', ' ')

  const selectedFlag = flags.find(f => f.id === selectedId)
  const latestRequestChanges = [...detail.decisions].reverse().find(d => d.decision === 'request_changes')
  const stage = liveStatus?.processing_stage || sub.processing_stage || 'extracting'
  const progressPct = liveStatus?.progress_pct ?? (sub.status === 'ai_review' ? 35 : 100)
  const stageOrder = ['extracting', 'retrieving_guidelines', 'verifying_and_assessing', 'synthesizing']
  const currentStageIdx =
    stage === 'understanding_content'
      ? 1
      : stageOrder.indexOf(stage) >= 0
      ? stageOrder.indexOf(stage)
      : 0

  const renderFindingCard = (f: ServerFlag, index?: number) => {
    const isError = f.origin === 'error'
    const wholeDraft = f.passage.trim().toLowerCase() === '(whole submission)'
    const internalList = f.internal_evidence?.length
      ? f.internal_evidence
      : f.guideline_refs?.length
      ? f.guideline_refs
      : f.guideline_ref
      ? [f.guideline_ref]
      : []
    const externalList = f.external_evidence?.length ? f.external_evidence : f.external_sources || []
    const isInsufficient =
      f.evidence_mode === 'insufficient_evidence' ||
      f.state === 'insufficient_evidence' ||
      (internalList.length === 0 && externalList.length === 0)

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

    const diff =
      f.suggested_correction && !wholeDraft && f.passage
        ? compareText(f.passage, f.suggested_correction)
        : null

    const modeLabel =
      f.explanation.startsWith('General visual/accessibility observation')
        ? 'Human visual review'
        : f.evidence_mode === 'combined'
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
      <article className={`evidence-first-card stagger-card${isError ? ' finding-incomplete' : ''}`} key={f.id}>
        <div className="finding-header-bar">
          <div className="finding-header-left">
            {index != null && <span className="finding-title-badge">Finding {index + 1}</span>}
            <span className="finding-type-pill">{f.explanation.startsWith('General visual/accessibility observation') ? 'Visual / accessibility observation' : f.finding_type === 'brand' ? 'Brand Guideline' : 'External Fact / Claim'}</span>
            <span className={`finding-state-pill ${f.state}`}>{label(f.state)}</span>
            <span className="finding-mode-pill">{modeLabel}</span>
          </div>
          <span
            className="finding-mode-pill"
            style={{
              textTransform: 'capitalize',
              background: f.status !== 'open' ? '#bbf7d0' : '#f1ebe8',
              color: f.status !== 'open' ? '#166534' : '#4b5563',
            }}
          >
            Status: {f.status}
          </span>
        </div>

        {/* 1. Supporting Evidence */}
        <div className="finding-section evidence-section">
          <div className="finding-section-heading">
            <span>1. Supporting Evidence</span>
          </div>
          <div className="evidence-group-container">
            {internalList.map((ie, i) => (
              <div className="evidence-block internal" key={`int-${i}`}>
                <div className="evidence-badge-row">
                  <span className="evidence-source-tag internal">
                    {ie.match_type === 'approved_fact' ? 'Approved Brand Fact' : 'Brand RAG Guideline'}
                  </span>
                  <strong>{ie.document}</strong>
                </div>
                <div className="evidence-meta-chips">
                  {ie.section && <span className="meta-chip">Section: {ie.section}</span>}
                  {ie.page_number != null && <span className="meta-chip">Page {ie.page_number}</span>}
                  {ie.similarity != null && <span className="meta-chip">{Math.round(ie.similarity * 100)}% match</span>}
                  {ie.matched_terms && ie.matched_terms.length > 0 && (
                    <span className="meta-chip">Matched: {ie.matched_terms.slice(0, 3).join(', ')}</span>
                  )}
                </div>
                {ie.exact_violated_passage && (
                  <div className="verbatim-guideline-box">
                    <span className="verbatim-label">Exact Cited Rule</span>
                    <blockquote className="verbatim-text">"{ie.exact_violated_passage}"</blockquote>
                  </div>
                )}
                {ie.excerpt && (
                  <details className="retrieved-chunk-details" open={!ie.exact_violated_passage}>
                    <summary>View retrieved guideline passage</summary>
                    <p>{ie.excerpt}</p>
                  </details>
                )}
              </div>
            ))}

            {externalList.map((ee, i) => (
              <div className="evidence-block external" key={`ext-${i}`}>
                <div className="evidence-badge-row">
                  <span className="evidence-source-tag external">External Web Evidence</span>
                  <strong>{ee.title || ee.domain || 'External Reference'}</strong>
                </div>
                <div className="evidence-meta-chips">
                  {ee.domain && <span className="meta-chip">{ee.domain}</span>}
                  {ee.published_date && <span className="meta-chip">Published: {ee.published_date}</span>}
                  {ee.evidence_quality && <span className="meta-chip">Quality: {ee.evidence_quality}</span>}
                </div>
                {ee.excerpt && <p className="external-excerpt-box">"{ee.excerpt}"</p>}
                {ee.url && (
                  <a className="external-url-link" href={ee.url} target="_blank" rel="noreferrer">
                    {ee.url}
                  </a>
                )}
              </div>
            ))}

            {isInsufficient && (
              <div className="evidence-block insufficient">
                <div className="evidence-badge-row">
                  <span className="evidence-source-tag insufficient">Evidence Gap</span>
                  <strong>Human Verification Needed</strong>
                </div>
                <p style={{ fontSize: '13px', margin: '4px 0', color: '#713f12' }}>
                  No verified internal fact or relevant external source was sufficient to resolve this item automatically.
                </p>
              </div>
            )}
          </div>
        </div>

        {/* 2. Flagged Content */}
        <div className="finding-section flagged-section">
          <div className="finding-section-heading">
            <span>2. Flagged Content</span>
            {f.location && <span className="meta-chip">{f.location}</span>}
          </div>
          {wholeDraft ? (
            <p style={{ fontStyle: 'italic', color: '#6d5b56', margin: '4px 0' }}>Applies to the full submission.</p>
          ) : f.passage ? (
            <button
              type="button"
              className="flagged-text-display"
              aria-pressed={selectedId === f.id}
              onClick={() => setSelectedId(selectedId === f.id ? null : f.id)}
              title="Highlight location in draft"
            >
              {renderedFlaggedContent}
            </button>
          ) : (
            <p style={{ fontStyle: 'italic', color: '#6d5b56', margin: '4px 0' }}>Location unavailable.</p>
          )}
        </div>

        {/* 3. Conflict Explanation & Impact */}
        <div className="finding-section explanation-section">
          <div className="finding-section-heading">
            <span>3. Why Flagged &amp; Impact</span>
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
        </div>

        {/* 4. Suggestions & Actions */}
        <div className="finding-section suggestions-section">
          <div className="finding-section-heading">
            <span>4. Suggested Fix &amp; Actions</span>
          </div>
          {f.suggested_correction ? (
            <div className="suggestion-block">
              <div className="suggestion-title">Minimal Intent-Preserving Edit</div>
              <div className="suggestion-diff-box">
                {diff ? <DiffText tokens={diff.after} changes={diff.added} kind="added" /> : <strong>{f.suggested_correction}</strong>}
              </div>
              {f.suggestion?.change_rationale && <p className="suggestion-rationale">{f.suggestion.change_rationale}</p>}
              {f.suggestion?.preserved_entities && f.suggestion.preserved_entities.length > 0 && (
                <div className="preserved-entities-row">
                  <span>Preserved:</span>
                  {f.suggestion.preserved_entities.map((ent, ei) => (
                    <span className="preserved-entity-chip" key={ei}>{ent}</span>
                  ))}
                </div>
              )}
            </div>
          ) : (
            <p style={{ fontSize: '13px', color: '#6d5b56', margin: '0 0 10px 0' }}>
              No automated rewrite generated — human review or manual edit is safest here.
            </p>
          )}

          {!isHistoricalView && (user.role === 'creator' || user.role === 'manager') && (
            <div className="action-buttons-row">
              {f.status === 'open' && f.suggested_correction && sub.content_type === 'text' && (
                <button type="button" className="btn-accept" onClick={() => handleResolve(f, 'accept')} disabled={!!busy}>
                  Accept change
                </button>
              )}
              {sub.content_type === 'text' && (
                <button type="button" className="btn-recheck" onClick={() => handleRecheck(f)} disabled={!!busy}>
                  Preview recheck
                </button>
              )}
              {f.origin !== 'error' && f.status === 'open' && (
                <button type="button" className="btn-dismiss" onClick={() => handleResolve(f, 'dismiss')} disabled={!!busy}>
                  Dismiss finding
                </button>
              )}
              {sub.content_type === 'text' && (
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
          )}

          {recheckPreview && recheckPreview.flagId === f.id && (
            <div className="recheck-result-box">
              <strong>Recheck preview:</strong> Original issue resolved:{' '}
              <strong>{recheckPreview.result.original_flag_gone ? 'Yes' : 'No'}</strong> · Remaining findings:{' '}
              {recheckPreview.result.new_flags.length}
            </div>
          )}
        </div>
      </article>
    )
  }

  return (
    <div className="review-workspace">
      <p className="judge-note">
        ★ For the judges: &#123; Review the current version's status and findings, switch between Brand Guidelines and External Verification, then revise or make a role-authorised decision. &#125;
      </p>
      <header className="workspace-intro">
        <div>
          <span className="workspace-kicker">{sub.brand_name || user.brand_name} Review</span>
          <h1>{sub.title || 'Untitled submission'}</h1>
          <p>
            Format: <strong>{sub.content_type.toUpperCase()}</strong> · Status:{' '}
            <strong style={{ color: readiness.startsWith('approved') ? '#6be092' : '#dec9f2' }}>
              {readinessLabel(readiness)}
            </strong>{' '}
            · Current <strong>v{sub.version}</strong>
            {isHistoricalView && ` (Viewing archived v${viewingVersion})`}
          </p>
        </div>
        <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
          {!isHistoricalView && readiness.startsWith('approved') && (
            <button type="button" className="workspace-outline" onClick={() => void handleExportCertificate()}>
              Export certificate
            </button>
          )}
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

      <div className="readiness-strip" role="status">
        <div className="readiness-stat">
          <div className="readiness-stat-label">
            <span>Review status</span>
            <small>{readinessExplanation(readiness)}</small>
          </div>
          <strong style={{ color: readiness.startsWith('approved') ? '#166534' : '#78350f' }}>
            {readinessLabel(readiness)}
          </strong>
        </div>
        <div className="readiness-stat">
          <div className="readiness-stat-label">
            <span>Confidence</span>
            <small>Heuristic scores are not a calibrated probability of correctness.</small>
          </div>
          <strong>Unavailable</strong>
        </div>
      </div>
      {!isHistoricalView && sub.status === 'final_approval' && managerOverrides.length > 0 && (
        <div className="workspace-notice" role="note">
          <strong>Manager approved with an override</strong>
          {managerOverrides.map(d => <p key={d.id}>Reason: {d.override_reason || 'No reason recorded.'}</p>)}
          <strong>Remaining unresolved risks ({openRisks.length})</strong>
          {openRisks.length > 0 ? (
            <ul>{openRisks.map(f => <li key={f.id}>{f.passage && f.passage !== '(whole submission)' ? f.passage : 'Applies to the whole draft'} — {f.explanation}</li>)}</ul>
          ) : <p>No open blocking findings remain on this version.</p>}
          {openRisks.length > 0 && <p>The Final Reviewer must provide their own override justification to approve these risks.</p>}
        </div>
      )}
      {readiness === 'approved_with_override' && overrideDecisions.length > 0 && (
        <div className="workspace-notice" role="status">
          Approved with override. Remaining risks require review. Reason: {overrideDecisions.map(d => d.override_reason || d.comment).filter(Boolean).join('; ')}
        </div>
      )}

      {/* Live Async Processing Stepper */}
      {displayStatus === 'ai_review' && (
        <div className="processing-card" role="status">
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '12px' }}>
            <strong style={{ color: '#28110f' }}>Reviewing {sub.content_type.toUpperCase()} against {sub.brand_name || user.brand_name}…</strong>
            <span className="meta-chip">{progressPct}%</span>
          </div>
          <div className="processing-progress-track">
            <div className="processing-progress-fill" style={{ width: `${progressPct}%` }} />
          </div>
          <div className="stage-stepper">
            {[
              { key: 'extracting', label: '1. Extract content' },
              { key: 'retrieving_guidelines', label: '2. Brand RAG' },
              { key: 'verifying_and_assessing', label: '3. Verify & assess' },
              { key: 'synthesizing', label: '4. Build flags' },
            ].map((step, idx) => (
              <div
                key={step.key}
                className={`stage-step ${idx < currentStageIdx ? 'done' : idx === currentStageIdx ? 'active' : ''}`}
              >
                <span className="stage-dot" />
                <span>{step.label}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Failed processing safe retry */}
      {sub.processing_stage === 'failed' && (
        <div className="workspace-notice" role="alert" style={{ background: '#45181b', color: '#ffc5c8', display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '12px' }}>
          <span>Processing failed safely: {sub.processing_error || 'Provider timeout or error.'}</span>
          {(user.role === 'creator' || user.role === 'manager') && (
            <button type="button" className="btn-accept" onClick={() => void handleCheck(true)}>
              Retry check
            </button>
          )}
        </div>
      )}

      {/* Changes Requested Banner */}
      {sub.status === 'draft' && latestRequestChanges && (
        <div className="workspace-notice" style={{ background: '#fef3c7', color: '#78350f', marginBottom: '14px' }}>
          <strong>Changes requested by {latestRequestChanges.role.replace('_', ' ')}:</strong>{' '}
          {latestRequestChanges.comment || 'Please address the flagged findings and resubmit for compliance check.'}
        </div>
      )}

      {busy && <div className="workspace-banner" role="status">{busy}</div>}
      {notice && <p className="workspace-notice" role="status">{notice}</p>}
      {error && <div className="workspace-notice" role="alert" style={{ background: '#45181b', color: '#ffc5c8' }}>{error}</div>}

      <div className="workspace-grid">
        {/* Left Column: Draft + Versions + Audit */}
        <section className="panel workspace-panel">
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '10px', flexWrap: 'wrap' }}>
            <h2 style={{ margin: 0 }}>Draft</h2>
            {versions.length > 0 && (
              <div className="version-pills" role="group" aria-label="Version history">
                {versions.map(v => {
                  const activePill = (viewingVersion ?? sub.version) === v.version
                  return (
                    <button
                      type="button"
                      key={v.version}
                      className={`version-pill${activePill ? ' active' : ''}`}
                      onClick={() => void handleSelectVersion(v.version)}
                    >
                      v{v.version} ({v.flag_count})
                    </button>
                  )
                })}
              </div>
            )}
          </div>

          <div className="workspace-paper">
            <h3>{activeSnapshot?.title || sub.title || 'Untitled submission'}</h3>
            {editing ? (
              <>
                {sub.status !== 'draft' && (
                  <p className="workspace-notice" style={{ background: '#fef3c7', color: '#78350f', fontSize: '12px', marginBottom: '10px' }}>
                    Saving edits will preserve v{sub.version}, create <strong>v{sub.version + 1}</strong>, and require fresh review &amp; approval.
                  </p>
                )}
                <label htmlFor="workspace-edit">Edit draft text</label>
                <textarea id="workspace-edit" value={editValue} onChange={e => setEditValue(e.target.value)} rows={10} disabled={!!busy} />
                <div className="workspace-actions">
                  <button type="button" onClick={handleSaveEdit} disabled={!!busy}>Save revision</button>
                  <button type="button" onClick={() => setEditing(false)} disabled={!!busy}>Cancel</button>
                </div>
              </>
            ) : sub.content_type === 'text' ? (
              <p className="workspace-text">
                {selectedFlag ? (
                  (() => {
                    const text = displayedText
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
                  displayedText || 'No text content.'
                )}
              </p>
            ) : fileUrl ? (
              sub.content_type === 'image' ? (
                <img className="workspace-image" src={fileUrl} alt={displayedFileName || 'Uploaded image'} />
              ) : (
                <object className="pdf-preview" data={fileUrl} type="application/pdf" aria-label="PDF preview">
                  <p>PDF preview unavailable. <a href={fileUrl} target="_blank" rel="noreferrer">Open PDF</a>.</p>
                </object>
              )
            ) : (
              <p className="workspace-muted">File: {displayedFileName || 'Binary asset uploaded'}</p>
            )}
          </div>

          {/* Creator & Manager Revision / Replacement Controls */}
          {!isHistoricalView && (user.role === 'creator' || user.role === 'manager') && !editing && sub.status !== 'ai_review' && (
            <div className="workspace-actions" style={{ marginTop: '12px' }}>
              {sub.content_type === 'text' ? (
                <button
                  type="button"
                  onClick={() => {
                    setEditValue(sub.text || '')
                    setEditing(true)
                  }}
                >
                  {sub.status === 'draft' ? 'Edit draft' : `Edit & create v${sub.version + 1}`}
                </button>
              ) : (
                <div style={{ display: 'flex', gap: '8px', alignItems: 'center', flexWrap: 'wrap' }}>
                  <input
                    ref={replaceInputRef}
                    type="file"
                    className="sr-only"
                    accept={sub.content_type === 'image' ? 'image/png,image/jpeg,image/webp' : 'application/pdf,.pdf'}
                    onChange={handleReplacementSelect}
                  />
                  <button type="button" onClick={() => replaceInputRef.current?.click()} disabled={!!busy}>
                    {replacementFile ? `Selected: ${replacementFile.name}` : `Replace ${sub.content_type.toUpperCase()} file`}
                  </button>
                  {replacementFile && (
                    <button type="button" className="btn-accept" onClick={() => void handleUploadReplacement()} disabled={!!busy}>
                      Upload &amp; {sub.status === 'draft' ? 'save' : `create v${sub.version + 1}`}
                    </button>
                  )}
                </div>
              )}
            </div>
          )}

          {/* Preserved Version & Audit Trail */}
          <details className="workspace-panel" style={{ marginTop: '16px', background: 'transparent', padding: '8px 0' }}>
            <summary>Version &amp; Audit Trail ({audit.length} events)</summary>
            {versions.length > 0 && (
              <ul style={{ marginTop: '8px', fontSize: '13px' }}>
                {versions.map(v => (
                  <li key={v.version}>
                    <strong>v{v.version}</strong> ({v.status || 'saved'}): {v.flag_count} findings, {v.decision_count || 0} decisions
                  </li>
                ))}
              </ul>
            )}
            {audit.length > 0 && (
              <ul style={{ marginTop: '8px', fontSize: '13px', lineHeight: '1.5' }}>
                {audit.map((evt, idx) => (
                  <li key={idx}>
                    <span style={{ color: '#6d5b56' }}>{new Date(evt.timestamp).toLocaleTimeString()}</span> ·{' '}
                    <strong>{evt.actor || evt.actor_role}</strong> — {evt.action}: {evt.detail}
                  </li>
                ))}
              </ul>
            )}
          </details>
        </section>

        {/* Right Column: Recurring Coaching + Brand vs External Lens Selector + Findings */}
        <section className="panel workspace-panel">
          <h2>Review findings</h2>

          {recurringHints.length > 0 && (
            <div className="recurring-coach-banner" role="note">
              <strong>Recurring Mistake Coaching</strong>
              <ul>
                {recurringHints.map((hint, idx) => (
                  <li key={idx}>{hint.message}</li>
                ))}
              </ul>
            </div>
          )}

          {/* Primary User Choice: Brand Guidelines vs External Verification */}
          <div className="lens-bar" role="tablist" aria-label="Choose what went wrong view">
            <button
              type="button"
              role="tab"
              aria-selected={lens === 'brand'}
              className={`lens-btn${lens === 'brand' ? ' active' : ''}`}
              onClick={() => setLens('brand')}
            >
              <div>
                Brand Guidelines
                <span className="lens-btn-meta">What went wrong vs. your brand</span>
              </div>
              <span className="lens-count">{brandFindings.length}</span>
            </button>

            <button
              type="button"
              role="tab"
              aria-selected={lens === 'claim'}
              className={`lens-btn${lens === 'claim' ? ' active' : ''}`}
              onClick={() => setLens('claim')}
            >
              <div>
                External Verification
                <span className="lens-btn-meta">What went wrong vs. web facts</span>
              </div>
              <span className="lens-count">{claimFindings.length}</span>
            </button>

            <button
              type="button"
              role="tab"
              aria-selected={lens === 'all'}
              className={`lens-btn${lens === 'all' ? ' active' : ''}`}
              onClick={() => setLens('all')}
            >
              <div>All</div>
              <span className="lens-count">{actionableFindings.length}</span>
            </button>
          </div>

          {displayStatus !== 'ai_review' && flags.some(f => f.origin === 'error') && (
            <div className="stale-label" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '10px' }}>
              <span>Review incomplete. Findings from completed checks remain visible; failed checks have not verified this draft. Retry runs a new check on this saved submission.</span>
              {(user.role === 'creator' || user.role === 'manager') && (
                <button type="button" className="btn-recheck" onClick={() => void handleCheck(true)} disabled={!!busy}>
                  Retry check
                </button>
              )}
            </div>
          )}

          {lensFindings.length === 0 ? (
            <div className="workspace-notice" role="status">
              {readiness === 'not_checked'
                ? 'Not yet checked. Run a review before interpreting findings for this version.'
                : readiness === 'review_in_progress'
                ? 'Review in progress. Findings will appear when the check completes.'
                : readiness === 'review_incomplete'
                ? 'Review incomplete. Some checks did not finish; retry or inspect the error above.'
                : 'No actionable findings returned in this view. This does not verify every claim or replace human review.'}
            </div>
          ) : (
            lensFindings.map((f, i) => renderFindingCard(f, i))
          )}

          {otherChecks.length > 0 && (
            <details style={{ marginTop: '14px' }}>
              <summary>Passed / Aligned Checks ({otherChecks.length})</summary>
              {otherChecks.map(f => renderFindingCard(f))}
            </details>
          )}

          <details className="local-records">
            <summary>Review Comments ({detail.comments.length})</summary>
            <label htmlFor="comment">Add review feedback</label>
            <textarea
              id="comment"
              value={commentText}
              onChange={e => setCommentText(e.target.value)}
              rows={2}
              placeholder="Leave feedback or guidance..."
              disabled={!!busy}
            />
            <button type="button" onClick={handleAddComment} disabled={!commentText.trim() || !!busy}>
              Post comment
            </button>
            {detail.comments.length > 0 && (
              <ul style={{ marginTop: '12px' }}>
                {detail.comments.map(c => (
                  <li key={c.id}>
                    <strong>{c.actor_name || c.role}</strong> ({c.role.replace('_', ' ')} · v{c.version}): {c.text}
                  </li>
                ))}
              </ul>
            )}
          </details>
        </section>
      </div>

      {/* Role-Enforced Approval Footer with Unresolved-Flag Gate & Authorised Override */}
      <div className="workspace-footer">
        <div>
          <span>
            Stage: <strong>{sub.status.replace('_', ' ').toUpperCase()}</strong> · Signed in as{' '}
            <strong>{user.name}</strong> ({user.role.replace('_', ' ')})
          </span>
        </div>

        <div className="workspace-actions">
          {sub.status === 'draft' &&
            (user.role === 'creator' || user.role === 'manager' ? (
              <button type="button" onClick={() => void handleCheck(false)} disabled={!!busy} style={{ background: '#dec9f2', fontWeight: 700 }}>
                Run Compliance Check →
              </button>
            ) : (
              <button type="button" onClick={onSwitchAccount}>
                Switch to Creator or Manager to run check
              </button>
            ))}

          {(sub.status === 'manager_review' || sub.status === 'final_approval') && (() => {
            const requiredRole = sub.status === 'manager_review' ? 'manager' : 'authorised_reviewer'
            const canReview = user.role === requiredRole || user.role === 'manager'
            if (!canReview) {
              return (
                <button type="button" onClick={onSwitchAccount} style={{ background: '#dec9f2' }}>
                  Switch to {requiredRole.replace('_', ' ')} to review
                </button>
              )
            }
            const needsOverride = blockingCount > 0
            const overrideValid = !needsOverride || (overrideChecked && overrideReason.trim().length >= 10)
            return (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', alignItems: 'flex-end' }}>
                {needsOverride && (
                  <div className="override-box">
                    <label style={{ display: 'flex', alignItems: 'center', gap: '6px', fontWeight: 600, fontSize: '12px' }}>
                      <input
                        type="checkbox"
                        checked={overrideChecked}
                        onChange={e => setOverrideChecked(e.target.checked)}
                      />
                      Authorised override ({blockingCount} open blocking finding{blockingCount > 1 ? 's' : ''})
                    </label>
                    {overrideChecked && (
                      <input
                        type="text"
                        placeholder="Required override justification (min 10 chars)..."
                        value={overrideReason}
                        onChange={e => setOverrideReason(e.target.value)}
                        style={{ padding: '6px 10px', borderRadius: '6px', border: '1px solid #c8bab6', width: '320px' }}
                      />
                    )}
                  </div>
                )}
                <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', alignItems: 'center' }}>
                  <input
                    type="text"
                    placeholder="Decision note (optional)..."
                    value={decisionComment}
                    onChange={e => setDecisionComment(e.target.value)}
                    style={{ padding: '8px 12px', borderRadius: '8px', border: '1px solid #b8aaa4' }}
                    disabled={!!busy}
                  />
                  <button
                    type="button"
                    onClick={() => void handleDecision('approve')}
                    disabled={!!busy || !overrideValid}
                    style={{
                      background: sub.status === 'final_approval' ? '#6be092' : '#dec9f2',
                      color: sub.status === 'final_approval' ? '#13351d' : '#28110f',
                      fontWeight: 700,
                    }}
                  >
                    {sub.status === 'manager_review' ? 'Approve as Manager' : 'Final Sign-Off'}
                  </button>
                  <button type="button" onClick={() => void handleDecision('request_changes')} disabled={!!busy}>
                    Request Changes
                  </button>
                </div>
              </div>
            )
          })()}

          {sub.status === 'approved' && (
            <span style={{ background: '#6be092', color: '#13351d', padding: '8px 16px', borderRadius: '8px', fontWeight: 700 }}>
              ✓ Publication Approved
            </span>
          )}

          <button type="button" onClick={onReturn}>Return to library</button>
        </div>
      </div>
    </div>
  )
}
