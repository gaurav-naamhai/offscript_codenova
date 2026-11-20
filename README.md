# Inkloom AI — Intelligent Brand Governance Platform (Team OFFSCRIPT)

## Current implementation and verification

The review UI supports text, image and PDF submissions, organisation-scoped guideline retrieval, findings, version history, and Creator → Manager → Authorised Reviewer decisions. A new or edited draft is **not checked** until its current version completes review; an incomplete check is not an approval. A justified override remains visible with its unresolved risks. The certificate endpoint exports a status report or approval record as JSON; it is **not cryptographically signed**.

Active organisation guidelines are used when retrieval is configured. Generic fixture rules are available only in explicit mock mode, and a retrieval failure is reported as incomplete rather than silently substituted. Claims require matching approved facts or relevant evidence; unapproved company domains cannot substantiate an organisation-specific offer. External source metadata and lexical relevance do not alone prove a claim. The review provider, OCR, web search, and database paths still need live-service validation. See [backend testing notes](backend/TESTING_NOTES.md) for tested scope and deployment checks.

The earlier Round 2 mapping below records the team's historical work; its old test counts and performance statements are superseded by the testing notes.

> **See tomorrow's headline today, and fix the mistake before it reaches your customers.**

Inkloom AI is an intelligent pre-publication brand-governance platform built for organisations publishing across multiple teams, agencies, and AI tools. Organisations perform a one-time upload of their approved brand guidelines, facts, and identity assets; creators can then submit text drafts, images, or PDFs to be verified against **both** their isolated internal brand knowledge base and live external evidence — with explainable, evidence-first findings, minimal intent-preserving corrections, recurring-mistake coaching, guideline rectification, and strict role-based human approval.

---

## 1. Problem & Solution Overview

### The Challenge
Growing organisations produce content across employees, agencies, and generative AI tools. Without pre-publication guardrails, unverified claims, outdated pricing/facts, off-brand tone or visuals, and accessibility failures damage credibility before publication.

### How OFFSCRIPT Solves It
1. **One-Time Brand Constitution Setup (Org-Isolated):** Upload brand PDFs, images, or text playbooks once. Inkloom chunks rules semantically, tags rule categories (`approved_fact`, `terminology`, `tone`, `visual`, `claim_policy`, `legal`) and expiry hints, builds an auto-compiled **Brand Constitution** (approved facts, forbidden terms, official color swatches), and indexes 768-dim embeddings in Supabase `pgvector` strictly isolated per organisation.
2. **Review findings:** The interface groups brand and claim findings with their available internal and external evidence. Missing or incomplete evidence remains visible for human review.
3. **Explainable Flags & Anti-Fabrication Corrections:** Every flag anchors to exact character spans (`FlaggedSpan`), verbatim guideline passages, or external URLs. Candidate corrections undergo programmatic entity protection and anti-fabrication validation before surfacing.
4. **Proactive Recurring-Mistake Coaching:** Detects repeated mistakes both live while typing (`POST /submissions/draft-hints`) and post-review (`recurring_hints` with line numbers and historical frequency).
5. **Guideline Rectification Loop:** Audits active brand guidelines for **unclear**, **conflicting**, **duplicate**, and **expired** rules; lets a Manager edit and approve clearer wording, automatically publishing a new active guideline version (`v1.0 → v1.1`) while preserving previous versions.
6. **Reliable Human-in-the-Loop Approvals:** Enforces real Bearer-token authentication, separation of duties (creators cannot approve their own content; the same person cannot act as both Manager and Final Reviewer), unresolved-flag approval gates (requiring resolution or a justified authorised override), immutable version snapshots on edits/re-approvals, and exportable compliance sign-off certificates.

---

## 2. System Architecture & Key Technical Decisions

```mermaid
flowchart LR
    U[Creator / Manager / Final Reviewer] -->|Bearer Auth + Org Scope| FE[React + Vite Minimal Motion UI]
    FE -->|REST + Async Polling| API[FastAPI Backend]

    subgraph Core Pipeline
        EX[PyMuPDF + Gemini Vision OCR] --> RAG[Hybrid Multi-Query Brand RAG<br/>Semantic + Lexical + Fact Boost]
        EX --> CU[Shared Gemini Content Understanding]
        CU --> PAR
        RAG --> PAR
        subgraph PAR [Concurrent Verification]
            BV[Brand & Visual Accessibility<br/>+ WCAG Contrast Math Filter]
            CV[Claim Verification<br/>Approved Facts First + Exa/TinyFish]
        end
        PAR --> SYN[Flag Synthesis + Anti-Fabrication Recheck]
    end

    API --> Core Pipeline
    RAG <--> SB[(Supabase pgvector + Brand Docs)]
    CV <--> EXT[Exa Search + TinySearch/TinyFetch]
    API --> GOV[Guideline Rectification + Recurring Hints + Audit Trail]
```

### Main Technical Decisions
- **Multi-Stage Hybrid Brand RAG (`backend/retrieval/brand_rag.py` & `chunker.py`):** Pure cosine vector search often misses exact banned words, numbers, or product specs, while naive chunking splits mid-rule. We implemented rule-aware semantic chunking (`rule_category`, keywords, expiry detection) combined with query decomposition, pgvector similarity, lexical/exact-term scoring, approved-fact boosting, relevance thresholding, and strict per-organisation filtering.
- **Organisation-Scoped Retrieval:** Brand document queries are scoped to an organisation and active version. Publication and synthetic legacy backfill after migrations 001 and 002 passed disposable PostgreSQL tests. See [testing notes](backend/TESTING_NOTES.md) before rollout.
- **Approved Brand Facts Priority & Unrelated-Company Filtering (`claim_verification.py`, `external_search.py`):** Claims about the organisation's own products/policies check approved internal facts first; external search results referencing unrelated companies or off-topic domains are rejected as `entity_matched=False` rather than causing false contradictions.
- **Extraction & Background Review (`pipeline.py`, `main.py`):** PDF/image extraction is shared with parallel brand and claim checks. The frontend starts a saved check, then polls status sequentially; failed or abandoned checks retain their submission ID for an explicit retry. An unreadable file is incomplete, and a server restart still loses in-memory submissions.
- **Deterministic Guardrails Over Raw LLM Outputs:**
  - *WCAG Contrast Math (`visual_accessibility.py`):* Re-computes contrast ratios via `evaluate_wcag_contrast()` and drops false-positive contrast warnings when pairs already pass WCAG 2.1 AA (`>= 4.5:1` normal, `>= 3.0:1` large/UI).
  - *Anti-Fabrication (`suggestions_corrections.py`):* Rejects candidate rewrites that introduce ungrounded numeric specs, unverified multi-word entities, or bloated product descriptions.
  - *Verbatim Guideline Verification (`brand_verification.py`):* `extract_verbatim_guideline_passage()` prevents paraphrased rules from masquerading as exact quotes.

---

## 3. Technology Stack, APIs, Models & Services

| Layer | Technologies / APIs / Libraries | Role |
|---|---|---|
| **Frontend** | React 19, TypeScript, Vite 8, `@fontsource/dm-serif-display`, `@fontsource/manrope`, CSS Motion (`motion.css`) | Minimal motion UI, URL hash routing, local unsent-draft persistence, Brand-vs-External lens selector, async stepper, Brand Constitution & Guideline Rectification screens |
| **Backend API** | FastAPI, Pydantic v2, Uvicorn, Starlette threadpool + background worker, HMAC-SHA256 stateless auth | REST API, RBAC, org isolation, approval gates, immutable version snapshots, audit log, WCAG contrast endpoint, compliance certificate export |
| **AI Models** | Google GenAI SDK (`google-genai`), provider/model configuration in backend settings, explicit offline `MOCK_AI` test mode | Multimodal text/image/PDF understanding, OCR fallback, claim and brand assessment; live provider accuracy remains to be verified |
| **Database & RAG** | Supabase (`supabase-py`), PostgreSQL + `pgvector` (`match_brand_chunks` RPC), thread-safe in-memory repository fallback | Brand document/chunk storage, vector similarity search, submission/version/comment/decision/audit persistence |
| **Document & OCR** | PyMuPDF (`pymupdf` / `fitz`), Gemini Vision OCR | Digital PDF extraction, 130-DPI rasterization for scanned PDF pages & visual PDF rendering, quantized image color palette sampling |
| **External Evidence** | Exa Search (`api.exa.ai/search`), TinyFish (`TinySearch` & `TinyFetch`), `httpx` | External claim discovery, full-page markdown retrieval, publication-date extraction, timeout/unavailable degradation |
| **Testing & Lint** | `pytest`, `anyio`, `tsc -b`, `oxlint` | 172 backend automated tests + frontend TypeScript & lint verification |

---

## 4. Round 2 Improvement & QA Fix Mapping

| Priority / Improvement | What Was Implemented | Files & Endpoints | Verified By (`pytest` / build) |
|---|---|---|---|
| **1. Login, Real Authorisation & Org Isolation** | Signed Bearer token auth (`auth.py`), 3 isolated orgs (BrightLeaf, Nike, Inkloom), Creator/Manager/Authorised Reviewer RBAC enforced server-side, creator cannot self-approve, manager cannot double-sign final approval, strict `org_id` scoping on submissions, RAG chunks, brand docs & insights | `backend/app/auth.py`, `backend/app/main.py`, `backend/retrieval/brand_rag.py`, `frontend/src/AuthModal.tsx`, `frontend/src/serverApi.ts` | `test_auth_login_failures_and_role_spoofing_blocked`, `test_separation_of_duties_prevents_self_approval`, `test_cross_organisation_isolation_submissions_and_rag` |
| **2. Review Accuracy & Hybrid Brand RAG** | Rule-aware chunking + Brand Constitution compiler, hybrid vector + lexical + approved-fact RAG, approved facts prioritized over external sites, unrelated-company rejection (`filter_relevant_external_evidence`), anti-fabrication guard blocking invented product descriptions/metrics, no false warnings on compliant text | `backend/retrieval/chunker.py`, `backend/retrieval/brand_rag.py`, `backend/retrieval/external_search.py`, `backend/app/ai/claim_verification.py`, `backend/app/ai/brand_verification.py`, `backend/app/ai/suggestions_corrections.py` | `test_external_evidence_rejects_unrelated_company_and_prioritizes_brand_facts`, `test_anti_fabrication_blocks_invented_descriptions_and_compliant_has_no_false_warnings` |
| **3. Reliable Approvals & Immutable Versioning** | Blocks approval (`409`) when open blocking flags exist unless an authorised override with `>=10`-char justification is recorded; editing approved/reviewed text or replacing files preserves exact `VersionSnapshot` of prior version, bumps `version`, resets status to `draft`, and logs `approval_invalidated` | `backend/app/models.py`, `backend/app/repository.py`, `backend/app/main.py` (`POST /decision`, `POST /revise`, `GET /submissions/{id}?version=v`, `GET /certificate`), `frontend/src/ReviewWorkspace.tsx` | `test_unsafe_approval_blocked_unless_authorised_override_and_edit_invalidates_approval`, `test_versions_preservation_and_query_by_version` |
| **4. Guideline Rectification** | Scans active org rules + historical escalations for `unclear`, `conflicting`, `duplicate`, and `expired` clauses; Manager edits & approves clearer wording, creating active `v1.1` while archiving `v1.0` for version history and immediately enforcing `v1.1` in future reviews | `backend/app/ai/guideline_rectification.py`, `backend/retrieval/brand_rag.py`, `backend/app/main.py` (`/brand-docs/rectifications*`, `/brand-docs/{id}/versions`), `frontend/src/BrandKnowledge.tsx` | `test_guideline_rectification_scan_approve_and_version_preservation` |
| **5. Complete PDF/Image Journeys, Async Polling & UX Fixes** | Fixed Gemini model 404 fallback, eliminated passing-contrast false positives via WCAG math, added `async_mode=true` background execution + `/status` polling + `/retry-check`, image/PDF file replacement & resubmission, `localStorage` unsent-draft persistence, URL hash routing (refresh stays on saved review), Brand-vs-External primary lens selector, and minimal CSS motion | `backend/app/ai/client.py`, `backend/app/ai/visual_accessibility.py`, `backend/app/pipeline.py`, `backend/retrieval/extractor.py`, `frontend/src/App.tsx`, `frontend/src/NewReview.tsx`, `frontend/src/ReviewWorkspace.tsx`, `frontend/src/motion.css` | `test_contrast_false_positive_filter_drops_passing_pairs`, `test_async_check_status_retry_draft_hints_and_recurring_coaching`, `npm run build`, `npm run lint` |
| **6. Standout Inkloom Capabilities** | Auto-compiled **Brand Constitution** (`GET /brand-constitution`), live typing & post-review **Recurring Mistake Coaching** (`POST /submissions/draft-hints`, `recurring_hints`), and exportable **Compliance Sign-Off Certificate** (`GET /submissions/{id}/certificate`) | `backend/retrieval/chunker.py`, `backend/app/ai/governance_intelligence.py`, `backend/app/main.py`, `frontend/src/BrandKnowledge.tsx`, `frontend/src/NewReview.tsx`, `frontend/src/ReviewWorkspace.tsx` | `test_async_check_status_retry_draft_hints_and_recurring_coaching` |

---

## 5. Privacy, Confidentiality & External Service Disclosures

- **Multi-Organisation Isolation:** Every submission, version snapshot, uploaded file, brand document, RAG chunk, rectification proposal, and governance metric is scoped by `org_id`. Cross-organisation access returns `404` and cross-organisation RAG retrieval is blocked at query time.
- **Role-Based Access & Separation of Duties:** Signed HMAC-SHA256 Bearer tokens identify `user_id`, `role`, and `org_id`. Creators cannot approve their own work, and the Manager who approves Stage 1 cannot double-sign Final Approval.
- **External AI & Web Disclosure:** `GET /disclosures` transparently reports enabled third-party providers (Gemini, Exa, TinyFish, Supabase) alongside the mandatory human-in-the-loop notice: Inkloom AI never auto-publishes content.
- **No Fabricated Evidence:** Missing metadata, unreachable URLs (`status="unavailable"`), or excluded unrelated-company results never produce synthetic reliability ratings; they escalate to `insufficient_evidence` for human review.

---

## 6. Verification & Running Locally

### Observed Verification Results
- **Backend Automated Tests (`pytest`):** **196 passed** on 20 November 2026 using synthetic/local fixtures. See [testing notes](backend/TESTING_NOTES.md) for scope and limitations.
- **Live Supabase Isolation Check:** Verified `list_brand_docs(org_id='brightleaf')` returns `['BrightLeaf-guidelines']` and `list_brand_docs(org_id='nike')` returns `['nike_brand_identity_detailed', 'identity']` with zero cross-org leakage.
- **Frontend Build:** `tsc -b && vite build` passed on 20 November 2026. Lint was not rerun for this update.

### Quick Start
```bash
# 1. Backend
cd backend
python -m pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# 2. Frontend
cd frontend
npm install
npm run dev
```

### Demo Sign-In Accounts (Grouped by Organisation)
The sign-in screen fetches the currently available demo identities from the backend. These are demonstration accounts, not production account security or a durable identity store.

---

## 7. Current Limitations & Roadmap

- **Limitations:** Submission persistence currently defaults to `InMemorySubmissionRepository` (while Brand RAG & chunks persist in Supabase `pgvector`); user accounts use seeded/in-memory org credentials (`SupabaseRepository` DDL wiring for submissions is next); video/audio frame-by-frame review is planned after text, image, and PDF flows.
- **Roadmap:** Full PostgreSQL submission persistence via `SupabaseRepository`, native CMS pre-flight connectors (WordPress, Webflow, HubSpot), Figma/Canva asset plugins, and video/audio transcript verification.

---

## 8. Team Contributions

- **Ken Rodrigues (Retrieval & Evidence):** Supabase `pgvector` RAG, rule-aware chunking, Brand Constitution compilation, org-isolated document versioning & rectification storage, Exa + TinyFish external evidence discovery/filtering, and PyMuPDF + Gemini Vision OCR extraction.
- **Sera Rumao (AI Intelligence & Verification):** Gemini multimodal content understanding, verbatim-grounded brand verification, approved-fact-first claim verification, entity-preserving anti-fabrication corrections, visual/WCAG contrast filtering, guideline rectification detection, and governance/recurring-hint intelligence.
- **Gaurav Jha (Backend & Governance Operations):** FastAPI REST architecture, HMAC-SHA256 authentication, RBAC & separation-of-duties enforcement, approval gates & authorised overrides, immutable version snapshots, async background check pipeline, WCAG contrast tool, compliance certificates, and audit logging.
- **Alisha Almeida (Frontend & Review Experience):** Minimal-motion editorial React/TypeScript UI, multi-org account switcher, URL hash routing & unsent-draft persistence, live async processing stepper, Brand-vs-External lens selector, Evidence-First finding cards, Brand Constitution & Guideline Rectification workspace, and Governance Insights dashboard.
