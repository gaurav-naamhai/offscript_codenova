export type ContentType = 'text' | 'image' | 'pdf'
export type ServerSubmission = { id: string; content_type: string; status: string; version: number; text?: string | null; file_name?: string | null; file_mime?: string | null; created_at: string; updated_at: string }
export type SubmissionSummary = { id: string; content_type: string; status: string; version: number; created_at: string; flag_count: number; needs_human_count: number }
export type ServerFlag = { id: string; finding_type: 'brand' | 'claim'; state: string; passage: string; location: string; explanation: string; why_it_matters: string; origin: 'module' | 'fixture' | 'error'; status: string; needs_human: boolean; suggested_correction?: string | null; guideline_ref?: { document: string; passage_ref: string; excerpt: string; source_reference?: string | null } | null; external_sources?: { url: string; excerpt: string }[] }
export type ServerDetail = { submission: ServerSubmission; flags: ServerFlag[]; comments: unknown[]; decisions: unknown[] }
export type CheckResult = { submission: ServerSubmission; flags: ServerFlag[]; degraded_modules?: { module: string; error: string }[] }
const defaultBase = 'https://offscript-codenova.onrender.com'
export const apiBase = (import.meta.env.VITE_API_BASE_URL || defaultBase).replace(/\/+$/, '')
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i
function submission(value: unknown): ServerSubmission {
  if (!value || typeof value !== 'object') throw new Error('Unexpected submission response: expected an object.')
  const s = value as Record<string, unknown>
  if (typeof s.id !== 'string' || !uuid.test(s.id) || typeof s.content_type !== 'string' || typeof s.status !== 'string' || typeof s.version !== 'number' || typeof s.created_at !== 'string' || typeof s.updated_at !== 'string') throw new Error('Unexpected submission response: required fields or server UUID are missing.')
  return s as ServerSubmission
}
async function request(path: string, init?: RequestInit): Promise<Response> {
  const controller = new AbortController(); const timer = window.setTimeout(() => controller.abort(), 60000)
  try {
    const response = await fetch(`${apiBase}${path}`, { ...init, signal: controller.signal })
    if (!response.ok) { let detail = ''; try { const body: unknown = await response.json(); if (body && typeof body === 'object' && 'detail' in body) detail = JSON.stringify(body.detail) } catch { /* no JSON detail */ } throw new Error(`Server returned ${response.status}${detail ? `: ${detail}` : ''}`) }
    return response
  } catch (error) {
    if (error instanceof Error && error.name === 'AbortError') throw new Error('Request timed out while the server may be starting. Check the list before trying creation again.')
    if (error instanceof TypeError) throw new Error('Could not reach the server. Check your connection and CORS settings, then retry safe reads.')
    throw error
  } finally { window.clearTimeout(timer) }
}
export const serverApi = {
  async list(): Promise<SubmissionSummary[]> { const data: unknown = await (await request('/submissions')).json(); if (!Array.isArray(data)) throw new Error('Unexpected list response.'); return data as SubmissionSummary[] },
  async create(type: ContentType, text: string, file: File | null): Promise<ServerSubmission> { const form = new FormData(); form.append('content_type', type); form.append('role', 'creator'); if (type === 'text') form.append('text', text); else if (file) form.append('file', file); return submission(await (await request('/submissions', { method: 'POST', body: form })).json()) },
  async detail(id: string): Promise<ServerDetail> { const data: unknown = await (await request(`/submissions/${encodeURIComponent(id)}`)).json(); if (!data || typeof data !== 'object') throw new Error('Unexpected detail response.'); const d = data as ServerDetail; submission(d.submission); if (!Array.isArray(d.flags) || !Array.isArray(d.comments) || !Array.isArray(d.decisions)) throw new Error('Unexpected detail response.'); return d },
  async check(id: string): Promise<CheckResult> { const data: unknown = await (await request(`/submissions/${encodeURIComponent(id)}/check`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ role: 'creator' }) })).json(); if (!data || typeof data !== 'object') throw new Error('Unexpected check response.'); const result = data as CheckResult; submission(result.submission); if (!Array.isArray(result.flags)) throw new Error('Unexpected check response.'); return result },
  async file(id: string, type: string): Promise<Blob> { const response = await request(`/submissions/${encodeURIComponent(id)}/file`); const mime = (response.headers.get('content-type') || '').split(';')[0].toLowerCase(); const allowed = type === 'pdf' ? ['application/pdf'] : ['image/png', 'image/jpeg', 'image/webp']; if (!allowed.includes(mime)) throw new Error(`Unexpected file content type: ${mime || 'missing'}. Preview unavailable.`); return new Blob([await response.arrayBuffer()], { type: mime }) },
}
