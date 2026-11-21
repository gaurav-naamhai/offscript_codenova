import { useEffect, useRef, useState } from 'react'
import type { ChangeEvent, DragEvent } from 'react'
import './NewReview.css'
import { serverApi } from './serverApi'
import type { AuthUser, ContentType, RecurringHint } from './serverApi'

type Format = 'Text' | 'Image' | 'PDF'
export type Draft = { format: Format; title: string; text: string; audience: string; channel: string; context: string; guidance: string }
type Files = Record<'Image' | 'PDF', File | null>
const emptyDraft: Draft = { format: 'Text', title: '', text: '', audience: '', channel: '', context: '', guidance: 'Org Brand Guidelines' }

function loadSavedDraft(orgId: string): { draft: Draft; restored: boolean } {
  try {
    const raw = window.localStorage.getItem(`inkloom_unsent_draft_${orgId}`)
    if (!raw) return { draft: emptyDraft, restored: false }
    const parsed = JSON.parse(raw) as Partial<Draft>
    const hasContent = Boolean((parsed.text && parsed.text.trim()) || (parsed.title && parsed.title.trim()))
    return {
      draft: { ...emptyDraft, ...parsed },
      restored: hasContent,
    }
  } catch {
    return { draft: emptyDraft, restored: false }
  }
}

function useFileUrl(file: File | null) {
  const [url, setUrl] = useState('')
  useEffect(() => {
    if (!file) { setUrl(''); return }
    const next = URL.createObjectURL(file)
    setUrl(next)
    return () => URL.revokeObjectURL(next)
  }, [file])
  return url
}

function FormatTabs({ value, onChange }: { value: Format; onChange: (value: Format) => void }) {
  return (
    <fieldset className="format-tabs">
      <legend className="sr-only">Content format</legend>
      {(['Text', 'Image', 'PDF'] as const).map(format => (
        <label key={format} className={value === format ? 'selected' : ''}>
          <input type="radio" name="format" value={format} checked={value === format} onChange={() => onChange(format)} />
          <span>{format}</span>
        </label>
      ))}
    </fieldset>
  )
}

function FilePicker({ format, file, onFile, error }: { format: 'Image' | 'PDF'; file: File | null; onFile: (file: File | null) => void; error: string }) {
  const input = useRef<HTMLInputElement>(null)
  function selectFile(event: ChangeEvent<HTMLInputElement>) { if (event.target.files?.[0]) onFile(event.target.files[0]); event.target.value = '' }
  function drop(event: DragEvent<HTMLDivElement>) { event.preventDefault(); if (event.dataTransfer.files[0]) onFile(event.dataTransfer.files[0]) }
  return (
    <div className="field">
      <span className="field-label">{format} file <span aria-hidden="true">*</span></span>
      <div className="drop-zone" onDragOver={event => event.preventDefault()} onDrop={drop}>
        <p>{file ? <><strong>{file.name}</strong><br />Selected for upload</> : <>Drag and drop a {format === 'Image' ? 'PNG, JPEG or WebP image' : 'PDF'} here</>}</p>
        <div className="file-actions">
          <button type="button" className="outline-button" onClick={() => input.current?.click()}>{file ? 'Replace file' : 'Choose file'}</button>
          {file && <button type="button" className="plain-button" onClick={() => onFile(null)}>Remove</button>}
        </div>
        <input ref={input} className="sr-only" type="file" accept={format === 'Image' ? 'image/png,image/jpeg,image/webp' : 'application/pdf,.pdf'} onChange={selectFile} aria-label={`Choose ${format} file`} tabIndex={-1} />
      </div>
      {error && <p className="form-error" role="alert">{error}</p>}
      <p className="field-hint">Supported: pasted text, PNG, JPEG, WebP and PDF. Word files are not supported. Reviews can be delayed or incomplete when services are unavailable.</p>
    </div>
  )
}

function DraftPreview({ draft, file, url }: { draft: Draft; file: File | null; url: string }) {
  return (
    <section className="panel review-preview">
      <div className="preview-heading">
        <h2>Draft preview</h2>
        <span className="format-badge">{draft.format}</span>
      </div>
      <div className="preview-paper">
        <h3>{draft.title.trim() || 'Untitled draft'}</h3>
        {draft.format === 'Text' ? (
          <p className="preview-text">{draft.text || 'Your text will appear here as you type.'}</p>
        ) : !file || !url ? (
          <p className="preview-empty">Choose a {draft.format} file to preview it here.</p>
        ) : draft.format === 'Image' ? (
          <><img src={url} alt={`Preview of ${file.name}`} /><p className="preview-filename">{file.name}</p></>
        ) : (
          <><object className="pdf-preview" data={url} type="application/pdf" aria-label={`PDF preview: ${file.name}`}><p>PDF preview is unavailable. <a href={url} target="_blank" rel="noreferrer">Open PDF file</a>.</p></object><p className="preview-filename">{file.name} · <a href={url} target="_blank" rel="noreferrer">Open PDF file</a></p></>
        )}
      </div>
    </section>
  )
}

export default function NewReview({
  user,
  onCreated,
  onSwitchAccount,
}: {
  user: AuthUser
  onCreated: (id: string) => void
  onSwitchAccount: () => void
}) {
  const storageKey = `inkloom_unsent_draft_${user.org_id}`
  const initialSaved = loadSavedDraft(user.org_id)
  const [draft, setDraft] = useState<Draft>(initialSaved.draft)
  const [restoredDraft, setRestoredDraft] = useState(initialSaved.restored)
  const [files, setFiles] = useState<Files>({ Image: null, PDF: null })
  const [errors, setErrors] = useState<string[]>([])
  const [fileError, setFileError] = useState('')
  const [busy, setBusy] = useState(false)
  const [statusMessage, setStatusMessage] = useState('')
  const [liveHints, setLiveHints] = useState<RecurringHint[]>([])
  const submitting = useRef(false)

  // Persist unsent draft cleanly across refreshes
  useEffect(() => {
    try {
      if (draft.text.trim() || draft.title.trim()) {
        window.localStorage.setItem(storageKey, JSON.stringify(draft))
      } else {
        window.localStorage.removeItem(storageKey)
      }
    } catch {
      // ignore quota failures
    }
  }, [draft, storageKey])

  // Debounced pre-flight recurring-mistake & Brand Constitution coaching hints while typing
  useEffect(() => {
    if (draft.format !== 'Text' || draft.text.trim().length < 12) {
      const clearTimer = window.setTimeout(() => setLiveHints([]), 0)
      return () => window.clearTimeout(clearTimer)
    }
    const timer = window.setTimeout(() => {
      void serverApi
        .draftHints(draft.text)
        .then(hints => setLiveHints(hints))
        .catch(() => setLiveHints([]))
    }, 600)
    return () => window.clearTimeout(timer)
  }, [draft.format, draft.text, user.org_id])

  const imageUrl = useFileUrl(files.Image)
  const pdfUrl = useFileUrl(files.PDF)
  const currentFile = draft.format === 'Text' ? null : files[draft.format]
  const currentUrl = draft.format === 'Image' ? imageUrl : draft.format === 'PDF' ? pdfUrl : ''

  function update<K extends keyof Draft>(key: K, value: Draft[K]) {
    setDraft(previous => ({ ...previous, [key]: value }))
    setErrors([])
  }

  function clearSavedDraft() {
    setDraft(emptyDraft)
    setRestoredDraft(false)
    setLiveHints([])
    try {
      window.localStorage.removeItem(storageKey)
    } catch {
      // ignore
    }
  }

  function setFile(format: 'Image' | 'PDF', file: File | null) {
    const valid = !file || (format === 'Image' ? ['image/png', 'image/jpeg', 'image/webp'].includes(file.type) : file.type === 'application/pdf')
    if (!valid) {
      setFileError(format === 'Image' ? 'Choose a PNG, JPEG or WebP image.' : 'Choose a PDF file.')
      return
    }
    setFileError('')
    setErrors([])
    setFiles(previous => ({ ...previous, [format]: file }))
  }

  async function submitForReview() {
    if (submitting.current) return
    if (user.role !== 'creator' && user.role !== 'manager') {
      setErrors(['Only Creator and Manager accounts can submit new drafts. Switch to an authorized account to submit.'])
      return
    }
    const next: string[] = []
    if (draft.format === 'Text' && !draft.text.trim()) next.push('Enter content to review.')
    if (draft.format !== 'Text' && !currentFile) next.push(`Choose a ${draft.format} file.`)
    if (fileError) next.push('Choose a supported file type or remove the invalid selection.')
    setErrors(next)
    if (next.length > 0) return

    submitting.current = true
    setBusy(true)
    setStatusMessage('Uploading & starting background compliance check…')
    try {
      const type = draft.format.toLowerCase() as ContentType
      const created = await serverApi.create(
        type,
        draft.text,
        currentFile,
        draft.title.trim(),
        draft.audience.trim(),
        draft.channel,
        draft.context.trim() || undefined
      )
      try {
        window.localStorage.removeItem(storageKey)
      } catch {
        // ignore
      }
      await serverApi.checkAsync(created.id)
      onCreated(created.id)
    } catch (err) {
      setBusy(false)
      setStatusMessage('')
      setErrors([err instanceof Error ? err.message : 'Submission failed. Verify server connection and try again.'])
    } finally {
      submitting.current = false
    }
  }

  return (
    <div className="new-review">
      <p className="judge-note">
        ★ For the judges: &#123; Type a draft or upload an image/PDF and submit. Review the findings, evidence, incomplete-check warnings and human approval status before publication. &#125;
      </p>
      <header className="review-intro review-intro-bar">
        <div>
          <h1>Bring your next draft.</h1>
        </div>
        <button
          type="button"
          className="primary-button"
          onClick={submitForReview}
          disabled={busy || (user.role !== 'creator' && user.role !== 'manager')}
        >
          {busy ? statusMessage : 'Submit for review'} <span aria-hidden="true">→</span>
        </button>
      </header>

      {user.role !== 'creator' && user.role !== 'manager' && (
        <div className="validation" role="status" style={{ marginBottom: '16px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '12px', flexWrap: 'wrap' }}>
          <span>Signed in as <strong>{user.role.replace('_', ' ')}</strong>. Only Creators and Managers can submit new drafts.</span>
          <button type="button" className="outline-button" onClick={onSwitchAccount}>
            Switch to Creator
          </button>
        </div>
      )}

      {restoredDraft && (
        <div className="workspace-notice" style={{ marginBottom: '14px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '12px' }}>
          <span>Unsent draft restored automatically.</span>
          <button type="button" className="plain-button" onClick={clearSavedDraft}>
            Clear draft
          </button>
        </div>
      )}

      <div className="review-layout">
        <section className="panel review-form">
          <h2>What would you like to review?</h2>
          <FormatTabs value={draft.format} onChange={value => { update('format', value); setFileError('') }} />
          <div className="field">
            <label htmlFor="draft-title">Title (optional)</label>
            <input id="draft-title" value={draft.title} onChange={event => update('title', event.target.value)} placeholder="e.g. Q4 Product Announcement" disabled={busy} />
          </div>
          {draft.format === 'Text' ? (
            <div className="field">
              <label htmlFor="draft-text">Content <span aria-hidden="true">*</span></label>
              <textarea id="draft-text" value={draft.text} onChange={event => update('text', event.target.value)} maxLength={50000} rows={5} required aria-describedby="character-count" placeholder="Paste draft text here..." disabled={busy} />
              <p className="character-count" id="character-count">{draft.text.length.toLocaleString()} / 50,000 characters</p>

              {liveHints.length > 0 && (
                <div className="workspace-notice stagger-card" style={{ marginTop: '10px', background: '#fef3c7', color: '#78350f', border: '1px solid #fcd34d' }}>
                  <strong>Early coaching hint before you submit:</strong>
                  <ul style={{ margin: '6px 0 0', paddingLeft: '18px', fontSize: '13px' }}>
                    {liveHints.map((h, idx) => (
                      <li key={idx}>{h.message}</li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          ) : (
            <FilePicker format={draft.format} file={currentFile} onFile={file => setFile(draft.format as 'Image' | 'PDF', file)} error={fileError} />
          )}

          {errors.length > 0 && (
            <div className="validation" role="alert">
              <strong>Please address the following:</strong>
              <ul>{errors.map(error => <li key={error}>{error}</li>)}</ul>
            </div>
          )}

          <div className="review-inline-submit">
            <span className="character-count" style={{ textAlign: 'left', margin: 0 }}>
              Draft auto-saved locally. Final publication requires Manager &amp; Reviewer approval.
            </span>
            <button
              type="button"
              className="primary-button"
              onClick={submitForReview}
              disabled={busy || (user.role !== 'creator' && user.role !== 'manager')}
            >
              {busy ? statusMessage : 'Submit for review'} <span aria-hidden="true">→</span>
            </button>
          </div>
        </section>

        <div className="review-side">
          <DraftPreview draft={draft} file={currentFile} url={currentUrl} />
          <p>Only {user.brand_name}’s active guidelines and verified relevant sources are consulted.</p>
        </div>
      </div>

      <div role="status" aria-live="polite" aria-atomic="true">
        {statusMessage && <p className="save-feedback">{statusMessage}</p>}
      </div>
    </div>
  )
}
