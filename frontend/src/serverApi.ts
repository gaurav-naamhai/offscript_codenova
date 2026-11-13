export type RecurringInsights = { top_guidelines: Record<string, unknown>[]; state_counts: Record<string, number>; total_flags: number }
export type ContentType = 'text' | 'image' | 'pdf'
export type ServerSubmission = { id: string; content_type: string; status: string; version: number; text?: string | null; file_name?: string | null; file_mime?: string | null; created_at: string; updated_at: string }
export type SubmissionSummary = { id: string; content_type: string; status: string; version: number; created_at: string; flag_count: number; needs_human_count: number }
export type ServerFlag = { id: string; finding_type: 'brand' | 'claim'; state: string; passage: string; location: string; explanation: string; why_it_matters: string; origin: 'module' | 'fixture' | 'error'; status: string; needs_human: boolean; suggested_correction?: string | null; guideline_ref?: { document: string; passage_ref: string; excerpt: string; source_reference?: string | null } | null; external_sources?: { url: string; excerpt: string }[] }
export type DemoRole = 'creator' | 'manager' | 'authorised_reviewer'
export type ServerComment = { id: string; role: string; text: string; version: number; created_at: string }
export type ServerDecision = { id: string; role: string; decision: string; comment?: string | null; version: number; created_at: string }
export type VersionInfo = { version: number; flag_count: number; needs_human_count: number }
export type AuditEvent = { actor_role: string; action: string; detail: string; timestamp: string; actor?: string | null }
export type RecheckResult = { new_flags: ServerFlag[]; original_flag_gone: boolean; has_needs_human: boolean }
export type ServerDetail = { submission: ServerSubmission; flags: ServerFlag[]; comments: ServerComment[]; decisions: ServerDecision[] }
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
async function request(path: string, init?: RequestInit, timeoutMs = 60000): Promise<Response> {
  const controller = new AbortController(); const timer = window.setTimeout(() => controller.abort(), timeoutMs)
  try {
    const headers = new Headers(init?.headers); if (init?.method === 'POST') headers.set('X-Actor', 'Guest')
    const response = await fetch(`${apiBase}${path}`, { ...init, headers, signal: controller.signal })
    if (!response.ok) {
      let detail = ''
      try {
        const body: unknown = await response.json()
        if (body && typeof body === 'object') {
          if ('detail' in body) {
            if (typeof body.detail === 'string') detail = body.detail
            else if (Array.isArray(body.detail)) {
              detail = body.detail.map(d => typeof d === 'object' && d && 'msg' in d ? `${d.loc ? (d.loc as string[]).join('.') + ': ' : ''}${d.msg}` : JSON.stringify(d)).join('; ')
            } else {
              detail = JSON.stringify(body.detail)
            }
          } else if ('error' in body && body.error && typeof body.error === 'object' && 'message' in body.error && typeof body.error.message === 'string') {
            detail = body.error.message
          }
        }
      } catch { /* no JSON detail */ }
      throw new Error(`Server returned ${response.status}${detail ? `: ${detail}` : ''}`)
    }
    return response
  } catch (error) {
    if (error instanceof Error && error.name === 'AbortError') throw new Error('Request timed out while connecting to the server. The server may still be spinning up; please retry.')
    if (error instanceof TypeError) throw new Error('Could not reach the server. Check your connection, then retry.')
    throw error
  } finally { window.clearTimeout(timer) }
}
export const serverApi = {
  async health(): Promise<{ status: string }> { const data: unknown = await (await request('/health', undefined, 90000)).json(); return data as { status: string } },
  fileUrl(id: string): string { return `${apiBase}/submissions/${encodeURIComponent(id)}/file` },
  async insights(): Promise<RecurringInsights> { const data: unknown = await (await request('/insights/recurring')).json(); if (!data || typeof data !== 'object') throw new Error('Unexpected insights response.'); const result = data as RecurringInsights; if (!Array.isArray(result.top_guidelines) || !result.top_guidelines.every(item => item && typeof item === 'object') || !result.state_counts || typeof result.state_counts !== 'object' || Array.isArray(result.state_counts) || !Object.values(result.state_counts).every(n => typeof n === 'number') || typeof result.total_flags !== 'number') throw new Error('Unexpected insights response.'); return result },
  async list(): Promise<SubmissionSummary[]> { const data: unknown = await (await request('/submissions')).json(); if (!Array.isArray(data)) throw new Error('Unexpected list response.'); return data as SubmissionSummary[] },
  async create(type: ContentType, text: string, file: File | null): Promise<ServerSubmission> { const form = new FormData(); form.append('content_type', type); form.append('role', 'creator'); if (type === 'text') form.append('text', text); else if (file) form.append('file', file); return submission(await (await request('/submissions', { method: 'POST', body: form }, 90000)).json()) },
  async detail(id: string): Promise<ServerDetail> { const data: unknown = await (await request(`/submissions/${encodeURIComponent(id)}`)).json(); if (!data || typeof data !== 'object') throw new Error('Unexpected detail response.'); const d = data as ServerDetail; submission(d.submission); if (!Array.isArray(d.flags) || !Array.isArray(d.comments) || !Array.isArray(d.decisions)) throw new Error('Unexpected detail response.'); return d },
  async check(id: string): Promise<CheckResult> { const data: unknown = await (await request(`/submissions/${encodeURIComponent(id)}/check`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ role: 'creator' }) })).json(); if (!data || typeof data !== 'object') throw new Error('Unexpected check response.'); const result = data as CheckResult; submission(result.submission); if (!Array.isArray(result.flags)) throw new Error('Unexpected check response.'); return result },
  async resolve(id: string, flagId: string, action: 'accept' | 'dismiss', role: DemoRole): Promise<void> { await request(`/submissions/${encodeURIComponent(id)}/flags/${encodeURIComponent(flagId)}/resolution`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ action, role }) }) },
  async recheck(id: string, flagId: string, role: DemoRole): Promise<RecheckResult> { const result: unknown = await (await request(`/submissions/${encodeURIComponent(id)}/flags/${encodeURIComponent(flagId)}/recheck`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ role }) })).json(); if (!result || typeof result !== 'object' || !Array.isArray((result as RecheckResult).new_flags) || typeof (result as RecheckResult).original_flag_gone !== 'boolean' || typeof (result as RecheckResult).has_needs_human !== 'boolean') throw new Error('Unexpected recheck response.'); return result as RecheckResult },
  async comment(id: string, role: DemoRole, text: string): Promise<void> { await request(`/submissions/${encodeURIComponent(id)}/comments`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ role, text }) }) },
  async decide(id: string, role: DemoRole, decision: 'approve' | 'request_changes', comment: string): Promise<void> { await request(`/submissions/${encodeURIComponent(id)}/decision`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ role, decision, comment: comment || null }) }) },
  async revise(id: string, type: ContentType, text: string, file: File | null): Promise<void> { const form = new FormData(); form.append('content_type', type); form.append('role', 'creator'); if (type === 'text') form.append('text', text); else if (file) form.append('file', file); await request(`/submissions/${encodeURIComponent(id)}/revise`, { method: 'POST', body: form }, 90000) },
  async versions(id: string): Promise<VersionInfo[]> { const data: unknown = await (await request(`/submissions/${encodeURIComponent(id)}/versions`)).json(); if (!Array.isArray(data)) throw new Error('Unexpected versions response.'); return data as VersionInfo[] },
  async audit(id: string): Promise<AuditEvent[]> { const data: unknown = await (await request(`/submissions/${encodeURIComponent(id)}/audit`)).json(); if (!Array.isArray(data)) throw new Error('Unexpected audit response.'); return data as AuditEvent[] },
  async file(id: string, type: string): Promise<Blob> { const response = await request(`/submissions/${encodeURIComponent(id)}/file`); const mime = (response.headers.get('content-type') || '').split(';')[0].toLowerCase(); const allowed = type === 'pdf' ? ['application/pdf'] : ['image/png', 'image/jpeg', 'image/webp']; if (!allowed.includes(mime)) throw new Error(`Unexpected file content type: ${mime || 'missing'}. Preview unavailable.`); return new Blob([await response.arrayBuffer()], { type: mime }) },
}
