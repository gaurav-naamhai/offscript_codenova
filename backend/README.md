# Inkloom AI / Offscript - Compliance Backend

FastAPI microservice for autonomous, pre-publication brand compliance reviews, multimodal asset verification (text, image, PDF), version-aware governance, and human-in-the-loop approvals.

> **Roadmap & Architecture Notice**: OCR image text extraction, persistent Supabase integration, real Gemini/Exa/TinyFish external API calls, and authentication are intentionally not implemented yet. In-memory storage is active, meaning data is reset on application restart (set `DEMO_MODE=true` and call `POST /demo/seed` to repopulate test records). `SupabaseRepository` remains a placeholder raising `NotImplementedError` until schema finalization.

---

## 1. Quickstart & Local Execution (Any OS)

### Prerequisites
- Python 3.11+ or 3.12+ (tested on Python 3.12 and 3.14)
- Git

### Linux / macOS (bash / zsh)
```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -r requirements-dev.txt   # for test dependencies

# Run server locally
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Windows (PowerShell)
```powershell
Set-Location backend
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install -r requirements-dev.txt   # for test dependencies

# Run server locally
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Interactive documentation and OpenAPI schema:
- Swagger UI: [http://localhost:8000/docs](http://localhost:8000/docs) (HTTP 200 verified)
- OpenAPI Specification: [http://localhost:8000/openapi.json](http://localhost:8000/openapi.json) (HTTP 200 verified)

---

## 2. Docker Execution

Build and run using the included container configuration (`python:3.12-slim`):

```bash
cd backend
docker build -t offscript-compliance-backend .
docker run -p 8000:8000 --env-file .env offscript-compliance-backend
```

---

## 3. Render Deployment

Deploy directly as a Render Web Service using `render.yaml`:
- **Root Directory**: `backend`
- **Runtime**: `Python`
- **Build Command**: `pip install -r requirements.txt`
- **Start Command**:
  ```bash
  uvicorn app.main:app --host 0.0.0.0 --port $PORT
  ```
- **Environment Variables**: `PYTHON_VERSION=3.12.2`

---

## 4. Environment Variables

Configure application settings via environment variables (read via `os.environ`):

| Variable | Type | Default | Description |
|---|---|---|---|
| `FRONTEND_ORIGIN` | string | `""` | Comma-separated list of allowed CORS origins (e.g. `http://localhost:3000,http://127.0.0.1:3000`). Trims trailing slashes. Supports `*` for demo and local development. |
| `REPO_BACKEND` | string | `"memory"` | Storage engine: `memory` for thread-safe in-memory store (capped at 200 submissions), or `supabase` (raises `NotImplementedError`). |
| `DEMO_MODE` | boolean | `false` | When set to `true`, enables `POST /demo/seed` to seed 3 mock submissions for judging. Must remain `false` by default. |
| `EXTERNAL_SERVICES_ENABLED`| string | `""` | Comma-separated list of external services disclosed in `GET /disclosures`. Defaults to empty string. |
| `GEMINI_MODEL` | string | `""` | Optional Google Gemini model override (e.g. `gemini-1.5-pro`). |
| `GEMINI_API_KEY` | string | `""` | Google Gemini multimodal engine API key. |
| `EXA_API_KEY` | string | `""` | Exa neural search API key. |
| `TINYFISH_API_KEY` | string | `""` | TinySearch / TinyFetch web grounding API key. |
| `SUPABASE_URL` | string | `""` | Supabase project URL. |
| `SUPABASE_SERVICE_KEY` | string | `""` | Supabase service role key. |

---

## 5. Endpoints Overview (Synchronized with OpenAPI)

Total Endpoints in OpenAPI: **17**

| Method | Path | Allowed Role(s) | Description |
|---|---|---|---|
| `GET` | `/health` | Any | Health probe returning `{"status": "ok"}`. |
| `GET` | `/submissions` | Any | Lists submissions (newest first). Optional query filter `?status=`. Returns item summaries with flag counts. |
| `POST` | `/submissions` | `creator` | Multipart upload for text (`<=50k` chars), image (`png`/`jpeg`/`webp` `<=5MB`), or PDF (`<=10MB`). Validates magic bytes. Initializes submission in `draft` state (version 1). Accepts optional `X-Actor` header. |
| `POST` | `/submissions/{id}/revise` | `creator` | Replaces draft text or file using creation validation rules. Updates current version and records audit event `revised`. Accepts optional `X-Actor` header. |
| `GET` | `/submissions/{id}/file` | Any | Streams uploaded image or PDF bytes with appropriate media type. Returns 404 for text submissions. |
| `POST` | `/submissions/{id}/flags/{flag_id}/resolution` | `creator` | Resolves a flag (`action: accept \| dismiss`, optional `comment`). For `accept` on text submissions, applies `suggested_correction` to text (returns 409 if passage is missing). Accepts optional `X-Actor` header. |
| `POST` | `/submissions/{id}/flags/{flag_id}/recheck` | `creator` | Applies candidate correction in-memory without saving, re-evaluates rules on candidate text, and returns new flags, whether the original flag is gone, and human uncertainty status. Text submissions only (400 otherwise). Accepts optional `X-Actor` header. |
| `GET` | `/submissions/{id}/versions` | Any | Lists recorded version numbers with corresponding flag and human review counts. |
| `POST` | `/submissions/{id}/check` | `creator` | `draft` only. Transitions to `ai_review`, executes pipeline (`retrieval` -> `verification` -> `brand_check`), saves versioned flags, transitions to `manager_review`. Accepts optional `X-Actor` header. |
| `GET` | `/submissions/{id}` | Any | Returns full submission data `{submission, flags, comments, decisions}`. Optional query `?version=N` loads historical version flags. |
| `POST` | `/submissions/{id}/decision` | `manager`, `authorised_reviewer` | Transitions submission based on role: `manager_review` + `manager` -> `final_approval` (approve) or `draft` (request_changes, v+1); `final_approval` + `authorised_reviewer` -> `approved` (approve) or `draft` (request_changes, v+1). Accepts optional `X-Actor` header. |
| `POST` | `/submissions/{id}/comments` | `creator`, `manager`, `authorised_reviewer` | Appends review comment tied to submission's current version. Accepts optional `X-Actor` header. |
| `GET` | `/submissions/{id}/audit` | Any | Returns chronological audit trail `(actor_role, action, detail, timestamp, actor)`. |
| `GET` | `/insights/recurring` | Any | Aggregates guideline frequency (top 10) and flag state distributions across all submissions. |
| `GET` | `/disclosures` | Any | Discloses external services enabled via `EXTERNAL_SERVICES_ENABLED` and emphasizes that final publication is always a human decision. |
| `GET` | `/tools/contrast` | Any | Computes WCAG contrast ratio between `fg` and `bg` hex colors and verifies compliance against AA and AAA standards. |
| `POST` | `/demo/seed` | Any | Requires `DEMO_MODE=true` (403 otherwise). Seeds 3 mock submissions (`draft`, `manager_review`, `approved`) for judging demonstrations. |

---

## 6. How to Replace a Plug-in

All plug-in modules reside in `app/plugins/`:
1. `retrieval.py` (Owner: Ken)
2. `verification.py` (Owner: Ken)
3. `brand_check.py` (Owner: Sera)

### Failure Handling Architecture
The pipeline in `app/pipeline.py` wraps each plugin call in a `try/except` block and validates the return type. If any plugin fails or returns an invalid object, the pipeline logs the full traceback server-side, records `{module, error: exception_type_only}` in `degraded_modules`, records a `module_fallback` audit event, and generates an explicit error flag (`origin="error"`, `needs_human=True`, `status="open"`, `passage="(whole submission)"`, no suggested correction). If retrieval fails, the pipeline continues with `guidelines=[]` so downstream verification and brand checking still run.

---

## 7. Teammate Contract: Plug-in Signatures & Flag Schema

Paste this contract directly into your AI coding tool when authoring plugins:

### Plug-in Signatures

```python
from app.models import ContentPayload, GuidelineRef, FlagDraft

# Owner: Ken
def retrieve_guidelines(content: ContentPayload) -> list[GuidelineRef]:
    ...

# Owner: Ken
def verify_claims(content: ContentPayload) -> list[FlagDraft]:
    ...

# Owner: Sera
def check_brand(content: ContentPayload, guidelines: list[GuidelineRef]) -> list[FlagDraft]:
    ...
```

### ContentPayload Schema
```python
@dataclass
class ContentPayload:
    content_type: str            # 'text' | 'image' | 'pdf'
    text: Optional[str]          # Cleaned text body (text submissions only)
    file_name: Optional[str]     # Uploaded filename
    file_mime: Optional[str]     # Uploaded MIME type
    file_bytes: Optional[bytes]   # Raw binary bytes (image/pdf submissions)
```

### Full Flag JSON Shape
```json
{
  "id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "submission_id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
  "version": 1,
  "finding_type": "brand",
  "state": "potential_issue",
  "passage": "Disruptive synergy for maximum scale.",
  "location": "paragraph 2, lines 14-16",
  "explanation": "Overly buzzword-heavy phrasing violates our plain-English brand tone.",
  "why_it_matters": "Maintains an approachable, clear, and trustworthy brand voice.",
  "guideline_ref": {
    "document": "Brand Voice Guidelines v2.1",
    "passage_ref": "Section 4.1",
    "excerpt": "Avoid empty corporate jargon and hyperbole.",
    "source_reference": "Brand Governance Guide"
  },
  "guideline_refs": [
    {
      "document": "Brand Voice Guidelines v2.1",
      "passage_ref": "Section 4.1",
      "excerpt": "Avoid empty corporate jargon and hyperbole.",
      "source_reference": "Brand Governance Guide"
    }
  ],
  "external_sources": [
    {
      "url": "https://brand.example.com/rules",
      "excerpt": "Rule 4.1: Plain communication standard."
    }
  ],
  "uncertainty_note": null,
  "suggested_correction": "Collaborative solutions designed to scale reliably.",
  "origin": "module",
  "status": "open",
  "comments": [],
  "needs_human": false,
  "created_at": "2026-11-13T12:00:00Z"
}
```

- **Allowed Origins**: `"module"`, `"fixture"`, `"error"`.
- **Allowed Brand States**: `"aligned"`, `"potential_issue"`, `"unclear"`.
- **Allowed Claim States**: `"supported"`, `"contradicted"`, `"insufficient_evidence"`.
- **Uncertainty Rule**: `needs_human` is automatically evaluated to `true` whenever state is `"unclear"`, `"contradicted"`, or `"insufficient_evidence"`.

---

## 8. Running Tests

```bash
cd backend
pytest tests/ -v
```

All 66 tests run in-memory with zero network or external database dependencies.
