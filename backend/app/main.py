"""FastAPI Application for Inkloom AI compliance governance."""

from collections import Counter
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import logging
from typing import List, Optional, Set
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
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException as StarletteHTTPException

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
    Flag,
    RecurringInsightsResponse,
    RecheckRequest,
    RecheckResponse,
    ResolutionRequest,
    Submission,
    SubmissionDetailResponse,
    SubmissionListItem,
    VersionInfo,
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


async def get_sub_or_404(repo: SubmissionRepository, sub_id: str) -> Submission:
    sub = await repo.get_submission(sub_id)
    if not sub:
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


def require_role(role: str, allowed: Set[str], context: str = ""):
    if role not in allowed:
        msg = f"Only creators can {context}" if allowed == {"creator"} else (
            f"Role '{role}' is not authorized for {context}" if context else f"Role '{role}' is not authorized"
        )
        raise HTTPException(status_code=403, detail=msg)


def create_app(
    repo: Optional[SubmissionRepository] = None,
    settings: Optional[Settings] = None,
) -> FastAPI:
    """Application factory for FastAPI app with injectable repository and settings."""
    app_settings = settings or Settings()
    app_repo = repo or get_repository(app_settings.repo_backend)

    async def _seed_data() -> List[Submission]:
        now_iso = datetime.now(timezone.utc).isoformat()
        seeds = [
            (
                "Summer Campaign Announcement",
                "Small business owners",
                "Marketing email",
                "Reviewing new promotional email draft for tone consistency and claim accuracy.",
                "draft",
                "Inkloom AI helps distributed marketing teams prevent brand violations.",
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
                title=title,
                audience=audience,
                channel=channel,
                context=context,
                text=txt,
                created_at=now_iso,
                updated_at=now_iso,
            )
            await app_repo.create_submission(sub)
            await record_audit(
                app_repo, sub.id, "creator", "created",
                f"Demo submission {idx} created" + (f" ({st})" if st == "draft" else ""),
                timestamp=now_iso,
            )
            if run_pipe:
                fl, _ = run_pipeline(ContentPayload(content_type="text", text=txt), sub.id, 1)
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

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if app_settings.demo_mode:
            existing = await app_repo.list_submissions()
            if not existing:
                await _seed_data()
        yield

    app = FastAPI(
        title="Inkloom Compliance API",
        version="1.0.0",
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
        codes = {400: "bad_request", 403: "forbidden", 404: "not_found", 409: "conflict", 422: "unprocessable_entity", 500: "internal_error"}
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

    @app.get("/health")
    async def health():
        """Health check probe."""
        return {"status": "ok"}

    @app.get("/submissions", response_model=List[SubmissionListItem])
    async def list_submissions(status: Optional[str] = Query(None)):
        """List all submissions with flag summaries."""
        submissions = await app_repo.list_submissions(status=status)
        results = []
        for sub in submissions:
            flags = await app_repo.get_flags(sub.id, version=sub.version)
            results.append(
                SubmissionListItem(
                    id=sub.id,
                    content_type=sub.content_type,
                    status=sub.status,
                    version=sub.version,
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
        role: str = Form(...),
        title: Optional[str] = Form(None),
        audience: Optional[str] = Form(None),
        channel: Optional[str] = Form(None),
        context: Optional[str] = Form(None),
        text: Optional[str] = Form(None),
        file: Optional[UploadFile] = File(None),
        x_actor: Optional[str] = Header(None, alias="X-Actor"),
    ):
        """Create a new compliance submission."""
        require_role(role, {"creator"}, "create submissions")
        cleaned_text, file_bytes, file_name, file_mime = (
            await validate_submission_payload(content_type, text, file)
        )
        now_iso = datetime.now(timezone.utc).isoformat()
        sub_id = str(uuid.uuid4())
        submission = Submission(
            id=sub_id,
            content_type=content_type,
            role=role,
            status="draft",
            version=1,
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
        await record_audit(
            app_repo,
            sub_id,
            role,
            "created",
            f"Submission created with content_type={content_type}",
            x_actor=x_actor,
            timestamp=now_iso,
        )
        return submission

    @app.post("/submissions/{id}/revise")
    async def revise_submission(
        id: str,
        content_type: str = Form(...),
        role: str = Form(...),
        title: Optional[str] = Form(None),
        audience: Optional[str] = Form(None),
        channel: Optional[str] = Form(None),
        context: Optional[str] = Form(None),
        text: Optional[str] = Form(None),
        file: Optional[UploadFile] = File(None),
        x_actor: Optional[str] = Header(None, alias="X-Actor"),
    ):
        """Revise draft content before review."""
        sub = await get_sub_or_404(app_repo, id)
        require_role(role, {"creator"}, "revise submissions")
        if sub.status != "draft":
            raise HTTPException(
                status_code=409,
                detail=f"Cannot revise submission in '{sub.status}' state. Must be 'draft'",
            )

        cleaned_text, file_bytes, file_name, file_mime = (
            await validate_submission_payload(content_type, text, file)
        )
        now_iso = datetime.now(timezone.utc).isoformat()
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
        sub.updated_at = now_iso

        await app_repo.update_submission(sub)
        await record_audit(
            app_repo,
            id,
            role,
            "revised",
            f"Submission revised with content_type={content_type}",
            x_actor=x_actor,
            timestamp=now_iso,
        )
        return sub

    @app.get("/submissions/{id}/file")
    async def get_submission_file(id: str):
        """Retrieve binary file bytes for image or PDF submission."""
        sub = await get_sub_or_404(app_repo, id)
        if sub.content_type == "text" or not sub.file_bytes:
            raise HTTPException(
                status_code=404, detail="File not found for text submission"
            )
        return Response(
            content=sub.file_bytes,
            media_type=sub.file_mime or "application/octet-stream",
        )

    @app.post("/submissions/{id}/flags/{flag_id}/resolution", response_model=Flag)
    async def resolve_flag(
        id: str,
        flag_id: str,
        payload: ResolutionRequest,
        x_actor: Optional[str] = Header(None, alias="X-Actor"),
    ):
        """Resolve a specific flag (accept or dismiss)."""
        sub = await get_sub_or_404(app_repo, id)
        role = payload.role or "creator"
        require_role(role, {"creator"}, "resolve flags")
        if payload.action not in {"accept", "dismiss"}:
            raise HTTPException(
                status_code=422, detail="Action must be 'accept' or 'dismiss'"
            )

        flags = await app_repo.get_flags(id, version=sub.version)
        target_flag = await _find_flag(app_repo, id, flag_id, sub.version)

        now_iso = datetime.now(timezone.utc).isoformat()
        if payload.action == "accept":
            if sub.content_type == "text":
                current_text = sub.text or ""
                if target_flag.passage not in current_text:
                    raise HTTPException(
                        status_code=409,
                        detail=f"Flag passage '{target_flag.passage}' was not found in the current text",
                    )
                if target_flag.suggested_correction:
                    sub.text = current_text.replace(
                        target_flag.passage, target_flag.suggested_correction, 1
                    )
                    sub.updated_at = now_iso
                    await app_repo.update_submission(sub)
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
            x_actor=x_actor,
            timestamp=now_iso,
        )
        return target_flag

    @app.post("/submissions/{id}/flags/{flag_id}/recheck", response_model=RecheckResponse)
    async def recheck_flag(
        id: str,
        flag_id: str,
        payload: Optional[RecheckRequest] = None,
        x_actor: Optional[str] = Header(None, alias="X-Actor"),
    ):
        """Simulate applying flag correction and recheck in threadpool."""
        role = payload.role if payload and payload.role else "creator"
        require_role(role, {"creator"}, "recheck flags")
        sub = await get_sub_or_404(app_repo, id)
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
            content_type="text", text=candidate_text
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
            x_actor=x_actor,
        )
        return RecheckResponse(
            new_flags=new_flags,
            original_flag_gone=original_flag_gone,
            has_needs_human=has_needs_human,
        )

    @app.get("/submissions/{id}/versions", response_model=List[VersionInfo])
    async def get_submission_versions(id: str):
        """List historical versions and flag counts."""
        await get_sub_or_404(app_repo, id)
        results = []
        for v in await app_repo.get_versions(id):
            v_flags = await app_repo.get_flags(id, version=v)
            results.append(VersionInfo(version=v, flag_count=len(v_flags), needs_human_count=sum(1 for f in v_flags if f.needs_human)))
        return results

    @app.post("/submissions/{id}/check", response_model=CheckResponse)
    async def check_submission(
        id: str,
        payload: CheckRequest,
        x_actor: Optional[str] = Header(None, alias="X-Actor"),
    ):
        """Run compliance review pipeline asynchronously in threadpool."""
        sub = await get_sub_or_404(app_repo, id)
        require_role(payload.role, {"creator"}, "run checks")
        if sub.status != "draft":
            raise HTTPException(
                status_code=409,
                detail=f"Cannot run check on submission in state '{sub.status}'. Must be 'draft'",
            )

        now_iso = datetime.now(timezone.utc).isoformat()
        sub.status = "ai_review"
        sub.updated_at = now_iso
        await app_repo.update_submission(sub)
        await record_audit(
            app_repo,
            id,
            payload.role,
            "check_started",
            "Compliance check pipeline started",
            x_actor=x_actor,
            timestamp=now_iso,
        )

        content = ContentPayload(
            content_type=sub.content_type,
            text=sub.text,
            file_name=sub.file_name,
            file_mime=sub.file_mime,
            file_bytes=sub.file_bytes,
        )
        flags, degraded_modules = await run_in_threadpool(
            run_pipeline, content, sub.id, sub.version
        )

        for dm in degraded_modules:
            await record_audit(
                app_repo,
                id,
                payload.role,
                "module_fallback",
                f"{dm.module}: {dm.error}",
                x_actor=x_actor,
            )

        await app_repo.set_flags(id, flags, version=sub.version)
        completed_iso = datetime.now(timezone.utc).isoformat()
        sub.status = "manager_review"
        sub.updated_at = completed_iso
        await app_repo.update_submission(sub)

        await record_audit(
            app_repo,
            id,
            payload.role,
            "check_completed",
            f"Check completed with {len(flags)} flags",
            x_actor=x_actor,
            timestamp=completed_iso,
        )
        return CheckResponse(
            submission=sub, flags=flags, degraded_modules=degraded_modules
        )

    @app.get("/submissions/{id}", response_model=SubmissionDetailResponse)
    async def get_submission_detail(id: str, version: Optional[int] = Query(None)):
        """Get full details of a submission."""
        sub = await get_sub_or_404(app_repo, id)
        return SubmissionDetailResponse(
            submission=sub,
            flags=await app_repo.get_flags(id, version=version),
            comments=await app_repo.get_comments(id),
            decisions=await app_repo.get_decisions(id),
        )

    @app.post("/submissions/{id}/decision", response_model=Decision)
    async def record_decision(
        id: str,
        payload: DecisionRequest,
        x_actor: Optional[str] = Header(None, alias="X-Actor"),
    ):
        """Record manager or reviewer approval decision."""
        sub = await get_sub_or_404(app_repo, id)
        if payload.decision not in {"approve", "request_changes"}:
            raise HTTPException(422, "Decision must be 'approve' or 'request_changes'")
        if sub.status not in {"manager_review", "final_approval"}:
            raise HTTPException(409, f"Cannot record decision in state '{sub.status}'")

        if sub.status == "manager_review":
            require_role(payload.role, {"manager"}, "manager_review")
            sub.status = "final_approval" if payload.decision == "approve" else "draft"
        else:
            require_role(payload.role, {"authorised_reviewer"}, "final_approval")
            sub.status = "approved" if payload.decision == "approve" else "draft"
        if payload.decision == "request_changes":
            sub.version += 1

        now_iso = datetime.now(timezone.utc).isoformat()
        sub.updated_at = now_iso
        await app_repo.update_submission(sub)

        decision_obj = Decision(
            id=str(uuid.uuid4()),
            submission_id=sub.id,
            role=payload.role,
            decision=payload.decision,
            comment=payload.comment,
            version=sub.version,
            created_at=now_iso,
        )
        await app_repo.add_decision(decision_obj)
        await record_audit(
            app_repo,
            id,
            payload.role,
            "decision_recorded",
            f"Decision '{payload.decision}' recorded. Status changed to '{sub.status}', version {sub.version}",
            x_actor=x_actor,
            timestamp=now_iso,
        )
        return decision_obj

    @app.post("/submissions/{id}/comments", response_model=Comment, status_code=status.HTTP_201_CREATED)
    async def add_comment(
        id: str,
        payload: CommentRequest,
        x_actor: Optional[str] = Header(None, alias="X-Actor"),
    ):
        """Add a review comment tied to current submission version."""
        sub = await get_sub_or_404(app_repo, id)
        if payload.role not in {"creator", "manager", "authorised_reviewer"}:
            raise HTTPException(403, f"Role '{payload.role}' is not authorized to comment")
        cleaned_text = payload.text.strip() if payload.text else None
        if not cleaned_text:
            raise HTTPException(422, "Comment text cannot be empty")

        now_iso = datetime.now(timezone.utc).isoformat()
        comment_obj = Comment(
            id=str(uuid.uuid4()),
            submission_id=sub.id,
            role=payload.role,
            text=cleaned_text,
            version=sub.version,
            created_at=now_iso,
        )
        await app_repo.add_comment(comment_obj)
        await record_audit(
            app_repo,
            id,
            payload.role,
            "comment_added",
            f"Comment added by {payload.role} on version {sub.version}",
            x_actor=x_actor,
            timestamp=now_iso,
        )
        return comment_obj

    @app.get("/submissions/{id}/audit", response_model=List[AuditEvent])
    async def get_audit_trail(id: str):
        """Get chronological audit events for submission."""
        await get_sub_or_404(app_repo, id)
        return await app_repo.get_audit_events(id)

    @app.get("/insights/recurring", response_model=RecurringInsightsResponse)
    async def recurring_insights():
        """Aggregate recurring compliance insights across submissions in a single pass."""
        all_flags = await app_repo.get_all_flags()
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

        # Connect historical flags to Sera's Governance Intelligence
        gov_dict = None
        try:
            from app.ai.governance_intelligence import generate_governance_insights

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
    async def governance_insights():
        """Generate executive governance intelligence from historical compliance flags."""
        all_flags = await app_repo.get_all_flags()
        from app.ai.governance_intelligence import generate_governance_insights

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

    @app.get("/brand-docs")
    async def list_brand_documents(include_inactive: bool = False):
        """List approved brand knowledge documents stored in Supabase RAG."""
        try:
            from retrieval.config import SUPABASE_KEY, SUPABASE_URL
            if not (SUPABASE_URL and SUPABASE_KEY):
                return {"documents": []}
            from retrieval.brand_rag import list_brand_docs

            docs = await run_in_threadpool(list_brand_docs, include_inactive)
            return {"documents": docs}
        except Exception as exc:
            logger.warning("Failed to list brand documents: %s", exc)
            raise HTTPException(502, f"Could not load brand documents: {exc}")

    @app.post("/brand-docs", status_code=status.HTTP_201_CREATED)
    async def upload_brand_document(
        title: str = Form(...),
        category: str = Form("guideline"),
        version: str = Form("1.0"),
        file: UploadFile = File(...),
    ):
        """Extract, chunk, embed, and ingest a brand document into Supabase pgvector RAG."""
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
            )
            return record.model_dump()
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        except Exception as exc:
            logger.error("Brand document ingestion failed: %s", exc, exc_info=True)
            raise HTTPException(502, f"Brand document ingestion failed: {exc}")

    @app.delete("/brand-docs/{doc_id}")
    async def remove_brand_document(doc_id: str):
        """Deactivate (soft-delete) a brand document so RAG ignores outdated rules."""
        try:
            from retrieval.brand_rag import deactivate_brand_doc

            updated = await run_in_threadpool(deactivate_brand_doc, document_id=doc_id)
            if not updated:
                raise HTTPException(404, "Brand document not found.")
            return {"status": "deactivated", "id": doc_id}
        except HTTPException:
            raise
        except Exception as exc:
            logger.error("Failed to deactivate brand document: %s", exc)
            raise HTTPException(502, f"Could not deactivate brand document: {exc}")

    @app.post("/demo/seed")
    async def demo_seed():
        """Seed 3 sample submissions for live judging demonstrations."""
        if not app_settings.demo_mode:
            raise HTTPException(403, "Demo mode is disabled. Set DEMO_MODE=true to enable seeding.")
        seeded = await _seed_data()
        return {"status": "ok", "message": "Demo submissions seeded successfully", "submissions": seeded}

    return app


app = create_app()
