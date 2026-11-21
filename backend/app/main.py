"""FastAPI Application for Inkloom AI compliance governance."""

import asyncio
from collections import Counter
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import logging
import threading
from typing import Dict, List, Optional, Set, Tuple
import uuid

from fastapi import (
    FastAPI,
    File,
    Form,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.ai.governance_intelligence import (
    compute_draft_hints,
    compute_fidelity_scores,
    compute_recurring_hints,
    generate_governance_insights,
)
from app.ai.guideline_rectification import scan_guidelines_for_rectification
from app.auth import (
    UserAccount,
    authenticate_user,
    create_access_token,
    list_demo_accounts,
    register_user,
    resolve_auth_context,
)
from app.config import Settings
from app.models import (
    AuditEvent,
    CheckRequest,
    CheckResponse,
    Comment,
    CommentRequest,
    ContentPayload,
    ContrastResponse,
    Decision,
    DecisionRequest,
    DisclosureItem,
    DisclosuresResponse,
    DraftHintsRequest,
    Flag,
    RectificationApproveRequest,
    RectificationDismissRequest,
    RecurringInsightsResponse,
    RecheckRequest,
    RecheckResponse,
    ResolutionRequest,
    RoleType,
    Submission,
    SubmissionDetailResponse,
    SubmissionListItem,
    SubmissionStatusResponse,
    VersionInfo,
    VersionSnapshot,
)
from app.pipeline import run_pipeline
from app.repository import SubmissionRepository, get_repository

logger = logging.getLogger("inkloom_app")

ALLOWED_IMAGE_PREFIXES = (b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff")
MAX_TEXT_LENGTH = 50000
MAX_IMAGE_SIZE = 5 * 1024 * 1024
MAX_PDF_SIZE = 10 * 1024 * 1024

SERVICE_DEFINITIONS = {
    "gemini": {"name": "Gemini", "description": "Google Gemini multimodal engine for guideline analysis and claim parsing"},
    "exa": {"name": "Exa", "description": "Exa neural search for external claim reference discovery"},
    "tinyfish": {"name": "TinyFish", "description": "TinySearch and TinyFetch for live web verification and factual grounding"},
    "supabase": {"name": "Supabase", "description": "Supabase PostgreSQL vector and relational store"},
}

STAGE_PROGRESS_PCT: Dict[str, int] = {
    "extracting": 20,
    "retrieving_guidelines": 40,
    "understanding_content": 58,
    "verifying_and_assessing": 78,
    "synthesizing": 92,
    "completed": 100,
    "failed": 0,
}


class LoginRequest(BaseModel):
    email: str
    password: str


class RegisterRequest(BaseModel):
    email: str
    password: str
    name: str
    role: RoleType
    org_name: str
    brand_name: Optional[str] = None


def is_valid_image(data: bytes) -> bool:
    """Validate image bytes for PNG, JPEG, or WEBP magic headers."""
    return data.startswith(ALLOWED_IMAGE_PREFIXES) or (
        len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP"
    )


def compute_contrast_ratio(fg: str, bg: str) -> float:
    """Calculate WCAG contrast ratio between foreground and background colors."""
    def lum(h: str) -> float:
        raw = h.strip().lstrip("#")
        if len(raw) == 3:
            raw = "".join(c * 2 for c in raw)
        if len(raw) != 6:
            raise ValueError(f"Invalid hex color length for '{h}'")
        try:
            rgb = [int(raw[i : i + 2], 16) / 255.0 for i in (0, 2, 4)]
        except ValueError as exc:
            raise ValueError(f"Invalid hex character in '{h}'") from exc
        c = [v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in rgb]
        return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]

    l1, l2 = lum(fg), lum(bg)
    return round((max(l1, l2) + 0.05) / (min(l1, l2) + 0.05), 2)


async def validate_submission_payload(
    content_type: str, text: Optional[str], file: Optional[UploadFile]
) -> tuple[Optional[str], Optional[bytes], Optional[str], Optional[str]]:
    """Validate multipart content and return cleaned text, bytes, filename, and mime."""
    if content_type not in {"text", "image", "pdf"}:
        raise HTTPException(422, "Invalid content_type. Must be text, image, or pdf")

    cleaned_text = text.strip() if text else None
    if content_type == "text":
        if file is not None and file.filename:
            raise HTTPException(422, "File upload not allowed when content_type is text")
        if not cleaned_text:
            raise HTTPException(422, "Text content cannot be empty")
        if len(cleaned_text) > MAX_TEXT_LENGTH:
            raise HTTPException(422, f"Text content exceeds {MAX_TEXT_LENGTH} characters limit")
        return cleaned_text, None, None, None

    if cleaned_text:
        raise HTTPException(422, f"Text content not allowed when content_type is {content_type}")
    if file is None or not file.filename:
        raise HTTPException(422, f"File is required for {content_type} submission")

    file_bytes = await file.read()
    limit = MAX_IMAGE_SIZE if content_type == "image" else MAX_PDF_SIZE
    limit_desc = "5MB" if content_type == "image" else "10MB"
    if len(file_bytes) > limit:
        prefix = "Image" if content_type == "image" else "PDF"
        raise HTTPException(422, f"{prefix} exceeds {limit} bytes limit ({limit_desc})")
    if content_type == "image" and not is_valid_image(file_bytes):
        raise HTTPException(422, "Invalid image format. Allowed formats are PNG, JPEG, WEBP")
    if content_type == "pdf" and not file_bytes.startswith(b"%PDF-"):
        raise HTTPException(422, "Invalid PDF format. File must start with %PDF-")

    return None, file_bytes, file.filename, file.content_type


async def get_sub_or_404(
    repo: SubmissionRepository,
    sub_id: str,
    user: Optional[UserAccount] = None,
) -> Submission:
    sub = await repo.get_submission(sub_id)
    if not sub:
        raise HTTPException(status_code=404, detail="Submission not found")
    if user and (sub.org_id or "inkloom").lower() != user.org_id.lower():
        raise HTTPException(status_code=404, detail="Submission not found")
    return sub


async def _find_flag(repo: SubmissionRepository, sub_id: str, flag_id: str, version: int) -> Flag:
    flags = await repo.get_flags(sub_id, version=version)
    target = next((f for f in flags if f.id == flag_id), None)
    if not target:
        target = next((f for f in await repo.get_all_flags(sub_id) if f.id == flag_id), None)
    if not target:
        raise HTTPException(status_code=404, detail="Flag not found")
    return target


async def record_audit(
    repo: SubmissionRepository,
    sub_id: str,
    role: str,
    action: str,
    detail: Optional[str] = None,
    x_actor: Optional[str] = None,
    timestamp: Optional[str] = None,
) -> AuditEvent:
    actor = x_actor.strip() if x_actor and x_actor.strip() else role
    event = AuditEvent(
        actor_role=role,
        action=action,
        detail=detail or "",
        timestamp=timestamp or datetime.now(timezone.utc).isoformat(),
        actor=actor,
    )
    return await repo.add_audit_event(sub_id, event)


def require_role(role: str, allowed: Set[str], context: str = "") -> None:
    if role == "manager":
        return
    if role not in allowed:
        msg = (
            f"Only creators can {context}"
            if allowed == {"creator"}
            else (
                f"Role '{role}' is not authorized for {context}"
                if context
                else f"Role '{role}' is not authorized"
            )
        )
        raise HTTPException(status_code=403, detail=msg)


def _snapshot_from_submission(sub: Submission) -> VersionSnapshot:
    return VersionSnapshot(
        version=sub.version,
        content_type=sub.content_type,
        title=sub.title,
        audience=sub.audience,
        channel=sub.channel,
        context=sub.context,
        text=sub.text,
        file_name=sub.file_name,
        file_mime=sub.file_mime,
        file_size=sub.file_size,
        file_bytes=sub.file_bytes,
        status=sub.status,
        created_at=sub.updated_at or sub.created_at,
        created_by=sub.created_by_name or sub.role,
    )


def _blocking_flags(flags: List[Flag]) -> List[Flag]:
    return [
        f
        for f in flags
        if f.status == "open"
        and (
            f.origin == "error"
            or f.state in {"potential_issue", "contradicted", "insufficient_evidence", "unclear"}
        )
    ]


def create_app(
    repo: Optional[SubmissionRepository] = None,
    settings: Optional[Settings] = None,
) -> FastAPI:
    """Application factory for FastAPI app with injectable repository and settings."""
    app_settings = settings or Settings()
    app_repo = repo or get_repository(app_settings.repo_backend)
    background_tasks: Set[asyncio.Task] = set()

    def _resolve_context(
        authorization: Optional[str],
        claimed_role: Optional[str] = None,
        require_explicit_role_when_unauth: bool = True,
    ) -> Tuple[Optional[UserAccount], str, str, str]:
        user = resolve_auth_context(authorization, app_settings)
        if user is not None:
            if claimed_role and claimed_role.strip() and claimed_role.strip() != user.role:
                raise HTTPException(
                    status_code=403,
                    detail=f"Authenticated role '{user.role}' cannot act as '{claimed_role.strip()}'.",
                )
            return user, user.role, user.org_id, user.brand_name
        role = (claimed_role or "").strip()
        if require_explicit_role_when_unauth and not role:
            raise HTTPException(status_code=422, detail="role is required")
        return None, role or "creator", "inkloom", "Inkloom AI"

    async def _seed_data(org_id: str = "inkloom", brand_name: str = "Inkloom AI") -> List[Submission]:
        now_iso = datetime.now(timezone.utc).isoformat()
        seeds = [
            (
                "Summer Campaign Announcement",
                "Small business owners",
                "Marketing email",
                "Reviewing new promotional email draft for tone consistency and claim accuracy.",
                "draft",
                f"{brand_name} helps distributed marketing teams prevent brand violations.",
                False,
                False,
            ),
            (
                "Enterprise SLA Performance Sheet",
                "Enterprise IT buyers",
                "Website",
                "Checking uptime and performance claims against verified SLA standards.",
                "manager_review",
                "Industry-leading 99.9% uptime SLA with real-time audit logging.",
                True,
                False,
            ),
            (
                "Q4 Brand Governance Overview",
                "Brand & legal stakeholders",
                "Social media",
                "Approved executive summary of compliance achievements.",
                "approved",
                "Trusted compliance automation for enterprise publishing.",
                True,
                True,
            ),
        ]
        seeded: List[Submission] = []
        for idx, (title, audience, channel, context, st, txt, run_pipe, do_dec) in enumerate(seeds, 1):
            sub = Submission(
                id=str(uuid.uuid4()),
                content_type="text",
                role="creator",
                status=st,
                version=1,
                org_id=org_id,
                brand_name=brand_name,
                title=title,
                audience=audience,
                channel=channel,
                context=context,
                text=txt,
                created_at=now_iso,
                updated_at=now_iso,
            )
            await app_repo.create_submission(sub)
            await app_repo.save_version_snapshot(sub.id, _snapshot_from_submission(sub))
            await record_audit(
                app_repo, sub.id, "creator", "created",
                f"Demo submission {idx} created" + (f" ({st})" if st == "draft" else ""),
                timestamp=now_iso,
            )
            if run_pipe:
                fl, _ = run_pipeline(
                    ContentPayload(
                        content_type="text",
                        text=txt,
                        org_id=org_id,
                        brand_name=brand_name,
                    ),
                    sub.id,
                    1,
                )
                await app_repo.set_flags(sub.id, fl, 1)
                await record_audit(app_repo, sub.id, "creator", "check_completed", f"Check completed with {len(fl)} flags", timestamp=now_iso)
            if do_dec:
                d1 = Decision(id=str(uuid.uuid4()), submission_id=sub.id, role="manager", decision="approve", comment="Brand voice aligned.", version=1, created_at=now_iso)
                d2 = Decision(id=str(uuid.uuid4()), submission_id=sub.id, role="authorised_reviewer", decision="approve", comment="Final legal sign-off granted.", version=1, created_at=now_iso)
                await app_repo.add_decision(d1)
                await app_repo.add_decision(d2)
                await record_audit(app_repo, sub.id, "manager", "decision_recorded", "Manager approved", timestamp=now_iso)
                await record_audit(app_repo, sub.id, "authorised_reviewer", "decision_recorded", "Authorised reviewer approved", timestamp=now_iso)
            seeded.append(sub)
        return seeded

    async def _execute_check_for_submission(
        sub: Submission,
        actor_role: str,
        x_actor: Optional[str],
    ) -> Tuple[List[Flag], list]:
        def _progress_update(stage: str) -> None:
            sub.processing_stage = stage
            sub.updated_at = datetime.now(timezone.utc).isoformat()

        content = ContentPayload(
            content_type=sub.content_type,
            text=sub.text,
            file_name=sub.file_name,
            file_mime=sub.file_mime,
            file_bytes=sub.file_bytes,
            org_id=sub.org_id,
            brand_name=sub.brand_name,
        )
        flags, degraded_modules = await run_in_threadpool(
            run_pipeline,
            content,
            sub.id,
            sub.version,
            None,
            None,
            None,
            _progress_update,
        )
        if content.extracted_text:
            sub.extracted_text = content.extracted_text

        for dm in degraded_modules:
            await record_audit(
                app_repo,
                sub.id,
                actor_role,
                "module_fallback",
                f"{dm.module}: {dm.error}",
                x_actor=x_actor,
            )

        await app_repo.set_flags(sub.id, flags, version=sub.version)
        completed_iso = datetime.now(timezone.utc).isoformat()
        sub.status = "manager_review"
        sub.processing_stage = "completed"
        sub.processing_error = None
        sub.updated_at = completed_iso
        await app_repo.update_submission(sub)
        await app_repo.save_version_snapshot(sub.id, _snapshot_from_submission(sub))

        await record_audit(
            app_repo,
            sub.id,
            actor_role,
            "check_completed",
            f"Check completed with {len(flags)} flags",
            x_actor=x_actor,
            timestamp=completed_iso,
        )
        return flags, degraded_modules

    async def _run_check_background(sub_id: str, actor_role: str, x_actor: Optional[str]) -> None:
        sub = await app_repo.get_submission(sub_id)
        if not sub:
            return
        try:
            await _execute_check_for_submission(sub, actor_role, x_actor)
        except Exception as exc:
            logger.error("Async compliance check failed for %s: %s", sub_id, exc, exc_info=True)
            sub.status = "draft"
            sub.processing_stage = "failed"
            sub.processing_error = str(exc)
            sub.updated_at = datetime.now(timezone.utc).isoformat()
            await app_repo.update_submission(sub)
            await record_audit(
                app_repo,
                sub.id,
                actor_role,
                "check_failed",
                f"Compliance check failed safely: {exc}",
                x_actor=x_actor,
            )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if app_settings.demo_mode:
            existing = await app_repo.list_submissions()
            if not existing:
                await _seed_data()
        yield
        for t in list(background_tasks):
            t.cancel()

    app = FastAPI(
        title="Inkloom Compliance API",
        version="2.0.0",
        docs_url="/docs",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )
    app.state.settings = app_settings
    app.state.repo = app_repo

    if app_settings.cors_origins:
        allow_all = app_settings.cors_origins == ["*"]
        app.add_middleware(
            CORSMiddleware,
            allow_origins=app_settings.cors_origins,
            allow_credentials=not allow_all,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        codes = {
            400: "bad_request",
            401: "unauthorized",
            403: "forbidden",
            404: "not_found",
            409: "conflict",
            413: "payload_too_large",
            422: "unprocessable_entity",
            500: "internal_error",
        }
        msg = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
        return JSONResponse(status_code=exc.status_code, content={"error": {"code": codes.get(exc.status_code, "http_error"), "message": msg}})

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        msgs = [f"{'.'.join(str(l) for l in err.get('loc', []))}: {err.get('msg', 'Invalid input')}" for err in exc.errors()]
        return JSONResponse(status_code=422, content={"error": {"code": "validation_error", "message": "; ".join(msgs) if msgs else "Validation failed"}})

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        logger.error("Unhandled exception: %s", exc, exc_info=True)
        return JSONResponse(status_code=500, content={"error": {"code": "internal_error", "message": "An internal server error occurred"}})

    # -----------------------------------------------------------------------
    # Health & Authentication
    # -----------------------------------------------------------------------

    @app.get("/health")
    async def health():
        """Health check probe."""
        return {"status": "ok"}

    @app.get("/auth/accounts")
    async def auth_accounts():
        """List available demo organisations and role accounts for sign-in."""
        return {"accounts": list_demo_accounts()}

    @app.post("/auth/login")
    async def auth_login(payload: LoginRequest):
        """Authenticate with email and password and receive a signed Bearer token."""
        user = authenticate_user(payload.email, payload.password)
        if not user:
            raise HTTPException(status_code=401, detail="Invalid email or password.")
        token = create_access_token(user, app_settings.auth_secret)
        return {"access_token": token, "token_type": "bearer", "user": user}

    @app.post("/auth/register", status_code=status.HTTP_201_CREATED)
    async def auth_register(payload: RegisterRequest):
        """Create a new organisation/role account and return a signed Bearer token."""
        user = register_user(
            email=payload.email,
            password=payload.password,
            name=payload.name,
            role=payload.role,
            org_name=payload.org_name,
            brand_name=payload.brand_name,
        )
        token = create_access_token(user, app_settings.auth_secret)
        return {"access_token": token, "token_type": "bearer", "user": user}

    @app.get("/auth/me")
    async def auth_me(authorization: Optional[str] = Header(None, alias="Authorization")):
        """Return currently authenticated user profile."""
        if not authorization:
            raise HTTPException(status_code=401, detail="Missing Authorization header.")
        user = resolve_auth_context(authorization, app_settings)
        return {"user": user}

    # -----------------------------------------------------------------------
    # Submissions & Live Draft Hints (static route BEFORE /submissions/{id})
    # -----------------------------------------------------------------------

    @app.post("/submissions/draft-hints")
    async def preview_draft_hints(
        payload: DraftHintsRequest,
        authorization: Optional[str] = Header(None, alias="Authorization"),
    ):
        """Fast pre-flight coaching hints while drafting, checking Brand Constitution & recurring mistakes."""
        user, _, org_id, _ = _resolve_context(authorization, require_explicit_role_when_unauth=False)
        from retrieval.brand_rag import get_brand_constitution

        constitution = await run_in_threadpool(get_brand_constitution, org_id)
        historical_flags = await app_repo.get_all_flags(org_id=org_id if user else None)
        hints = compute_draft_hints(payload.text, constitution=constitution, historical_flags=historical_flags)
        return {"hints": [h.model_dump() for h in hints]}

    @app.get("/submissions", response_model=List[SubmissionListItem])
    async def list_submissions(
        status: Optional[str] = Query(None),
        authorization: Optional[str] = Header(None, alias="Authorization"),
    ):
        """List submissions scoped strictly to the authenticated organisation."""
        user, _, org_id, _ = _resolve_context(authorization, require_explicit_role_when_unauth=False)
        submissions = await app_repo.list_submissions(
            status=status,
            org_id=org_id if user else None,
        )
        results = []
        for sub in submissions:
            flags = await app_repo.get_flags(sub.id, version=sub.version)
            results.append(
                SubmissionListItem(
                    id=sub.id,
                    content_type=sub.content_type,
                    status=sub.status,
                    version=sub.version,
                    org_id=sub.org_id,
                    brand_name=sub.brand_name,
                    created_by_name=sub.created_by_name,
                    processing_stage=sub.processing_stage,
                    title=sub.title,
                    audience=sub.audience,
                    channel=sub.channel,
                    context=sub.context,
                    created_at=sub.created_at,
                    flag_count=len(flags),
                    needs_human_count=sum(1 for f in flags if f.needs_human),
                )
            )
        return results

    @app.post("/submissions", status_code=status.HTTP_201_CREATED)
    async def create_submission(
        content_type: str = Form(...),
        role: Optional[str] = Form(None),
        title: Optional[str] = Form(None),
        audience: Optional[str] = Form(None),
        channel: Optional[str] = Form(None),
        context: Optional[str] = Form(None),
        text: Optional[str] = Form(None),
        file: Optional[UploadFile] = File(None),
        x_actor: Optional[str] = Header(None, alias="X-Actor"),
        authorization: Optional[str] = Header(None, alias="Authorization"),
    ):
        """Create a new compliance submission."""
        user, effective_role, org_id, brand_name = _resolve_context(authorization, claimed_role=role)
        require_role(effective_role, {"creator", "manager"}, "create submissions")
        cleaned_text, file_bytes, file_name, file_mime = (
            await validate_submission_payload(content_type, text, file)
        )
        now_iso = datetime.now(timezone.utc).isoformat()
        sub_id = str(uuid.uuid4())
        submission = Submission(
            id=sub_id,
            content_type=content_type,
            role=effective_role,
            status="draft",
            version=1,
            org_id=org_id,
            brand_name=brand_name,
            created_by_user_id=user.user_id if user else None,
            created_by_name=user.name if user else (x_actor or effective_role),
            title=title.strip() if title and title.strip() else None,
            audience=audience.strip() if audience and audience.strip() else None,
            channel=channel.strip() if channel and channel.strip() else None,
            context=context.strip() if context and context.strip() else None,
            text=cleaned_text,
            file_name=file_name,
            file_mime=file_mime,
            file_size=len(file_bytes) if file_bytes else None,
            file_bytes=file_bytes,
            created_at=now_iso,
            updated_at=now_iso,
        )
        await app_repo.create_submission(submission)
        await app_repo.save_version_snapshot(sub_id, _snapshot_from_submission(submission))
        await record_audit(
            app_repo,
            sub_id,
            effective_role,
            "created",
            f"Submission created with content_type={content_type} (org={org_id})",
            x_actor=user.name if user else x_actor,
            timestamp=now_iso,
        )
        return submission

    @app.post("/submissions/{id}/revise")
    async def revise_submission(
        id: str,
        content_type: str = Form(...),
        role: Optional[str] = Form(None),
        title: Optional[str] = Form(None),
        audience: Optional[str] = Form(None),
        channel: Optional[str] = Form(None),
        context: Optional[str] = Form(None),
        text: Optional[str] = Form(None),
        file: Optional[UploadFile] = File(None),
        create_new_version: bool = Form(False),
        x_actor: Optional[str] = Header(None, alias="X-Actor"),
        authorization: Optional[str] = Header(None, alias="Authorization"),
    ):
        """Revise draft content, or create a new version requiring reapproval if already reviewed/approved."""
        user, effective_role, _, _ = _resolve_context(authorization, claimed_role=role)
        sub = await get_sub_or_404(app_repo, id, user=user)
        require_role(effective_role, {"creator", "manager"}, "revise submissions")

        was_approved_or_final = sub.status in {"final_approval", "approved"}
        can_auto_version = (
            was_approved_or_final
            or create_new_version
            or (app_settings.enforce_approval_gates and sub.status == "manager_review")
        )

        if sub.status != "draft" and not can_auto_version:
            raise HTTPException(
                status_code=409,
                detail=f"Cannot revise submission in '{sub.status}' state. Must be 'draft'",
            )

        cleaned_text, file_bytes, file_name, file_mime = (
            await validate_submission_payload(content_type, text, file)
        )
        now_iso = datetime.now(timezone.utc).isoformat()
        actor_label = user.name if user else x_actor

        if sub.status != "draft":
            # Preserve exact snapshot of the previous version before bumping
            await app_repo.save_version_snapshot(id, _snapshot_from_submission(sub))
            old_status = sub.status
            old_version = sub.version
            sub.version += 1
            sub.status = "draft"
            sub.manager_approved_by = None
            await record_audit(
                app_repo,
                id,
                effective_role,
                "approval_invalidated" if was_approved_or_final else "version_created",
                f"Content edited while in '{old_status}' state; preserved v{old_version} and created v{sub.version} requiring reapproval.",
                x_actor=actor_label,
                timestamp=now_iso,
            )

        sub.content_type = content_type
        if title is not None:
            sub.title = title.strip() if title.strip() else None
        if audience is not None:
            sub.audience = audience.strip() if audience.strip() else None
        if channel is not None:
            sub.channel = channel.strip() if channel.strip() else None
        if context is not None:
            sub.context = context.strip() if context.strip() else None
        sub.text = cleaned_text
        sub.file_name = file_name
        sub.file_mime = file_mime
        sub.file_size = len(file_bytes) if file_bytes else None
        sub.file_bytes = file_bytes
        sub.extracted_text = None
        sub.processing_stage = None
        sub.processing_error = None
        sub.updated_at = now_iso

        await app_repo.update_submission(sub)
        await app_repo.save_version_snapshot(id, _snapshot_from_submission(sub))
        await record_audit(
            app_repo,
            id,
            effective_role,
            "revised",
            f"Submission revised on v{sub.version} with content_type={content_type}",
            x_actor=actor_label,
            timestamp=now_iso,
        )
        return sub

    @app.get("/submissions/{id}/file")
    async def get_submission_file(
        id: str,
        version: Optional[int] = Query(None),
        authorization: Optional[str] = Header(None, alias="Authorization"),
    ):
        """Retrieve binary file bytes for image or PDF submission (optionally by version snapshot)."""
        user, _, _, _ = _resolve_context(authorization, require_explicit_role_when_unauth=False)
        sub = await get_sub_or_404(app_repo, id, user=user)
        target_bytes = sub.file_bytes
        target_mime = sub.file_mime
        target_type = sub.content_type

        if version is not None and version != sub.version:
            snap = await app_repo.get_version_snapshot(id, version)
            if snap:
                target_bytes = snap.file_bytes
                target_mime = snap.file_mime
                target_type = snap.content_type

        if target_type == "text" or not target_bytes:
            raise HTTPException(
                status_code=404, detail="File not found for text submission"
            )
        return Response(
            content=target_bytes,
            media_type=target_mime or "application/octet-stream",
        )

    @app.post("/submissions/{id}/flags/{flag_id}/resolution", response_model=Flag)
    async def resolve_flag(
        id: str,
        flag_id: str,
        payload: ResolutionRequest,
        x_actor: Optional[str] = Header(None, alias="X-Actor"),
        authorization: Optional[str] = Header(None, alias="Authorization"),
    ):
        """Resolve a specific flag (accept or dismiss)."""
        user, effective_role, _, _ = _resolve_context(
            authorization,
            claimed_role=payload.role,
            require_explicit_role_when_unauth=False,
        )
        sub = await get_sub_or_404(app_repo, id, user=user)
        role = effective_role if user else (payload.role or "creator")
        require_role(role, {"creator", "manager"}, "resolve flags")
        if payload.action not in {"accept", "dismiss"}:
            raise HTTPException(
                status_code=422, detail="Action must be 'accept' or 'dismiss'"
            )

        target_flag = await _find_flag(app_repo, id, flag_id, sub.version)
        now_iso = datetime.now(timezone.utc).isoformat()
        actor_label = user.name if user else x_actor

        if payload.action == "accept":
            if sub.content_type == "text":
                current_text = sub.text or ""
                if target_flag.passage not in current_text:
                    raise HTTPException(
                        status_code=409,
                        detail=f"Flag passage '{target_flag.passage}' was not found in the current text",
                    )
                if target_flag.suggested_correction:
                    if sub.status in {"final_approval", "approved"} or (
                        app_settings.enforce_approval_gates and sub.status == "manager_review"
                    ):
                        await app_repo.save_version_snapshot(id, _snapshot_from_submission(sub))
                        old_status = sub.status
                        old_version = sub.version
                        sub.version += 1
                        sub.status = "draft"
                        sub.manager_approved_by = None
                        await record_audit(
                            app_repo,
                            id,
                            role,
                            "approval_invalidated" if old_status in {"final_approval", "approved"} else "version_created",
                            f"Accepted correction changed '{old_status}' content; preserved v{old_version} and created v{sub.version}.",
                            x_actor=actor_label,
                            timestamp=now_iso,
                        )
                    sub.text = current_text.replace(
                        target_flag.passage, target_flag.suggested_correction, 1
                    )
                    sub.updated_at = now_iso
                    await app_repo.update_submission(sub)
                    await app_repo.save_version_snapshot(id, _snapshot_from_submission(sub))
            target_flag.status = "accepted"
        else:
            target_flag.status = "dismissed"

        if payload.comment:
            target_flag.comments.append(payload.comment)
        await app_repo.update_flag(id, target_flag)

        await record_audit(
            app_repo,
            id,
            role,
            "flag_resolved",
            f"Flag {flag_id} resolved with action '{payload.action}'",
            x_actor=actor_label,
            timestamp=now_iso,
        )
        return target_flag

    @app.post("/submissions/{id}/flags/{flag_id}/recheck", response_model=RecheckResponse)
    async def recheck_flag(
        id: str,
        flag_id: str,
        payload: Optional[RecheckRequest] = None,
        x_actor: Optional[str] = Header(None, alias="X-Actor"),
        authorization: Optional[str] = Header(None, alias="Authorization"),
    ):
        """Simulate applying flag correction and recheck in threadpool."""
        claimed = payload.role if payload and payload.role else None
        user, effective_role, _, _ = _resolve_context(
            authorization,
            claimed_role=claimed,
            require_explicit_role_when_unauth=False,
        )
        role = effective_role if user else (claimed or "creator")
        require_role(role, {"creator", "manager"}, "recheck flags")
        sub = await get_sub_or_404(app_repo, id, user=user)
        if sub.content_type != "text":
            raise HTTPException(
                status_code=400,
                detail="Recheck is only supported for text submissions",
            )

        target_flag = await _find_flag(app_repo, id, flag_id, sub.version)

        candidate_text = sub.text or ""
        if target_flag.suggested_correction and target_flag.passage in candidate_text:
            candidate_text = candidate_text.replace(
                target_flag.passage, target_flag.suggested_correction, 1
            )

        candidate_payload = ContentPayload(
            content_type="text",
            text=candidate_text,
            org_id=sub.org_id,
            brand_name=sub.brand_name,
        )
        new_flags, _ = await run_in_threadpool(
            run_pipeline, candidate_payload, sub.id, sub.version
        )

        original_flag_gone = not any(
            f.passage == target_flag.passage for f in new_flags
        )
        has_needs_human = any(f.needs_human for f in new_flags)

        await record_audit(
            app_repo,
            id,
            role,
            "recheck",
            f"Recheck executed for flag {flag_id}",
            x_actor=user.name if user else x_actor,
        )
        return RecheckResponse(
            new_flags=new_flags,
            original_flag_gone=original_flag_gone,
            has_needs_human=has_needs_human,
        )

    @app.get("/submissions/{id}/versions", response_model=List[VersionInfo])
    async def get_submission_versions(
        id: str,
        authorization: Optional[str] = Header(None, alias="Authorization"),
    ):
        """List historical versions, flag counts, previews, and decisions."""
        user, _, _, _ = _resolve_context(authorization, require_explicit_role_when_unauth=False)
        sub = await get_sub_or_404(app_repo, id, user=user)
        decisions = await app_repo.get_decisions(id)
        results = []
        for v in await app_repo.get_versions(id):
            v_flags = await app_repo.get_flags(id, version=v)
            snap = await app_repo.get_version_snapshot(id, v)
            preview = None
            file_name = None
            v_status = sub.status if v == sub.version else "archived"
            created_at = sub.updated_at if v == sub.version else None
            if snap:
                v_status = snap.status
                created_at = snap.created_at
                file_name = snap.file_name
                if snap.text:
                    preview = snap.text[:140]
            elif v == sub.version:
                file_name = sub.file_name
                if sub.text:
                    preview = sub.text[:140]

            results.append(
                VersionInfo(
                    version=v,
                    flag_count=len(v_flags),
                    needs_human_count=sum(1 for f in v_flags if f.needs_human),
                    status=v_status,
                    created_at=created_at,
                    content_preview=preview,
                    decision_count=sum(1 for d in decisions if d.version == v),
                    file_name=file_name,
                )
            )
        return results

    @app.get("/submissions/{id}/status", response_model=SubmissionStatusResponse)
    async def get_submission_status(
        id: str,
        authorization: Optional[str] = Header(None, alias="Authorization"),
    ):
        """Poll live processing status for async text/image/PDF reviews."""
        user, _, _, _ = _resolve_context(authorization, require_explicit_role_when_unauth=False)
        sub = await get_sub_or_404(app_repo, id, user=user)
        flags = await app_repo.get_flags(id, version=sub.version)
        stage = sub.processing_stage or ("completed" if sub.status != "ai_review" else "extracting")
        pct = STAGE_PROGRESS_PCT.get(stage, 100 if sub.status != "ai_review" else 35)
        return SubmissionStatusResponse(
            id=sub.id,
            status=sub.status,
            version=sub.version,
            processing_stage=sub.processing_stage,
            processing_error=sub.processing_error,
            progress_pct=pct,
            flag_count=len(flags),
            updated_at=sub.updated_at,
        )

    @app.post("/submissions/{id}/check", response_model=CheckResponse)
    async def check_submission(
        id: str,
        payload: Optional[CheckRequest] = None,
        x_actor: Optional[str] = Header(None, alias="X-Actor"),
        authorization: Optional[str] = Header(None, alias="Authorization"),
    ):
        """Run compliance review pipeline synchronously or asynchronously (`async_mode=true`)."""
        claimed_role = payload.role if payload else None
        user, effective_role, _, _ = _resolve_context(authorization, claimed_role=claimed_role)
        sub = await get_sub_or_404(app_repo, id, user=user)
        require_role(effective_role, {"creator", "manager"}, "run checks")
        if sub.status != "draft":
            raise HTTPException(
                status_code=409,
                detail=f"Cannot run check on submission in state '{sub.status}'. Must be 'draft'",
            )

        now_iso = datetime.now(timezone.utc).isoformat()
        actor_label = user.name if user else x_actor
        sub.status = "ai_review"
        sub.processing_stage = "extracting"
        sub.processing_error = None
        sub.updated_at = now_iso
        await app_repo.update_submission(sub)
        await record_audit(
            app_repo,
            id,
            effective_role,
            "check_started",
            f"Compliance check pipeline started (async={bool(payload and payload.async_mode)})",
            x_actor=actor_label,
            timestamp=now_iso,
        )

        if payload and payload.async_mode:
            t = threading.Thread(
                target=lambda: asyncio.run(_run_check_background(sub.id, effective_role, actor_label)),
                daemon=True,
            )
            t.start()
            return CheckResponse(submission=sub, flags=[], degraded_modules=[])

        try:
            flags, degraded_modules = await _execute_check_for_submission(sub, effective_role, actor_label)
        except Exception as exc:
            sub.status = "draft"
            sub.processing_stage = "failed"
            sub.processing_error = str(exc)
            sub.updated_at = datetime.now(timezone.utc).isoformat()
            await app_repo.update_submission(sub)
            raise

        hist_flags = await app_repo.get_all_flags(org_id=sub.org_id if user else None)
        prior_flags = [hf for hf in hist_flags if hf.submission_id != sub.id]
        hints = compute_recurring_hints(flags, prior_flags, submission_text=sub.text or sub.extracted_text)
        b_score, f_score, readiness = compute_fidelity_scores(flags)
        return CheckResponse(
            submission=sub,
            flags=flags,
            degraded_modules=degraded_modules,
            recurring_hints=hints,
            unresolved_blocking_count=len(_blocking_flags(flags)),
            brand_score=b_score,
            fact_score=f_score,
            readiness_status=readiness,
        )

    @app.post("/submissions/{id}/retry-check", response_model=CheckResponse)
    async def retry_check_submission(
        id: str,
        payload: Optional[CheckRequest] = None,
        x_actor: Optional[str] = Header(None, alias="X-Actor"),
        authorization: Optional[str] = Header(None, alias="Authorization"),
    ):
        """Safely retry a failed or incomplete compliance review."""
        claimed_role = payload.role if payload else None
        user, effective_role, _, _ = _resolve_context(
            authorization,
            claimed_role=claimed_role,
            require_explicit_role_when_unauth=False,
        )
        sub = await get_sub_or_404(app_repo, id, user=user)
        require_role(effective_role, {"creator", "manager"}, "retry checks")

        existing_flags = await app_repo.get_flags(id, version=sub.version)
        has_error_flags = any(f.origin == "error" for f in existing_flags)
        if sub.status not in {"draft", "ai_review"} and not (sub.status == "manager_review" and has_error_flags):
            raise HTTPException(
                status_code=409,
                detail=f"Retry is only allowed on draft, failed, or degraded checks (current state: '{sub.status}').",
            )

        now_iso = datetime.now(timezone.utc).isoformat()
        actor_label = user.name if user else x_actor
        sub.status = "ai_review"
        sub.processing_stage = "extracting"
        sub.processing_error = None
        sub.updated_at = now_iso
        await app_repo.update_submission(sub)
        await record_audit(
            app_repo,
            id,
            effective_role,
            "check_retried",
            f"Compliance check retried by {effective_role}",
            x_actor=actor_label,
            timestamp=now_iso,
        )

        if payload and payload.async_mode:
            t = threading.Thread(
                target=lambda: asyncio.run(_run_check_background(sub.id, effective_role, actor_label)),
                daemon=True,
            )
            t.start()
            return CheckResponse(submission=sub, flags=[], degraded_modules=[])

        flags, degraded_modules = await _execute_check_for_submission(sub, effective_role, actor_label)
        b_score, f_score, readiness = compute_fidelity_scores(flags)
        return CheckResponse(
            submission=sub,
            flags=flags,
            degraded_modules=degraded_modules,
            unresolved_blocking_count=len(_blocking_flags(flags)),
            brand_score=b_score,
            fact_score=f_score,
            readiness_status=readiness,
        )

    @app.get("/submissions/{id}", response_model=SubmissionDetailResponse)
    async def get_submission_detail(
        id: str,
        version: Optional[int] = Query(None),
        authorization: Optional[str] = Header(None, alias="Authorization"),
    ):
        """Get full details of a submission, optionally scoped to a preserved historical version."""
        user, _, _, _ = _resolve_context(authorization, require_explicit_role_when_unauth=False)
        sub = await get_sub_or_404(app_repo, id, user=user)
        target_version = version if version is not None else sub.version

        flags = await app_repo.get_flags(id, version=target_version)
        all_comments = await app_repo.get_comments(id)
        all_decisions = await app_repo.get_decisions(id)
        snapshot = await app_repo.get_version_snapshot(id, target_version)

        comments = [c for c in all_comments if c.version == target_version] if version is not None else all_comments
        decisions = [d for d in all_decisions if d.version == target_version] if version is not None else all_decisions

        hist_flags = await app_repo.get_all_flags(org_id=sub.org_id if user else None)
        prior_flags = [hf for hf in hist_flags if hf.submission_id != sub.id]
        doc_text = (snapshot.text if snapshot and snapshot.text else None) or sub.text or sub.extracted_text
        hints = compute_recurring_hints(flags, prior_flags, submission_text=doc_text)
        b_score, f_score, readiness = compute_fidelity_scores(flags)

        return SubmissionDetailResponse(
            submission=sub,
            flags=flags,
            comments=comments,
            decisions=decisions,
            recurring_hints=hints,
            unresolved_blocking_count=len(_blocking_flags(flags)),
            brand_score=b_score,
            fact_score=f_score,
            readiness_status=readiness,
            version_snapshot=snapshot,
        )

    @app.post("/submissions/{id}/decision", response_model=Decision)
    async def record_decision(
        id: str,
        payload: DecisionRequest,
        x_actor: Optional[str] = Header(None, alias="X-Actor"),
        authorization: Optional[str] = Header(None, alias="Authorization"),
    ):
        """Record manager or reviewer approval decision with separation of duties and unresolved-flag gating."""
        user, effective_role, _, _ = _resolve_context(authorization, claimed_role=payload.role)
        sub = await get_sub_or_404(app_repo, id, user=user)

        if payload.decision not in {"approve", "request_changes"}:
            raise HTTPException(422, "Decision must be 'approve' or 'request_changes'")
        if sub.status not in {"manager_review", "final_approval"}:
            raise HTTPException(409, f"Cannot record decision in state '{sub.status}'")

        actor_label = user.name if user else x_actor
        current_status = sub.status

        if current_status == "manager_review":
            require_role(effective_role, {"manager"}, "manager_review")
        else:
            require_role(effective_role, {"authorised_reviewer"}, "final_approval")

        # Separation of duties when authenticated
        if user and payload.decision == "approve":
            if sub.created_by_user_id and sub.created_by_user_id == user.user_id:
                raise HTTPException(
                    status_code=403,
                    detail="Separation of duties violation: creators cannot approve their own submission.",
                )
            if current_status == "final_approval" and sub.manager_approved_by and sub.manager_approved_by == user.user_id:
                raise HTTPException(
                    status_code=403,
                    detail="Separation of duties violation: the same person cannot grant both manager and final approval.",
                )

        # Unresolved findings / error flag gating before approval
        current_flags = await app_repo.get_flags(id, version=sub.version)
        blocking = _blocking_flags(current_flags)
        if payload.decision == "approve" and app_settings.enforce_approval_gates and blocking:
            reason = (payload.override_reason or "").strip()
            if not payload.override_unresolved or len(reason) < 10:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"Cannot approve: {len(blocking)} unresolved finding(s) remain open on v{sub.version}. "
                        "Resolve the issues or submit an authorised override with a written reason (at least 10 characters)."
                    ),
                )
            await record_audit(
                app_repo,
                id,
                effective_role,
                "authorised_override",
                f"Authorised override granted over {len(blocking)} unresolved finding(s) on v{sub.version}: {reason}",
                x_actor=actor_label,
            )

        now_iso = datetime.now(timezone.utc).isoformat()
        if payload.decision == "request_changes":
            # Preserve exact snapshot of the reviewed version before incrementing version
            await app_repo.save_version_snapshot(id, _snapshot_from_submission(sub))
            sub.status = "draft"
            sub.version += 1
            sub.manager_approved_by = None
        elif current_status == "manager_review":
            sub.status = "final_approval"
            if user:
                sub.manager_approved_by = user.user_id
        else:
            sub.status = "approved"

        sub.updated_at = now_iso
        await app_repo.update_submission(sub)
        if payload.decision == "approve":
            await app_repo.save_version_snapshot(id, _snapshot_from_submission(sub))

        decision_obj = Decision(
            id=str(uuid.uuid4()),
            submission_id=sub.id,
            role=effective_role,
            decision=payload.decision,
            comment=payload.comment,
            override_unresolved=bool(payload.override_unresolved and blocking),
            override_reason=(payload.override_reason or "").strip() or None,
            actor_user_id=user.user_id if user else None,
            actor_name=actor_label,
            version=sub.version,
            created_at=now_iso,
        )
        await app_repo.add_decision(decision_obj)
        await record_audit(
            app_repo,
            id,
            effective_role,
            "decision_recorded",
            f"Decision '{payload.decision}' recorded. Status changed to '{sub.status}', version {sub.version}",
            x_actor=actor_label,
            timestamp=now_iso,
        )
        return decision_obj

    @app.post("/submissions/{id}/comments", response_model=Comment, status_code=status.HTTP_201_CREATED)
    async def add_comment(
        id: str,
        payload: CommentRequest,
        x_actor: Optional[str] = Header(None, alias="X-Actor"),
        authorization: Optional[str] = Header(None, alias="Authorization"),
    ):
        """Add a review comment tied to current submission version."""
        user, effective_role, _, _ = _resolve_context(authorization, claimed_role=payload.role)
        sub = await get_sub_or_404(app_repo, id, user=user)
        if effective_role not in {"creator", "manager", "authorised_reviewer"}:
            raise HTTPException(403, f"Role '{effective_role}' is not authorized to comment")
        cleaned_text = payload.text.strip() if payload.text else None
        if not cleaned_text:
            raise HTTPException(422, "Comment text cannot be empty")

        now_iso = datetime.now(timezone.utc).isoformat()
        actor_label = user.name if user else x_actor
        comment_obj = Comment(
            id=str(uuid.uuid4()),
            submission_id=sub.id,
            role=effective_role,
            text=cleaned_text,
            version=sub.version,
            actor_name=actor_label,
            created_at=now_iso,
        )
        await app_repo.add_comment(comment_obj)
        await record_audit(
            app_repo,
            id,
            effective_role,
            "comment_added",
            f"Comment added by {effective_role} on version {sub.version}",
            x_actor=actor_label,
            timestamp=now_iso,
        )
        return comment_obj

    @app.get("/submissions/{id}/audit", response_model=List[AuditEvent])
    async def get_audit_trail(
        id: str,
        authorization: Optional[str] = Header(None, alias="Authorization"),
    ):
        """Get chronological audit events for submission."""
        user, _, _, _ = _resolve_context(authorization, require_explicit_role_when_unauth=False)
        await get_sub_or_404(app_repo, id, user=user)
        return await app_repo.get_audit_events(id)

    @app.get("/submissions/{id}/certificate")
    async def get_compliance_certificate(
        id: str,
        authorization: Optional[str] = Header(None, alias="Authorization"),
    ):
        """Generate an exportable pre-publication governance sign-off certificate."""
        user, _, _, _ = _resolve_context(authorization, require_explicit_role_when_unauth=False)
        sub = await get_sub_or_404(app_repo, id, user=user)
        flags = await app_repo.get_flags(id, version=sub.version)
        decisions = await app_repo.get_decisions(id)
        audit = await app_repo.get_audit_events(id)
        b_score, f_score, readiness = compute_fidelity_scores(flags)

        external_urls = list(
            dict.fromkeys(
                s.url
                for f in flags
                for s in (f.external_sources or [])
                if s.url and "unavailable.local" not in s.url
            )
        )
        guideline_refs = list(
            dict.fromkeys(
                f"{g.document} ({g.passage_ref})"
                for f in flags
                for g in (f.guideline_refs or ([f.guideline_ref] if f.guideline_ref else []))
            )
        )
        return {
            "certificate_id": f"CERT-{sub.id[:8].upper()}-V{sub.version}",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "organisation": sub.brand_name or sub.org_id,
            "submission": {
                "id": sub.id,
                "title": sub.title or "Untitled submission",
                "content_type": sub.content_type,
                "status": sub.status,
                "version": sub.version,
                "created_by": sub.created_by_name or sub.role,
            },
            "scores": {
                "brand_fidelity_score": b_score,
                "fact_confidence_score": f_score,
                "readiness_status": readiness,
                "total_flags": len(flags),
                "resolved_flags": sum(1 for f in flags if f.status in ("accepted", "dismissed", "resolved")),
                "unresolved_blocking": len(_blocking_flags(flags)),
            },
            "evidence_citations": {
                "brand_guidelines_consulted": guideline_refs,
                "external_sources_consulted": external_urls,
            },
            "decisions": [d.model_dump() for d in decisions if d.version == sub.version],
            "audit_events_count": len(audit),
        }

    # -----------------------------------------------------------------------
    # Insights, Disclosures & Tools
    # -----------------------------------------------------------------------

    @app.get("/insights/recurring", response_model=RecurringInsightsResponse)
    async def recurring_insights(
        authorization: Optional[str] = Header(None, alias="Authorization"),
    ):
        """Aggregate recurring compliance insights scoped to the active organisation."""
        user, _, org_id, _ = _resolve_context(authorization, require_explicit_role_when_unauth=False)
        all_flags = await app_repo.get_all_flags(org_id=org_id if user else None)
        guideline_counts: Counter[str] = Counter()
        state_counts: Counter[str] = Counter()

        for flag in all_flags:
            state_counts[flag.state] += 1
            if flag.guideline_ref:
                guideline_counts[
                    f"{flag.guideline_ref.document} - {flag.guideline_ref.passage_ref}"
                ] += 1

        top_guidelines = [
            {"guideline": g, "count": c}
            for g, c in guideline_counts.most_common(10)
        ]

        gov_dict = None
        try:
            gov_out = generate_governance_insights(flags=all_flags)
            gov_dict = gov_out.model_dump()
        except Exception as exc:
            logger.warning("Governance insights generation failed: %s", exc)

        return RecurringInsightsResponse(
            top_guidelines=top_guidelines,
            state_counts=dict(state_counts),
            total_flags=len(all_flags),
            governance_insights=gov_dict,
        )

    @app.get("/insights/governance")
    async def governance_insights(
        authorization: Optional[str] = Header(None, alias="Authorization"),
    ):
        """Generate executive governance intelligence scoped to the active organisation."""
        user, _, org_id, _ = _resolve_context(authorization, require_explicit_role_when_unauth=False)
        all_flags = await app_repo.get_all_flags(org_id=org_id if user else None)
        return generate_governance_insights(flags=all_flags)

    @app.get("/disclosures", response_model=DisclosuresResponse)
    async def get_disclosures():
        """Retrieve external services disclosure metadata."""
        enabled_list = app_settings.enabled_services
        items = [
            DisclosureItem(
                name=meta["name"],
                service_id=service_id,
                description=meta["description"],
                enabled=service_id in enabled_list,
            )
            for service_id, meta in SERVICE_DEFINITIONS.items()
        ]
        return DisclosuresResponse(
            external_services=items,
            services_enabled=enabled_list,
            human_in_the_loop_notice=(
                "Publication is always a human decision. AI recommendations "
                "are advisory and require explicit manager and authorised reviewer approval."
            ),
        )

    @app.get("/tools/contrast", response_model=ContrastResponse)
    async def check_contrast(fg: str = Query(...), bg: str = Query(...)):
        """Calculate WCAG contrast ratio for color pairs."""
        try:
            ratio = compute_contrast_ratio(fg, bg)
        except ValueError as exc:
            raise HTTPException(422, f"Invalid hex color input: {exc}")
        formatted_fg = fg if fg.startswith("#") else f"#{fg}"
        formatted_bg = bg if bg.startswith("#") else f"#{bg}"
        return ContrastResponse(
            fg=formatted_fg,
            bg=formatted_bg,
            contrast_ratio=ratio,
            aa_normal=ratio >= 4.5,
            aa_large=ratio >= 3.0,
            aaa_normal=ratio >= 7.0,
        )

    # -----------------------------------------------------------------------
    # Brand Knowledge Base, Brand Constitution & Guideline Rectification
    # (Static routes declared BEFORE /brand-docs/{doc_id}!)
    # -----------------------------------------------------------------------

    @app.get("/brand-constitution")
    async def brand_constitution(
        authorization: Optional[str] = Header(None, alias="Authorization"),
    ):
        """Return the compiled one-time Brand Constitution for the active organisation."""
        _, _, org_id, brand_name = _resolve_context(authorization, require_explicit_role_when_unauth=False)
        from retrieval.brand_rag import get_brand_constitution

        data = await run_in_threadpool(get_brand_constitution, org_id)
        data["brand_name"] = brand_name
        return data

    @app.get("/brand-docs/rectifications")
    async def list_guideline_rectifications(
        authorization: Optional[str] = Header(None, alias="Authorization"),
    ):
        """List pending and historical guideline rectification proposals for the active org."""
        _, _, org_id, _ = _resolve_context(authorization, require_explicit_role_when_unauth=False)
        items = await app_repo.list_rectifications(org_id)
        return {"rectifications": [r.model_dump() for r in items]}

    @app.post("/brand-docs/rectifications/scan")
    async def scan_guideline_rectifications(
        authorization: Optional[str] = Header(None, alias="Authorization"),
    ):
        """Scan active org guidelines and historical flags for unclear, conflicting, duplicate, or expired rules."""
        user, effective_role, org_id, _ = _resolve_context(
            authorization,
            require_explicit_role_when_unauth=False,
        )
        if user:
            require_role(effective_role, {"creator", "manager", "authorised_reviewer"}, "scan guidelines for rectification")
        from retrieval.brand_rag import get_org_active_chunks

        chunks = await run_in_threadpool(get_org_active_chunks, org_id)
        hist_flags = await app_repo.get_all_flags(org_id=org_id if user else None)
        proposals = await run_in_threadpool(
            scan_guidelines_for_rectification,
            chunks,
            hist_flags,
            org_id,
        )
        saved = await app_repo.save_rectifications(org_id, proposals)
        return {"rectifications": [r.model_dump() for r in saved], "scanned_chunks": len(chunks)}

    @app.post("/brand-docs/rectifications/{rect_id}/approve")
    async def approve_guideline_rectification(
        rect_id: str,
        payload: Optional[RectificationApproveRequest] = None,
        authorization: Optional[str] = Header(None, alias="Authorization"),
    ):
        """Manager edits/approves a rectification, publishing a new active guideline version while keeping the old one."""
        claimed = payload.role if payload else None
        user, effective_role, org_id, _ = _resolve_context(
            authorization,
            claimed_role=claimed,
            require_explicit_role_when_unauth=False,
        )
        role = effective_role if user else (claimed or "manager")
        require_role(role, {"creator", "manager"}, "approve guideline rectifications")

        rect = await app_repo.get_rectification(org_id, rect_id)
        if not rect:
            raise HTTPException(404, "Guideline rectification proposal not found.")
        if rect.status == "approved":
            raise HTTPException(409, "This guideline rectification has already been approved.")

        approved_text = (
            payload.approved_wording.strip()
            if payload and payload.approved_wording and payload.approved_wording.strip()
            else rect.suggested_wording
        )
        actor_name = user.name if user else role

        from retrieval.brand_rag import create_rectified_brand_doc_version

        try:
            new_doc = await run_in_threadpool(
                create_rectified_brand_doc_version,
                rect.document_id,
                rect.chunk_id,
                approved_text,
                org_id,
                actor_name,
            )
        except ValueError as exc:
            raise HTTPException(422, str(exc))

        rect.status = "approved"
        rect.approved_wording = approved_text
        rect.reviewed_by = actor_name
        rect.reviewed_at = datetime.now(timezone.utc).isoformat()
        rect.new_document_id = new_doc.id
        rect.new_version = new_doc.version
        await app_repo.update_rectification(rect)
        return {"rectification": rect.model_dump(), "new_document": new_doc.model_dump()}

    @app.post("/brand-docs/rectifications/{rect_id}/dismiss")
    async def dismiss_guideline_rectification(
        rect_id: str,
        payload: Optional[RectificationDismissRequest] = None,
        authorization: Optional[str] = Header(None, alias="Authorization"),
    ):
        """Manager dismisses a guideline rectification proposal."""
        claimed = payload.role if payload else None
        user, effective_role, org_id, _ = _resolve_context(
            authorization,
            claimed_role=claimed,
            require_explicit_role_when_unauth=False,
        )
        role = effective_role if user else (claimed or "manager")
        require_role(role, {"creator", "manager"}, "dismiss guideline rectifications")

        rect = await app_repo.get_rectification(org_id, rect_id)
        if not rect:
            raise HTTPException(404, "Guideline rectification proposal not found.")

        rect.status = "dismissed"
        rect.reviewed_by = user.name if user else role
        rect.reviewed_at = datetime.now(timezone.utc).isoformat()
        await app_repo.update_rectification(rect)
        return {"rectification": rect.model_dump()}

    @app.get("/brand-docs")
    async def list_brand_documents(
        include_inactive: bool = False,
        authorization: Optional[str] = Header(None, alias="Authorization"),
    ):
        """List brand knowledge documents strictly scoped to the active organisation."""
        user, _, org_id, _ = _resolve_context(authorization, require_explicit_role_when_unauth=False)
        try:
            from retrieval.brand_rag import list_brand_docs

            docs = await run_in_threadpool(
                list_brand_docs,
                include_inactive,
                org_id if user else None,
            )
            return {"documents": docs}
        except Exception as exc:
            logger.warning("Failed to list brand documents: %s", exc)
            raise HTTPException(502, f"Could not load brand documents: {exc}")

    @app.get("/brand-docs/{doc_id}/versions")
    async def get_brand_document_versions(
        doc_id: str,
        authorization: Optional[str] = Header(None, alias="Authorization"),
    ):
        """List active and preserved historical versions of a brand document."""
        _, _, org_id, _ = _resolve_context(authorization, require_explicit_role_when_unauth=False)
        from retrieval.brand_rag import list_brand_doc_versions

        versions = await run_in_threadpool(list_brand_doc_versions, doc_id, org_id)
        return {"versions": versions}

    @app.post("/brand-docs", status_code=status.HTTP_201_CREATED)
    async def upload_brand_document(
        title: str = Form(...),
        category: str = Form("guideline"),
        version: str = Form("1.0"),
        file: UploadFile = File(...),
        authorization: Optional[str] = Header(None, alias="Authorization"),
    ):
        """Extract, chunk, compile Brand Constitution, embed, and ingest an org-scoped brand document."""
        user, effective_role, org_id, brand_name = _resolve_context(
            authorization,
            require_explicit_role_when_unauth=False,
        )
        if user:
            require_role(effective_role, {"creator", "manager", "authorised_reviewer"}, "upload brand guidelines")

        clean_title = title.strip()
        if not clean_title:
            raise HTTPException(422, "Document title is required.")
        raw_bytes = await file.read()
        if not raw_bytes:
            raise HTTPException(422, "Uploaded file is empty.")
        if len(raw_bytes) > MAX_PDF_SIZE:
            raise HTTPException(413, "Brand document exceeds 10MB limit.")

        try:
            from retrieval.brand_rag import ingest_brand_doc

            record = await run_in_threadpool(
                ingest_brand_doc,
                file_bytes=raw_bytes,
                filename=file.filename or "brand_document.pdf",
                title=clean_title,
                category=category.strip() or "guideline",
                version=version.strip() or "1.0",
                org_id=org_id,
                brand_name=brand_name,
            )
            return record.model_dump()
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        except Exception as exc:
            logger.error("Brand document ingestion failed: %s", exc, exc_info=True)
            raise HTTPException(502, f"Brand document ingestion failed: {exc}")

    @app.delete("/brand-docs/{doc_id}")
    async def remove_brand_document(
        doc_id: str,
        authorization: Optional[str] = Header(None, alias="Authorization"),
    ):
        """Deactivate (soft-delete) a brand document within the active organisation."""
        user, effective_role, org_id, _ = _resolve_context(
            authorization,
            require_explicit_role_when_unauth=False,
        )
        if user:
            require_role(effective_role, {"creator", "manager", "authorised_reviewer"}, "deactivate brand guidelines")
        try:
            from retrieval.brand_rag import deactivate_brand_doc

            updated = await run_in_threadpool(
                deactivate_brand_doc,
                document_id=doc_id,
                org_id=org_id if user else None,
            )
            if not updated:
                raise HTTPException(404, "Brand document not found.")
            return {"status": "deactivated", "id": doc_id}
        except HTTPException:
            raise
        except Exception as exc:
            logger.error("Failed to deactivate brand document: %s", exc)
            raise HTTPException(502, f"Could not deactivate brand document: {exc}")

    @app.post("/demo/seed")
    async def demo_seed(
        authorization: Optional[str] = Header(None, alias="Authorization"),
    ):
        """Seed 3 sample submissions for live judging demonstrations."""
        if not app_settings.demo_mode:
            raise HTTPException(403, "Demo mode is disabled. Set DEMO_MODE=true to enable seeding.")
        org_id = "inkloom"
        brand_name = "Inkloom AI"
        if authorization:
            user = resolve_auth_context(authorization, app_settings)
            if user:
                org_id = user.org_id
                brand_name = user.brand_name
        seeded = await _seed_data(org_id=org_id, brand_name=brand_name)
        return {"status": "ok", "message": "Demo submissions seeded successfully", "submissions": seeded}

    return app


app = create_app()
