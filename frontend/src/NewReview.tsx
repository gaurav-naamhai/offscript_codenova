import { useEffect, useRef, useState } from 'react'
import type { ChangeEvent, DragEvent, FormEvent } from 'react'
import { demoChannels, demoGuidance } from './demoData'
import './NewReview.css'
import { readGuidanceDocuments } from './knowledgeData'
import { apiBase, serverApi } from './serverApi'
import type { ContentType } from './serverApi'
import { writeMetadata } from './metadataStore'
import type { ClientMetadata } from './metadataStore'

export type Format = 'Text' | 'Image' | 'PDF'
export type Draft = {
  format: Format
  title: string
  text: string
  audience: string
  channel: string
  context: string
  guidance: string
}

type Files = Record<'Image' | 'PDF', File | null>

const emptyDraft: Draft = {
  format: 'Text',
  title: '',
  text: '',
  audience: '',
  channel: '',
  context: '',
  guidance: 'No brand guidance',
}

function useFileUrl(file: File | null) {
  const [url, setUrl] = useState('')
  useEffect(() => {
    if (!file) {
      setUrl('')
      return
    }
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
          <input
            type="radio"
            name="format"
            value={format}
            checked={value === format}
            onChange={() => onChange(format)}
          />
          <span>{format}</span>
        </label>
      ))}
    </fieldset>
  )
}

function FilePicker({
  format,
  file,
  onFile,
  error,
}: {
  format: 'Image' | 'PDF'
  file: File | null
  onFile: (file: File | null) => void
  error: string
}) {
  const input = useRef<HTMLInputElement>(null)
  function selectFile(event: ChangeEvent<HTMLInputElement>) {
    if (event.target.files?.[0]) onFile(event.target.files[0])
    event.target.value = ''
  }
  function drop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault()
    if (event.dataTransfer.files[0]) onFile(event.dataTransfer.files[0])
  }
  return (
    <div className="field">
      <span className="field-label">
        {format} file <span aria-hidden="true">*</span>
      </span>
      <div className="drop-zone" onDragOver={event => event.preventDefault()} onDrop={drop}>
        <p>
          {file ? (
            <>
              <strong>{file.name}</strong>
              <br />
              {(file.size / (1024 * 1024)).toFixed(2)} MB selected
            </>
          ) : (
            <>
              Drag and drop a {format === 'Image' ? 'PNG, JPEG or WebP image (max 5 MiB)' : 'PDF (max 10 MiB)'} here
            </>
          )}
        </p>
        <div className="file-actions">
          <button type="button" className="outline-button" onClick={() => input.current?.click()}>
            {file ? 'Replace file' : 'Choose file'}
          </button>
          {file && (
            <button type="button" className="plain-button" onClick={() => onFile(null)}>
              Remove
            </button>
          )}
        </div>
        <input
          ref={input}
          className="sr-only"
          type="file"
          accept={format === 'Image' ? 'image/png,image/jpeg,image/webp' : 'application/pdf,.pdf'}
          onChange={selectFile}
          aria-label={`Choose ${format} file`}
          tabIndex={-1}
        />
      </div>
      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}
      <p className="field-hint">
        {format === 'Image'
          ? 'Supported: PNG, JPEG, WebP up to 5 MiB.'
          : 'Supported: PDF up to 10 MiB.'}
      </p>
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
          <>
            <img src={url} alt={`Preview of ${file.name}`} />
            <p className="preview-filename">{file.name}</p>
          </>
        ) : (
          <>
            <object
              className="pdf-preview"
              data={url}
              type="application/pdf"
              aria-label={`PDF preview: ${file.name}`}
            >
              <p>
                PDF preview is unavailable.{' '}
                <a href={url} target="_blank" rel="noreferrer">
                  Open PDF file
                </a>
                .
              </p>
            </object>
            <p className="preview-filename">
              {file.name} ·{' '}
              <a href={url} target="_blank" rel="noreferrer">
                Open PDF file
              </a>
            </p>
          </>
        )}
      </div>
    </section>
  )
}

function GuidanceCard({ value, onChange }: { value: string; onChange: (value: string) => void }) {
  const { docs, error } = readGuidanceDocuments()
  const known =
    value === 'No brand guidance' ||
    demoGuidance.includes(value as (typeof demoGuidance)[number]) ||
    docs.some(doc => `document:${doc.id}` === value)

  return (
    <section className="panel guidance-card">
      <h2>Review against</h2>
      <label htmlFor="guidance">Guidance reference</label>
      <select id="guidance" value={value} onChange={event => onChange(event.target.value)}>
        <option value="No brand guidance">No brand guidance</option>
        <optgroup label="Sample guidance">
          {demoGuidance
            .filter(option => option !== 'No brand guidance')
            .map(option => (
              <option value={option} key={option}>
                Reference · {option}
              </option>
            ))}
        </optgroup>
        {docs.length > 0 && (
          <optgroup label="Your documents — reference only">
            {docs.map(doc => (
              <option value={`document:${doc.id}`} key={doc.id}>
                {doc.title} · Not processed
              </option>
            ))}
          </optgroup>
        )}
        {!known && <option value={value}>Previously saved selection unavailable</option>}
      </select>
      {error && <p role="status">{error}</p>}
      <p>
        Selections are references only. Documents are not processed by backend review modules.
        Checks use backend fixture rules.
      </p>
    </section>
  )
}

export default function NewReview({ onCreated }: { onCreated: (id: string) => void }) {
  const [draft, setDraft] = useState<Draft>(emptyDraft)
  const [files, setFiles] = useState<Files>({ Image: null, PDF: null })
  const [errors, setErrors] = useState<string[]>([])
  const [fileError, setFileError] = useState('')
  const [busy, setBusy] = useState(false)
  const [serverError, setServerError] = useState('')

  const imageUrl = useFileUrl(files.Image)
  const pdfUrl = useFileUrl(files.PDF)
  const currentFile = draft.format === 'Text' ? null : files[draft.format]
  const currentUrl = draft.format === 'Image' ? imageUrl : draft.format === 'PDF' ? pdfUrl : ''

  function update<K extends keyof Draft>(key: K, value: Draft[K]) {
    setDraft(previous => ({ ...previous, [key]: value }))
    setServerError('')
    setErrors([])
  }

  function setFile(format: 'Image' | 'PDF', file: File | null) {
    if (!file) {
      setFileError('')
      setFiles(previous => ({ ...previous, [format]: null }))
      return
    }

    if (format === 'Image') {
      const allowed = ['image/png', 'image/jpeg', 'image/webp']
      if (!allowed.includes(file.type)) {
        setFileError('Choose a PNG, JPEG or WebP image. (GIF is not supported).')
        return
      }
      if (file.size > 5 * 1024 * 1024) {
        setFileError('Image exceeds the 5 MiB size limit.')
        return
      }
    } else {
      const isPdf = file.type === 'application/pdf' || file.name.toLowerCase().endsWith('.pdf')
      if (!isPdf) {
        setFileError('Choose a valid PDF file.')
        return
      }
      if (file.size > 10 * 1024 * 1024) {
        setFileError('PDF exceeds the 10 MiB size limit.')
        return
      }
    }

    setFileError('')
    setErrors([])
    setServerError('')
    setFiles(previous => ({ ...previous, [format]: file }))
  }

  async function submitReview(event: FormEvent) {
    event.preventDefault()
    const next: string[] = []

    if (!draft.title.trim()) next.push('Enter a draft title.')
    if (draft.format === 'Text') {
      if (!draft.text.trim()) next.push('Enter content to review.')
      if (draft.text.length > 10000) next.push('Text exceeds the 10,000 character limit.')
    } else {
      if (!currentFile) next.push(`Choose a ${draft.format} file.`)
    }
    if (!draft.audience.trim()) next.push('Enter an audience.')
    if (!draft.channel) next.push('Choose a purpose / channel.')
    if (fileError) next.push('Fix file error before submitting.')

    setErrors(next)
    if (next.length > 0) return

    setBusy(true)
    setServerError('')

    try {
      const contentType: ContentType = draft.format.toLowerCase() as ContentType
      const result = await serverApi.create(contentType, draft.text, currentFile)

      const metadata: ClientMetadata = {
        title: draft.title.trim(),
        audience: draft.audience.trim(),
        channel: draft.channel,
        context: draft.context.trim(),
        guidance: draft.guidance,
      }
      writeMetadata(result.id, metadata)
      onCreated(result.id)
    } catch (err) {
      setServerError(
        err instanceof Error
          ? err.message
          : 'Could not create submission. Check server connection.'
      )
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="new-review">
      <div className="workspace-banner" style={{ marginBottom: '16px' }}>
        <strong>Placeholder checks. No live AI analysis.</strong>
        <span> Submissions are sent to {apiBase}. Free-tier server data resets periodically.</span>
      </div>

      <header className="review-intro">
        <h1>Bring your next draft.</h1>
        <p>Add your content and context. Review it before it goes public.</p>
      </header>

      <form onSubmit={submitReview}>
        <div className="review-layout">
          <section className="panel review-form">
            <h2>What would you like to review?</h2>
            <FormatTabs
              value={draft.format}
              onChange={value => {
                update('format', value)
                setFileError('')
              }}
            />

            <div className="field">
              <label htmlFor="draft-title">
                Draft title <span aria-hidden="true">*</span>
              </label>
              <input
                id="draft-title"
                value={draft.title}
                onChange={event => update('title', event.target.value)}
                placeholder="e.g. Summer launch newsletter"
                required
              />
              <p className="field-hint">
                Title, audience, channel, context, and guidance are stored in this browser only.
              </p>
            </div>

            {draft.format === 'Text' ? (
              <div className="field">
                <label htmlFor="draft-text">
                  Content <span aria-hidden="true">*</span>
                </label>
                <textarea
                  id="draft-text"
                  value={draft.text}
                  onChange={event => update('text', event.target.value)}
                  maxLength={10000}
                  rows={5}
                  required
                  aria-describedby="character-count"
                />
                <p className="character-count" id="character-count">
                  {draft.text.length.toLocaleString()} / 10,000 characters
                </p>
              </div>
            ) : (
              <FilePicker
                format={draft.format}
                file={currentFile}
                onFile={file => setFile(draft.format as 'Image' | 'PDF', file)}
                error={fileError}
              />
            )}

            <div className="field-row">
              <div className="field">
                <label htmlFor="audience">
                  Audience <span aria-hidden="true">*</span>
                </label>
                <input
                  id="audience"
                  value={draft.audience}
                  onChange={event => update('audience', event.target.value)}
                  placeholder="e.g. Small business owners"
                  required
                />
              </div>
              <div className="field">
                <label htmlFor="channel">
                  Purpose / channel <span aria-hidden="true">*</span>
                </label>
                <select
                  id="channel"
                  value={draft.channel}
                  onChange={event => update('channel', event.target.value)}
                  required
                >
                  <option value="">Select a channel</option>
                  {demoChannels.map(channel => (
                    <option key={channel}>{channel}</option>
                  ))}
                </select>
              </div>
            </div>

            <div className="field">
              <label htmlFor="context">
                Additional context <span className="optional">(optional)</span>
              </label>
              <textarea
                id="context"
                rows={2}
                value={draft.context}
                onChange={event => update('context', event.target.value)}
                placeholder="Anything the reviewer should know?"
              />
            </div>
          </section>

          <div className="review-side">
            <DraftPreview draft={draft} file={currentFile} url={currentUrl} />
            <GuidanceCard
              value={draft.guidance}
              onChange={value => update('guidance', value)}
            />
          </div>
        </div>

        {errors.length > 0 && (
          <div className="validation" role="alert" style={{ marginTop: '16px' }}>
            <strong>Please complete the draft:</strong>
            <ul>
              {errors.map(error => (
                <li key={error}>{error}</li>
              ))}
            </ul>
          </div>
        )}

        {serverError && (
          <div className="validation" role="alert" style={{ marginTop: '16px' }}>
            <strong>Server error:</strong> {serverError}
          </div>
        )}

        <div className="review-footer">
          <p>
            {busy
              ? 'Connecting to the server. The first request can take up to a minute…'
              : 'Submissions are sent to the backend server. Analysis uses placeholder checks.'}
          </p>
          <div>
            <button type="submit" className="primary-button" disabled={busy}>
              {busy ? 'Creating submission…' : 'Submit for review'}{' '}
              <span aria-hidden="true">→</span>
            </button>
          </div>
        </div>
      </form>
    </div>
  )
}
