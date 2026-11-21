export type DemoRole = 'creator' | 'manager' | 'authorised_reviewer'

export type AuthUser = {
  user_id: string
  email: string
  name: string
  role: DemoRole
  org_id: string
  org_name: string
  brand_name: string
}

export type DemoAccount = AuthUser & {
  demo_password: string
}

export type RecurringViolation = {
  rule_or_topic: string
  frequency: number
  severity: string
  guideline_reference?: string | null
  recommendation: string
}

export type AmbiguousGuideline = {
  guideline_title: string
  human_escalation_count: number
  reason_for_ambiguity: string
  suggested_clarification: string
}

export type GovernanceInsights = {
  total_reviews_analyzed: number
  top_recurring_violations: RecurringViolation[]
  ambiguous_guidelines: AmbiguousGuideline[]
  summary_narrative: string
}

export type RecurringInsights = {
  top_guidelines: Record<string, unknown>[]
  state_counts: Record<string, number>
  total_flags: number
  governance_insights?: GovernanceInsights | null
}

export type ContentType = 'text' | 'image' | 'pdf'

export type ServerSubmission = {
  id: string
  content_type: string
  status: string
  version: number
  org_id?: string
  brand_name?: string | null
  created_by_name?: string | null
  processing_stage?: string | null
  processing_error?: string | null
  extracted_text?: string | null
  title?: string | null
  audience?: string | null
  channel?: string | null
  context?: string | null
  text?: string | null
  file_name?: string | null
  file_mime?: string | null
  created_at: string
  updated_at: string
}

export type SubmissionSummary = {
  id: string
  content_type: string
  status: string
  version: number
  org_id?: string
  brand_name?: string | null
  created_by_name?: string | null
  processing_stage?: string | null
  title?: string | null
  audience?: string | null
  channel?: string | null
  context?: string | null
  created_at: string
  flag_count: number
  needs_human_count: number
  readiness_status?: string | null
}

export type EvidenceMode = 'internal_only' | 'external_only' | 'combined' | 'insufficient_evidence'

export type InternalEvidence = {
  document: string
  passage_ref: string
  excerpt: string
  source_reference?: string | null
  document_id?: string | null
  chunk_id?: string | null
  section?: string | null
  page_number?: number | null
  similarity?: number | null
  exact_violated_passage?: string | null
  category?: string | null
  match_type?: string | null
  matched_terms?: string[]
  version?: string | null
}

export type ExternalEvidence = {
  url: string
  excerpt: string
  title?: string | null
  domain?: string | null
  published_date?: string | null
  retrieved_at?: string | null
  evidence_quality?: string | null
  status?: string | null
  error_reason?: string | null
}

export type FlaggedSpan = {
  exact_text: string
  start_char?: number | null
  end_char?: number | null
  surrounding_passage?: string | null
  location_label?: string | null
}

export type SuggestionDetails = {
  suggested_replacement?: string | null
  change_rationale?: string | null
  preserved_entities?: string[]
}

export type ServerFlag = {
  id: string
  submission_id?: string
  version?: number
  finding_type: 'brand' | 'claim'
  state: string
  passage: string
  location: string
  explanation: string
  why_it_matters: string
  origin: 'module' | 'fixture' | 'error'
  status: string
  needs_human: boolean
  suggested_correction?: string | null
  uncertainty_note?: string | null
  guideline_ref?: InternalEvidence | null
  guideline_refs?: InternalEvidence[]
  external_sources?: ExternalEvidence[]
  evidence_mode?: EvidenceMode
  internal_evidence?: InternalEvidence[]
  external_evidence?: ExternalEvidence[]
  exact_violated_passage?: string | null
  flagged_span?: FlaggedSpan | null
  suggestion?: SuggestionDetails | null
}

export type RecurringHint = {
  topic: string
  count: number
  line_number?: number | null
  passage?: string | null
  guideline_reference?: string | null
  message: string
  severity: 'low' | 'medium' | 'high'
}

export type VersionSnapshot = {
  version: number
  content_type: string
  title?: string | null
  audience?: string | null
  channel?: string | null
  context?: string | null
  text?: string | null
  file_name?: string | null
  file_mime?: string | null
  file_size?: number | null
  status: string
  created_at: string
  created_by?: string | null
}

export type ServerComment = {
  id: string
  role: string
  text: string
  version: number
  actor_name?: string | null
  created_at: string
}

export type ServerDecision = {
  id: string
  role: string
  decision: string
  comment?: string | null
  override_unresolved?: boolean
  override_reason?: string | null
  actor_name?: string | null
  version: number
  created_at: string
}

export type VersionInfo = {
  version: number
  flag_count: number
  needs_human_count: number
  status?: string | null
  created_at?: string | null
  content_preview?: string | null
  decision_count?: number
  file_name?: string | null
}

export type AuditEvent = {
  actor_role: string
  action: string
  detail: string
  timestamp: string
  actor?: string | null
}

export type RecheckResult = {
  new_flags: ServerFlag[]
  original_flag_gone: boolean
  has_needs_human: boolean
}

export type ServerDetail = {
  submission: ServerSubmission
  flags: ServerFlag[]
  comments: ServerComment[]
  decisions: ServerDecision[]
  recurring_hints?: RecurringHint[]
  unresolved_blocking_count?: number
  brand_score?: number | null
  fact_score?: number | null
  readiness_status?: string | null
  version_snapshot?: VersionSnapshot | null
}

export type CheckResult = {
  submission: ServerSubmission
  flags: ServerFlag[]
  degraded_modules?: { module: string; error: string }[]
  recurring_hints?: RecurringHint[]
  unresolved_blocking_count?: number
  brand_score?: number | null
  fact_score?: number | null
  readiness_status?: string | null
}

export type SubmissionStatus = {
  id: string
  status: string
  version: number
  processing_stage?: string | null
  processing_error?: string | null
  progress_pct: number
  flag_count: number
  updated_at: string
}

export type BrandDocument = {
  id: string
  title: string
  category: string
  version: string
  is_active: boolean
  source_filename?: string | null
  created_at?: string
  chunks_count?: number
  org_id?: string
  brand_name?: string
  previous_version_id?: string | null
}

export type BrandConstitution = {
  org_id: string
  brand_name?: string
  documents_count: number
  approved_facts: string[]
  forbidden_terms: string[]
  preferred_terms: string[]
  tone_pillars: string[]
  brand_colors: string[]
  expiry_notices: string[]
}

export type GuidelineRectification = {
  id: string
  org_id: string
  issue_type: 'unclear' | 'conflicting' | 'duplicate' | 'expired'
  severity: 'low' | 'medium' | 'high'
  document_id: string
  document_title: string
  document_version: string
  chunk_id: string
  section?: string | null
  original_text: string
  conflicting_document?: string | null
  conflicting_text?: string | null
  problem_explanation: string
  suggested_wording: string
  evidence_count: number
  status: 'pending' | 'approved' | 'dismissed'
  approved_wording?: string | null
  reviewed_by?: string | null
  reviewed_at?: string | null
  new_document_id?: string | null
  new_version?: string | null
  created_at: string
}

export type ComplianceCertificate = {
  certificate_id: string
  generated_at: string
  organisation: string
  submission: Record<string, unknown>
  scores: Record<string, unknown>
  evidence_citations: {
    brand_guidelines_consulted: string[]
    external_sources_consulted: string[]
  }
  decisions: ServerDecision[]
  audit_events_count: number
}

const TOKEN_KEY = 'inkloom_auth_token'
const USER_KEY = 'inkloom_auth_user'
export const AUTH_SESSION_EVENT = 'inkloom-auth-session-changed'
export const isAuthStorageKey = (key: string | null) => key === null || key === TOKEN_KEY || key === USER_KEY

export function getStoredToken(): string {
  try {
    return window.localStorage.getItem(TOKEN_KEY) || ''
  } catch {
    return ''
  }
}

export function getStoredUser(): AuthUser | null {
  try {
    const raw = window.localStorage.getItem(USER_KEY)
    return raw ? (JSON.parse(raw) as AuthUser) : null
  } catch {
    return null
  }
}

export function setAuthSession(token: string, user: AuthUser): void {
  try {
    window.localStorage.setItem(TOKEN_KEY, token)
    window.localStorage.setItem(USER_KEY, JSON.stringify(user))
    window.dispatchEvent(new Event(AUTH_SESSION_EVENT))
  } catch {
    // ignore storage quota failures
  }
}

export function clearAuthSession(): void {
  try {
    window.localStorage.removeItem(TOKEN_KEY)
    window.localStorage.removeItem(USER_KEY)
    window.dispatchEvent(new Event(AUTH_SESSION_EVENT))
  } catch {
    // ignore
  }
}

const defaultBase = 'https://offscript-codenova.onrender.com'
export const apiBase = (import.meta.env.VITE_API_BASE_URL || defaultBase).replace(/\/+$/, '')
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

function submission(value: unknown): ServerSubmission {
  if (!value || typeof value !== 'object') throw new Error('Unexpected submission response: expected an object.')
  const s = value as Record<string, unknown>
  if (
    typeof s.id !== 'string' ||
    !uuid.test(s.id) ||
    typeof s.content_type !== 'string' ||
    typeof s.status !== 'string' ||
    typeof s.version !== 'number' ||
    typeof s.created_at !== 'string' ||
    typeof s.updated_at !== 'string'
  ) {
    throw new Error('Unexpected submission response: required fields or server UUID are missing.')
  }
  return s as ServerSubmission
}

async function request(path: string, init?: RequestInit, timeoutMs = 90000): Promise<Response> {
  const controller = new AbortController()
  const timer = window.setTimeout(() => controller.abort(), timeoutMs)
  try {
    const headers = new Headers(init?.headers)
    const token = getStoredToken()
    const user = getStoredUser()
    if (token) {
      headers.set('Authorization', `Bearer ${token}`)
    }
    if (user?.name && !headers.has('X-Actor')) {
      headers.set('X-Actor', user.name)
    }
    const response = await fetch(`${apiBase}${path}`, { ...init, headers, signal: controller.signal })
    if (!response.ok) {
      if (response.status === 401 && path !== '/auth/login') {
        clearAuthSession()
      }
      let detail = ''
      try {
        const body: unknown = await response.json()
        if (body && typeof body === 'object') {
          if ('detail' in body) {
            detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail)
          } else if (
            'error' in body &&
            body.error &&
            typeof body.error === 'object' &&
            'message' in body.error &&
            typeof body.error.message === 'string'
          ) {
            detail = body.error.message
          }
        }
      } catch {
        /* no JSON detail */
      }
      throw new Error(`Server returned ${response.status}${detail ? `: ${detail}` : ''}`)
    }
    return response
  } catch (error) {
    if (error instanceof Error && error.name === 'AbortError') {
      throw new Error('Request timed out while waiting for server response. Refresh status before retrying.')
    }
    if (error instanceof TypeError) {
      throw new Error('Could not reach the server. Check your connection and CORS settings, then retry.')
    }
    throw error
  } finally {
    window.clearTimeout(timer)
  }
}

export const serverApi = {
  async authAccounts(): Promise<DemoAccount[]> {
    const data = (await (await request('/auth/accounts', undefined, 20000)).json()) as { accounts?: DemoAccount[] }
    return data.accounts || []
  },

  async login(email: string, password: string): Promise<{ access_token: string; user: AuthUser }> {
    const res = (await (
      await request('/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password }),
      }, 30000)
    ).json()) as { access_token: string; user: AuthUser }
    setAuthSession(res.access_token, res.user)
    return res
  },

  async register(payload: {
    email: string
    password: string
    name: string
    role: DemoRole
    org_name: string
    brand_name?: string
  }): Promise<{ access_token: string; user: AuthUser }> {
    const res = (await (
      await request('/auth/register', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
    ).json()) as { access_token: string; user: AuthUser }
    setAuthSession(res.access_token, res.user)
    return res
  },

  async me(): Promise<AuthUser> {
    const data = (await (await request('/auth/me')).json()) as { user: AuthUser }
    return data.user
  },

  async insights(): Promise<RecurringInsights> {
    const data: unknown = await (await request('/insights/recurring')).json()
    if (!data || typeof data !== 'object') throw new Error('Unexpected insights response.')
    return data as RecurringInsights
  },

  async list(): Promise<SubmissionSummary[]> {
    const data: unknown = await (await request('/submissions')).json()
    if (!Array.isArray(data)) throw new Error('Unexpected list response.')
    return data as SubmissionSummary[]
  },

  async create(
    type: ContentType,
    text: string,
    file: File | null,
    title?: string,
    audience?: string,
    channel?: string,
    context?: string
  ): Promise<ServerSubmission> {
    const user = getStoredUser()
    const form = new FormData()
    form.append('content_type', type)
    form.append('role', user?.role || 'creator')
    if (title) form.append('title', title)
    if (audience) form.append('audience', audience)
    if (channel) form.append('channel', channel)
    if (context) form.append('context', context)
    if (type === 'text') form.append('text', text)
    else if (file) form.append('file', file)
    return submission(await (await request('/submissions', { method: 'POST', body: form })).json())
  },

  async detail(id: string, version?: number): Promise<ServerDetail> {
    const q = version != null ? `?version=${encodeURIComponent(String(version))}` : ''
    const data: unknown = await (await request(`/submissions/${encodeURIComponent(id)}${q}`)).json()
    if (!data || typeof data !== 'object') throw new Error('Unexpected detail response.')
    const d = data as ServerDetail
    submission(d.submission)
    if (!Array.isArray(d.flags) || !Array.isArray(d.comments) || !Array.isArray(d.decisions)) {
      throw new Error('Unexpected detail response.')
    }
    return d
  },

  async check(id: string): Promise<CheckResult> {
    const user = getStoredUser()
    const data: unknown = await (
      await request(`/submissions/${encodeURIComponent(id)}/check`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ role: user?.role || 'creator', async_mode: false }),
      })
    ).json()
    return data as CheckResult
  },

  async checkAsync(id: string): Promise<CheckResult> {
    const user = getStoredUser()
    const data: unknown = await (
      await request(`/submissions/${encodeURIComponent(id)}/check`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ role: user?.role || 'creator', async_mode: true }),
      })
    ).json()
    return data as CheckResult
  },

  async status(id: string): Promise<SubmissionStatus> {
    return (await (await request(`/submissions/${encodeURIComponent(id)}/status`)).json()) as SubmissionStatus
  },

  async retryCheck(id: string, asyncMode = true): Promise<CheckResult> {
    const user = getStoredUser()
    return (await (
      await request(`/submissions/${encodeURIComponent(id)}/retry-check`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ role: user?.role || 'creator', async_mode: asyncMode }),
      })
    ).json()) as CheckResult
  },

  async draftHints(text: string): Promise<RecurringHint[]> {
    const res = (await (
      await request('/submissions/draft-hints', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text }),
      })
    ).json()) as { hints?: RecurringHint[] }
    return res.hints || []
  },

  async resolve(id: string, flagId: string, action: 'accept' | 'dismiss', role?: DemoRole): Promise<void> {
    const user = getStoredUser()
    const effectiveRole = role || user?.role || 'creator'
    await request(`/submissions/${encodeURIComponent(id)}/flags/${encodeURIComponent(flagId)}/resolution`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action, role: effectiveRole }),
    })
  },

  async recheck(id: string, flagId: string, role?: DemoRole): Promise<RecheckResult> {
    const user = getStoredUser()
    const effectiveRole = role || user?.role || 'creator'
    const result: unknown = await (
      await request(`/submissions/${encodeURIComponent(id)}/flags/${encodeURIComponent(flagId)}/recheck`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ role: effectiveRole }),
      })
    ).json()
    return result as RecheckResult
  },

  async comment(id: string, role: DemoRole, text: string): Promise<void> {
    await request(`/submissions/${encodeURIComponent(id)}/comments`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ role, text }),
    })
  },

  async decide(
    id: string,
    role: DemoRole,
    decision: 'approve' | 'request_changes',
    comment = '',
    overrideUnresolved = false,
    overrideReason = ''
  ): Promise<void> {
    await request(`/submissions/${encodeURIComponent(id)}/decision`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        role,
        decision,
        comment: comment || null,
        override_unresolved: overrideUnresolved,
        override_reason: overrideReason || null,
      }),
    })
  },

  async revise(
    id: string,
    type: ContentType,
    text: string,
    file: File | null,
    title?: string,
    audience?: string,
    channel?: string,
    context?: string,
    createNewVersion = true
  ): Promise<ServerSubmission> {
    const user = getStoredUser()
    const form = new FormData()
    form.append('content_type', type)
    form.append('role', user?.role || 'creator')
    form.append('create_new_version', createNewVersion ? 'true' : 'false')
    if (title) form.append('title', title)
    if (audience) form.append('audience', audience)
    if (channel) form.append('channel', channel)
    if (context) form.append('context', context)
    if (type === 'text') form.append('text', text)
    else if (file) form.append('file', file)
    return submission(await (await request(`/submissions/${encodeURIComponent(id)}/revise`, { method: 'POST', body: form })).json())
  },

  async versions(id: string): Promise<VersionInfo[]> {
    const data: unknown = await (await request(`/submissions/${encodeURIComponent(id)}/versions`)).json()
    if (!Array.isArray(data)) throw new Error('Unexpected versions response.')
    return data as VersionInfo[]
  },

  async audit(id: string): Promise<AuditEvent[]> {
    const data: unknown = await (await request(`/submissions/${encodeURIComponent(id)}/audit`)).json()
    if (!Array.isArray(data)) throw new Error('Unexpected audit response.')
    return data as AuditEvent[]
  },

  async certificate(id: string): Promise<ComplianceCertificate> {
    return (await (await request(`/submissions/${encodeURIComponent(id)}/certificate`)).json()) as ComplianceCertificate
  },

  async file(id: string, type: string, version?: number): Promise<Blob> {
    const q = version != null ? `?version=${encodeURIComponent(String(version))}` : ''
    const response = await request(`/submissions/${encodeURIComponent(id)}/file${q}`)
    const mime = (response.headers.get('content-type') || '').split(';')[0].toLowerCase()
    const allowed = type === 'pdf' ? ['application/pdf'] : ['image/png', 'image/jpeg', 'image/webp']
    if (!allowed.includes(mime)) throw new Error(`Unexpected file content type: ${mime || 'missing'}. Preview unavailable.`)
    return new Blob([await response.arrayBuffer()], { type: mime })
  },

  async listBrandDocs(includeInactive = false): Promise<BrandDocument[]> {
    const q = includeInactive ? '?include_inactive=true' : ''
    const data = (await (await request(`/brand-docs${q}`)).json()) as { documents?: BrandDocument[] }
    return data.documents || []
  },

  async uploadBrandDoc(form: FormData): Promise<BrandDocument> {
    return (await (await request('/brand-docs', { method: 'POST', body: form })).json()) as BrandDocument
  },

  async deactivateBrandDoc(docId: string): Promise<void> {
    await request(`/brand-docs/${encodeURIComponent(docId)}`, { method: 'DELETE' })
  },

  async brandDocVersions(docId: string): Promise<BrandDocument[]> {
    const data = (await (await request(`/brand-docs/${encodeURIComponent(docId)}/versions`)).json()) as {
      versions?: BrandDocument[]
    }
    return data.versions || []
  },

  async brandConstitution(): Promise<BrandConstitution> {
    return (await (await request('/brand-constitution')).json()) as BrandConstitution
  },

  async listRectifications(): Promise<GuidelineRectification[]> {
    const data = (await (await request('/brand-docs/rectifications')).json()) as {
      rectifications?: GuidelineRectification[]
    }
    return data.rectifications || []
  },

  async scanRectifications(): Promise<{ rectifications: GuidelineRectification[]; scanned_chunks: number }> {
    return (await (await request('/brand-docs/rectifications/scan', { method: 'POST' })).json()) as {
      rectifications: GuidelineRectification[]
      scanned_chunks: number
    }
  },

  async approveRectification(
    rectId: string,
    approvedWording: string,
    comment = ''
  ): Promise<{ rectification: GuidelineRectification; new_document: BrandDocument }> {
    return (await (
      await request(`/brand-docs/rectifications/${encodeURIComponent(rectId)}/approve`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ approved_wording: approvedWording, comment: comment || null }),
      })
    ).json()) as { rectification: GuidelineRectification; new_document: BrandDocument }
  },

  async dismissRectification(rectId: string, reason = ''): Promise<void> {
    await request(`/brand-docs/rectifications/${encodeURIComponent(rectId)}/dismiss`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ reason: reason || null }),
    })
  },

  async seed(): Promise<void> {
    await request('/demo/seed', { method: 'POST' })
  },

  async pingHealth(timeoutMs = 5000): Promise<{ ok: boolean; latencyMs: number }> {
    const controller = new AbortController()
    const timer = window.setTimeout(() => controller.abort(), timeoutMs)
    const started = performance.now()
    try {
      const response = await fetch(`${apiBase}/health`, {
        method: 'GET',
        cache: 'no-store',
        signal: controller.signal,
      })
      return { ok: response.ok, latencyMs: Math.round(performance.now() - started) }
    } catch {
      return { ok: false, latencyMs: Math.round(performance.now() - started) }
    } finally {
      window.clearTimeout(timer)
    }
  },
}

export const DEFAULT_DEMO_ACCOUNT: {
  email: string
  password: string
  user: AuthUser
} = {
  email: 'creator@brightleaf.co',
  password: 'brightleaf123',
  user: {
    user_id: 'u-bl-creator',
    email: 'creator@brightleaf.co',
    name: 'Maya Chen',
    role: 'creator',
    org_id: 'brightleaf',
    org_name: 'BrightLeaf Organics',
    brand_name: 'BrightLeaf',
  },
}
