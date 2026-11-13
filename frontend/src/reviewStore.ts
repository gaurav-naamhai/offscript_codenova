import type { Draft } from './NewReview'

export type ReviewState = { original: string; text: string; stale: boolean; edits: string[]; comments: string[]; activity: string[] }
export type SampleReviewState = ReviewState & { decisions: { brand: 'open' | 'applied' | 'dismissed'; claim: 'open' | 'applied' | 'dismissed' } }
export type ReviewRecord = { id: string; draft: Draft; status: 'Draft' | 'Unreviewed'; updatedAt: string; review?: ReviewState; fileName?: string }
const KEY = 'inkloom-reviews-v1'
const LEGACY = 'inkloom-demo-draft'
const MIGRATED_ID = 'legacy-draft-v1'
export function loadRecords(): { records: ReviewRecord[]; error: string } {
  try {
    const raw = localStorage.getItem(KEY)
    const parsed: unknown = raw ? JSON.parse(raw) : []
    if (!Array.isArray(parsed)) throw new Error('Invalid stored records')
    const records = parsed as ReviewRecord[]
    const legacy = localStorage.getItem(LEGACY)
    if (legacy && !localStorage.getItem('inkloom-legacy-migrated-v1')) {
      const draft = JSON.parse(legacy) as Draft
      if (draft && typeof draft === 'object' && (draft.title || draft.text || draft.audience || draft.context)) {
        if (!records.some(record => record.id === MIGRATED_ID)) records.push({ id: MIGRATED_ID, draft, status: 'Draft', updatedAt: new Date().toISOString() })
        localStorage.setItem(KEY, JSON.stringify(records))
      }
      localStorage.setItem('inkloom-legacy-migrated-v1', 'yes')
    }
    return { records, error: '' }
  } catch { return { records: [], error: 'Local storage could not be read or migrated. Existing data was left untouched; saving is unavailable in this session.' } }
}
export function writeRecords(records: ReviewRecord[]): string {
  try { localStorage.setItem(KEY, JSON.stringify(records)); return '' }
  catch { return 'Could not save: browser storage is unavailable or full. Changes are only in memory and may be lost.' }
}
export function newId(): string { return crypto.randomUUID() }

const SAMPLE_KEY = 'inkloom-sample-review-v1'
export function loadSampleReview(): { review: SampleReviewState | null; error: string } {
  try { const raw = localStorage.getItem(SAMPLE_KEY); return { review: raw ? JSON.parse(raw) as SampleReviewState : null, error: '' } }
  catch { return { review: null, error: 'Could not restore the sample review from browser storage.' } }
}
export function saveSampleReview(review: SampleReviewState): string {
  try { localStorage.setItem(SAMPLE_KEY, JSON.stringify(review)); return '' }
  catch { return 'Could not save the sample review: browser storage is unavailable or full. Changes are only in memory.' }
}
