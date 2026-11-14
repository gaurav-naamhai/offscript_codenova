import { useEffect, useRef, useState } from 'react'
import { serverApi } from './serverApi'
import type { SubmissionSummary } from './serverApi'
import { listBrandDocuments } from './brandDocuments'
import type { BrandDocument } from './brandDocuments'

type Props = { onClose: () => void; onReview: (id: string) => void; onDocument: (id: string) => void }

export default function GlobalSearch({ onClose, onReview, onDocument }: Props) {
  const dialog = useRef<HTMLDialogElement>(null)
  const input = useRef<HTMLInputElement>(null)
  const [query, setQuery] = useState('')
  const [reviews, setReviews] = useState<SubmissionSummary[]>([])
  const [documents, setDocuments] = useState<BrandDocument[]>([])
  const [reviewsLoading, setReviewsLoading] = useState(true)
  const [documentsLoading, setDocumentsLoading] = useState(true)
  const [reviewError, setReviewError] = useState('')
  const [documentError, setDocumentError] = useState('')

  useEffect(() => {
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null
    const node = dialog.current
    node?.showModal()
    input.current?.focus()
    let active = true
    void serverApi.list().then(data => { if (active) setReviews(data) }).catch(error => { if (active) setReviewError(error instanceof Error ? error.message : 'Could not load reviews.') }).finally(() => { if (active) setReviewsLoading(false) })
    void listBrandDocuments().then(data => { if (active) setDocuments(data) }).catch(error => { if (active) setDocumentError(error instanceof Error ? error.message : 'Could not load brand documents.') }).finally(() => { if (active) setDocumentsLoading(false) })
    return () => { active = false; node?.close(); if (previous?.isConnected) previous.focus() }
  }, [])

  const term = query.trim().toLocaleLowerCase()
  const matches = (values: (string | null | undefined)[]) => values.some(value => value?.toLocaleLowerCase().includes(term))
  const reviewMatches = term ? reviews.filter(item => matches([item.title || 'Untitled submission', item.content_type, item.status, item.audience, item.channel, item.context])) : []
  const documentMatches = term ? documents.filter(item => matches([item.title, item.source_filename, item.category, item.version])) : []

  return <dialog ref={dialog} className="global-search" aria-labelledby="search-title" onKeyDownCapture={event => { if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); onClose() } }} onCancel={event => { event.preventDefault(); onClose() }}>
    <div className="search-heading"><h2 id="search-title">Search workspace</h2><button type="button" onClick={onClose} aria-label="Close search">×</button></div>
    <label htmlFor="global-search-input">Search names and metadata</label>
    <input ref={input} id="global-search-input" type="search" value={query} onChange={event => setQuery(event.target.value)} placeholder="Search reviews and brand documents" />
    {!term && <p>Enter a name or metadata to search.</p>}
    <div className="search-results">
      <section><h3>Reviews</h3>{reviewsLoading ? <p role="status">Loading reviews…</p> : reviewError ? <p role="alert">Reviews unavailable: {reviewError}</p> : term && (reviewMatches.length ? reviewMatches.map(item => <button type="button" key={item.id} onClick={() => onReview(item.id)}><strong>{item.title || 'Untitled submission'}</strong><span>{item.content_type} · {item.status.replaceAll('_', ' ')}</span></button>) : <p>No matching reviews.</p>)}</section>
      <section><h3>Brand Documents</h3>{documentsLoading ? <p role="status">Loading brand documents…</p> : documentError ? <p role="alert">Brand documents unavailable: {documentError}</p> : term && (documentMatches.length ? documentMatches.map(item => <button type="button" key={item.id} onClick={() => onDocument(item.id)}><strong>{item.title}</strong><span>{item.category} · {item.source_filename || 'Filename unavailable'}</span></button>) : <p>No matching documents.</p>)}</section>
    </div>
  </dialog>
}
