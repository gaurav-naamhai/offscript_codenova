import { useEffect, useRef, useState } from 'react'
import type { ChangeEvent, DragEvent } from 'react'
import { demoChannels, demoGuidance } from './demoData'
import './NewReview.css'
import ReviewWorkspace from './ReviewWorkspace'

type Format = 'Text' | 'Image' | 'PDF'
export type Draft = { format: Format; title: string; text: string; audience: string; channel: string; context: string; guidance: string }
type Files = Record<'Image' | 'PDF', File | null>
const storageKey = 'inkloom-demo-draft'
const emptyDraft: Draft = { format: 'Text', title: '', text: '', audience: '', channel: '', context: '', guidance: demoGuidance[0] }
function loadDraft(): Draft {
  try {
    const saved: unknown = JSON.parse(localStorage.getItem(storageKey) || 'null')
    if (!saved || typeof saved !== 'object') return emptyDraft
    const data = saved as Partial<Draft>
    return { format: data.format === 'Image' || data.format === 'PDF' ? data.format : 'Text', title: typeof data.title === 'string' ? data.title : '', text: typeof data.text === 'string' ? data.text : '', audience: typeof data.audience === 'string' ? data.audience : '', channel: typeof data.channel === 'string' ? data.channel : '', context: typeof data.context === 'string' ? data.context : '', guidance: typeof data.guidance === 'string' ? data.guidance : demoGuidance[0] }
  } catch { return emptyDraft }
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
  return <fieldset className="format-tabs"><legend className="sr-only">Content format</legend>{(['Text', 'Image', 'PDF'] as const).map(format => <label key={format} className={value === format ? 'selected' : ''}><input type="radio" name="format" value={format} checked={value === format} onChange={() => onChange(format)}/><span>{format}</span></label>)}</fieldset>
}
function FilePicker({ format, file, onFile, error }: { format: 'Image' | 'PDF'; file: File | null; onFile: (file: File | null) => void; error: string }) {
  const input = useRef<HTMLInputElement>(null)
  function selectFile(event: ChangeEvent<HTMLInputElement>) { if (event.target.files?.[0]) onFile(event.target.files[0]); event.target.value = '' }
  function drop(event: DragEvent<HTMLDivElement>) { event.preventDefault(); if (event.dataTransfer.files[0]) onFile(event.dataTransfer.files[0]) }
  return <div className="field"><span className="field-label">{format} file <span aria-hidden="true">*</span></span><div className="drop-zone" onDragOver={event => event.preventDefault()} onDrop={drop}><p>{file ? <><strong>{file.name}</strong><br/>Selected for this session</> : <>Drag and drop a {format === 'Image' ? 'PNG, JPEG, GIF or WebP image' : 'PDF'} here</>}</p><div className="file-actions"><button type="button" className="outline-button" onClick={() => input.current?.click()}>{file ? 'Replace file' : 'Choose file'}</button>{file && <button type="button" className="plain-button" onClick={() => onFile(null)}>Remove</button>}</div><input ref={input} className="sr-only" type="file" accept={format === 'Image' ? 'image/png,image/jpeg,image/gif,image/webp' : 'application/pdf,.pdf'} onChange={selectFile} aria-label={`Choose ${format} file`} tabIndex={-1}/></div>{error && <p className="form-error" role="alert">{error}</p>}<p className="field-hint">Files stay in this browser session and are not saved after refresh.</p></div>
}
function DraftPreview({ draft, file, url }: { draft: Draft; file: File | null; url: string }) {
  return <section className="panel review-preview"><div className="preview-heading"><h2>Draft preview</h2><span className="format-badge">{draft.format}</span></div><div className="preview-paper"><h3>{draft.title.trim() || 'Untitled draft'}</h3>{draft.format === 'Text' ? <p className="preview-text">{draft.text || 'Your text will appear here as you type.'}</p> : !file || !url ? <p className="preview-empty">Choose a {draft.format} file to preview it here.</p> : draft.format === 'Image' ? <><img src={url} alt={`Preview of ${file.name}`} /><p className="preview-filename">{file.name}</p></> : <><object className="pdf-preview" data={url} type="application/pdf" aria-label={`PDF preview: ${file.name}`}><p>PDF preview is unavailable. <a href={url} target="_blank" rel="noreferrer">Open PDF file</a>.</p></object><p className="preview-filename">{file.name} · <a href={url} target="_blank" rel="noreferrer">Open PDF file</a></p></>}</div></section>
}
function GuidanceCard({ value, onChange }: { value: string; onChange: (value: string) => void }) {
  return <section className="panel guidance-card"><h2>Review against</h2><label htmlFor="guidance">Demo brand guidance</label><select id="guidance" value={value} onChange={event => onChange(event.target.value)}>{demoGuidance.map(option => <option key={option}>{option}</option>)}</select><p>Demo selection only. No brand guidance is applied or analyzed.</p></section>
}
export default function NewReview() {
  const [draft, setDraft] = useState<Draft>(loadDraft)
  const [files, setFiles] = useState<Files>({ Image: null, PDF: null })
  const [errors, setErrors] = useState<string[]>([])
  const [fileError, setFileError] = useState('')
  const [feedback, setFeedback] = useState('')
  const [demo, setDemo] = useState(false)
  const imageUrl = useFileUrl(files.Image)
  const pdfUrl = useFileUrl(files.PDF)
  const currentFile = draft.format === 'Text' ? null : files[draft.format]
  const currentUrl = draft.format === 'Image' ? imageUrl : draft.format === 'PDF' ? pdfUrl : ''
  function update<K extends keyof Draft>(key: K, value: Draft[K]) { setDraft(previous => ({ ...previous, [key]: value })); setFeedback(''); setErrors([]) }
  function setFile(format: 'Image' | 'PDF', file: File | null) {
    const valid = !file || (format === 'Image' ? ['image/png', 'image/jpeg', 'image/gif', 'image/webp'].includes(file.type) : file.type === 'application/pdf')
    if (!valid) { setFileError(format === 'Image' ? 'Choose a PNG, JPEG, GIF or WebP image.' : 'Choose a PDF file.'); return }
    setFileError(''); setErrors([]); setFeedback(''); setFiles(previous => ({ ...previous, [format]: file }))
  }
  function saveDraft() {
    try { localStorage.setItem(storageKey, JSON.stringify(draft)); setFeedback('Draft text and details saved in this browser. Files are not saved and must be selected again after refresh.') }
    catch { setFeedback('Could not save locally. Check browser storage settings and try again.') }
  }
  function preview() {
    const next: string[] = []
    if (!draft.title.trim()) next.push('Enter a draft title.')
    if (draft.format === 'Text' && !draft.text.trim()) next.push('Enter content to review.')
    if (draft.format !== 'Text' && !currentFile) next.push(`Choose a ${draft.format} file.`)
    if (!draft.audience.trim()) next.push('Enter an audience.')
    if (!draft.channel) next.push('Choose a purpose / channel.')
    if (fileError) next.push('Choose a supported file type or remove the invalid selection.')
    setErrors(next)
    if (!next.length) { setDemo(true); window.scrollTo(0, 0) }
  }
  if (demo) return <ReviewWorkspace submitted={draft} file={currentFile} url={currentUrl} onReturn={() => setDemo(false)} onUpdateText={text => setDraft(previous => ({ ...previous, text }))}/>
  return <div className="new-review"><header className="review-intro"><h1>Bring your next draft.</h1><p>Add your content and context. Review it before it goes public.</p></header><div className="review-layout"><section className="panel review-form"><h2>What would you like to review?</h2><FormatTabs value={draft.format} onChange={value => { update('format', value); setFileError('') }}/><div className="field"><label htmlFor="draft-title">Draft title <span aria-hidden="true">*</span></label><input id="draft-title" value={draft.title} onChange={event => update('title', event.target.value)} required /></div>{draft.format === 'Text' ? <div className="field"><label htmlFor="draft-text">Content <span aria-hidden="true">*</span></label><textarea id="draft-text" value={draft.text} onChange={event => update('text', event.target.value)} maxLength={10000} rows={5} required aria-describedby="character-count"/><p className="character-count" id="character-count">{draft.text.length.toLocaleString()} / 10,000 characters</p></div> : <FilePicker format={draft.format} file={currentFile} onFile={file => setFile(draft.format as 'Image' | 'PDF', file)} error={fileError}/>}<div className="field-row"><div className="field"><label htmlFor="audience">Audience <span aria-hidden="true">*</span></label><input id="audience" value={draft.audience} onChange={event => update('audience', event.target.value)} placeholder="e.g. Small business owners" required/></div><div className="field"><label htmlFor="channel">Purpose / channel <span aria-hidden="true">*</span></label><select id="channel" value={draft.channel} onChange={event => update('channel', event.target.value)} required><option value="">Select a channel</option>{demoChannels.map(channel => <option key={channel}>{channel}</option>)}</select></div></div><div className="field"><label htmlFor="context">Additional context <span className="optional">(optional)</span></label><textarea id="context" rows={2} value={draft.context} onChange={event => update('context', event.target.value)} placeholder="Anything the reviewer should know?"/></div></section><div className="review-side"><DraftPreview draft={draft} file={currentFile} url={currentUrl}/><GuidanceCard value={draft.guidance} onChange={value => update('guidance', value)}/></div></div>{errors.length > 0 && <div className="validation" role="alert"><strong>Please complete the draft:</strong><ul>{errors.map(error => <li key={error}>{error}</li>)}</ul></div>}<div className="review-footer"><p>No content is sent to AI or external services.</p><div><button type="button" className="save-button" onClick={saveDraft}>Save draft</button><button type="button" className="primary-button" onClick={preview}>Preview demo review <span aria-hidden="true">→</span></button></div></div><p className="save-feedback" role="status">{feedback}</p></div>
}
