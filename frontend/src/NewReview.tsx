import { useEffect, useRef, useState } from 'react'
import type { ChangeEvent, DragEvent } from 'react'
import { demoChannels, demoGuidance } from './demoData'
import './NewReview.css'
import { readGuidanceDocuments } from './knowledgeData'
import { serverApi } from './serverApi'
import type { ContentType } from './serverApi'

type Format = 'Text' | 'Image' | 'PDF'
export type Draft = { format: Format; title: string; text: string; audience: string; channel: string; context: string; guidance: string }
type Files = Record<'Image' | 'PDF', File | null>
const emptyDraft: Draft = { format: 'Text', title: '', text: '', audience: '', channel: '', context: '', guidance: 'No brand guidance' }

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
          <input type="radio" name="format" value={format} checked={value === format} onChange={() => onChange(format)}/>
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
        <p>{file ? <><strong>{file.name}</strong><br/>Selected for upload</> : <>Drag and drop a {format === 'Image' ? 'PNG, JPEG or WebP image' : 'PDF'} here</>}</p>
        <div className="file-actions">
          <button type="button" className="outline-button" onClick={() => input.current?.click()}>{file ? 'Replace file' : 'Choose file'}</button>
          {file && <button type="button" className="plain-button" onClick={() => onFile(null)}>Remove</button>}
        </div>
        <input ref={input} className="sr-only" type="file" accept={format === 'Image' ? 'image/png,image/jpeg,image/webp' : 'application/pdf,.pdf'} onChange={selectFile} aria-label={`Choose ${format} file`} tabIndex={-1}/>
      </div>
      {error && <p className="form-error" role="alert">{error}</p>}
      <p className="field-hint">Files are uploaded directly to the verification service.</p>
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

function GuidanceCard({ value, onChange }: { value: string; onChange: (value: string) => void }) {
  const { docs, error } = readGuidanceDocuments()
  const known = value === 'No brand guidance' || demoGuidance.includes(value as typeof demoGuidance[number]) || docs.some(doc => `document:${doc.id}` === value)
  return (
    <section className="panel guidance-card">
      <h2>Review against</h2>
      <label htmlFor="guidance">Guidance reference</label>
      <select id="guidance" value={value} onChange={event => onChange(event.target.value)}>
        <option value="No brand guidance">Standard Brand Voice Guidelines v2.1</option>
        <optgroup label="Sample guidance">
          {demoGuidance.filter(option => option !== 'No brand guidance').map(option => <option value={option} key={option}>Sample · {option}</option>)}
        </optgroup>
        {docs.length > 0 && (
          <optgroup label="Your documents">
            {docs.map(doc => <option value={`document:${doc.id}`} key={doc.id}>{doc.title}</option>)}
          </optgroup>
        )}
        {!known && <option value={value}>Previously saved selection</option>}
      </select>
      {error && <p role="status">{error}</p>}
      <p>Checks are run against approved Brand Tone &amp; Claim Compliance standards.</p>
    </section>
  )
}

export default function NewReview({ onCreated }: { onCreated: (id: string) => void }) {
  const [draft, setDraft] = useState<Draft>(emptyDraft)
  const [files, setFiles] = useState<Files>({ Image: null, PDF: null })
  const [errors, setErrors] = useState<string[]>([])
  const [fileError, setFileError] = useState('')
  const [busy, setBusy] = useState(false)
  const [statusMessage, setStatusMessage] = useState('')
  const imageUrl = useFileUrl(files.Image)
  const pdfUrl = useFileUrl(files.PDF)
  const currentFile = draft.format === 'Text' ? null : files[draft.format]
  const currentUrl = draft.format === 'Image' ? imageUrl : draft.format === 'PDF' ? pdfUrl : ''

  function update<K extends keyof Draft>(key: K, value: Draft[K]) {
    setDraft(previous => ({ ...previous, [key]: value }))
    setErrors([])
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
    const next: string[] = []
    if (!draft.title.trim()) next.push('Enter a draft title.')
    if (draft.format === 'Text' && !draft.text.trim()) next.push('Enter content to review.')
    if (draft.format !== 'Text' && !currentFile) next.push(`Choose a ${draft.format} file.`)
    if (!draft.audience.trim()) next.push('Enter an audience.')
    if (!draft.channel) next.push('Choose a purpose / channel.')
    if (fileError) next.push('Choose a supported file type or remove the invalid selection.')
    setErrors(next)
    if (next.length > 0) return

    setBusy(true)
    setStatusMessage('Uploading submission to compliance server...')
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
      setStatusMessage('Running brand guideline & claim verification checks...')
      await serverApi.check(created.id)
      onCreated(created.id)
    } catch (err) {
      setBusy(false)
      setStatusMessage('')
      setErrors([err instanceof Error ? err.message : 'Submission failed. Please verify server connection and try again.'])
    }
  }

  return (
    <div className="new-review">
      <header className="review-intro">
        <h1>Bring your next draft.</h1>
        <p>Add your content and context. Review it against brand governance before it goes public.</p>
      </header>
      <div className="review-layout">
        <section className="panel review-form">
          <h2>What would you like to review?</h2>
          <FormatTabs value={draft.format} onChange={value => { update('format', value); setFileError('') }}/>
          <div className="field">
            <label htmlFor="draft-title">Draft title <span aria-hidden="true">*</span></label>
            <input id="draft-title" value={draft.title} onChange={event => update('title', event.target.value)} placeholder="e.g. Q4 Product Announcement" required disabled={busy}/>
          </div>
          {draft.format === 'Text' ? (
            <div className="field">
              <label htmlFor="draft-text">Content <span aria-hidden="true">*</span></label>
              <textarea id="draft-text" value={draft.text} onChange={event => update('text', event.target.value)} maxLength={50000} rows={6} required aria-describedby="character-count" placeholder="Paste draft text here..." disabled={busy}/>
              <p className="character-count" id="character-count">{draft.text.length.toLocaleString()} / 50,000 characters</p>
            </div>
          ) : (
            <FilePicker format={draft.format} file={currentFile} onFile={file => setFile(draft.format as 'Image' | 'PDF', file)} error={fileError}/>
          )}
          <div className="field-row">
            <div className="field">
              <label htmlFor="audience">Audience <span aria-hidden="true">*</span></label>
              <input id="audience" value={draft.audience} onChange={event => update('audience', event.target.value)} placeholder="e.g. Small business owners" required disabled={busy}/>
            </div>
            <div className="field">
              <label htmlFor="channel">Purpose / channel <span aria-hidden="true">*</span></label>
              <select id="channel" value={draft.channel} onChange={event => update('channel', event.target.value)} required disabled={busy}>
                <option value="">Select a channel</option>
                {demoChannels.map(channel => <option key={channel}>{channel}</option>)}
              </select>
            </div>
          </div>
          <div className="field">
            <label htmlFor="context">Additional context <span className="optional">(optional)</span></label>
            <textarea id="context" rows={2} value={draft.context} onChange={event => update('context', event.target.value)} placeholder="Anything the reviewer should know?" disabled={busy}/>
          </div>
        </section>
        <div className="review-side">
          <DraftPreview draft={draft} file={currentFile} url={currentUrl}/>
          <GuidanceCard value={draft.guidance} onChange={value => update('guidance', value)}/>
        </div>
      </div>
      {statusMessage && <p className="save-feedback" role="status">{statusMessage}</p>}
      {errors.length > 0 && (
        <div className="validation" role="alert">
          <strong>Please address the following:</strong>
          <ul>{errors.map(error => <li key={error}>{error}</li>)}</ul>
        </div>
      )}
      <div className="review-footer">
        <p>Checks evaluate tone compliance, buzzwords, and verifiable claim benchmarks.</p>
        <div>
          <button type="button" className="primary-button" onClick={submitForReview} disabled={busy}>
            {busy ? 'Running compliance check...' : 'Submit for review'} <span aria-hidden="true">→</span>
          </button>
        </div>
      </div>
    </div>
  )
}
