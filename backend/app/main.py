"""FastAPI Application for Inkloom AI compliance governance."""

from collections import Counter
import logging
import uuid
from datetime import datetime, timezone
from typing import List, Optional

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

ALLOWED_IMAGE_PREFIXES = (
    b"\x89PNG\r\n\x1a\n",  # PNG
    b"\xff\xd8\xff",  # JPEG
)
MAX_TEXT_LENGTH = 50000
MAX_IMAGE_SIZE = 5 * 1024 * 1024
MAX_PDF_SIZE = 10 * 1024 * 1024

SERVICE_DEFINITIONS = {
    "gemini": {
        "name": "Gemini",
        "description": "Google Gemini multimodal engine for guideline analysis and claim parsing",
    },
    "exa": {
        "name": "Exa",
        "description": "Exa neural search for external claim reference discovery",
    },
    "tinyfish": {
        "name": "TinyFish",
        "description": "TinySearch and TinyFetch for live web verification and factual grounding",
    },
    "supabase": {
        "name": "Supabase",
        "description": "Supabase PostgreSQL vector and relational store",
    },
}


def is_valid_image(data: bytes) -> bool:
    """Validate image bytes for PNG, JPEG, or WEBP magic headers."""
    if data.startswith(ALLOWED_IMAGE_PREFIXES):
        return True
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return True
    return False


def parse_hex_color(hex_str: str) -> tuple[float, float, float]:
    """Parse hex color into normalized RGB components, raising ValueError on failure."""
    raw = hex_str.strip()
    if raw.startswith("#"):
        raw = raw[1:]
    if len(raw) == 3:
        raw = "".join(c * 2 for c in raw)
    if len(raw) != 6:
        raise ValueError(f"Invalid hex color length for '{hex_str}'")
    try:
        r = int(raw[0:2], 16) / 255.0
        g = int(raw[2:4], 16) / 255.0
        b = int(raw[4:6], 16) / 255.0
    except ValueError as exc:
        raise ValueError(f"Invalid hex character in '{hex_str}'") from exc
    return r, g, b


def channel_luminance(c: float) -> float:
    """Convert sRGB channel value to linear luminance component."""
    if c <= 0.04045:
        return c / 12.92
    return ((c + 0.055) / 1.055) ** 2.4


def relative_luminance(r: float, g: float, b: float) -> float:
    """Calculate WCAG relative luminance."""
    r_lum = channel_luminance(r)
    g_lum = channel_luminance(g)
    b_lum = channel_luminance(b)
    return 0.2126 * r_lum + 0.7152 * g_lum + 0.0722 * b_lum


def compute_contrast_ratio(fg: str, bg: str) -> float:
    """Calculate WCAG contrast ratio between foreground and background colors."""
    r1, g1, b1 = parse_hex_color(fg)
    r2, g2, b2 = parse_hex_color(bg)
    lum1 = relative_luminance(r1, g1, b1)
    lum2 = relative_luminance(r2, g2, b2)
    lighter = max(lum1, lum2)
    darker = min(lum1, lum2)
    return round((lighter + 0.05) / (darker + 0.05), 2)


async def validate_submission_payload(
    content_type: str,
    text: Optional[str],
    file: Optional[UploadFile],
) -> tuple[Optional[str], Optional[bytes], Optional[str], Optional[str]]:
    """Validate multipart content and return cleaned text, bytes, filename, and mime."""
    if content_type not in {"text", "image", "pdf"}:
        raise HTTPException(
            status_code=422,
            detail="Invalid content_type. Must be text, image, or pdf",
        )

    file_bytes: Optional[bytes] = None
    file_name: Optional[str] = None
    file_mime: Optional[str] = None
    cleaned_text = text.strip() if text else None

    if content_type == "text":
        if file is not None and file.filename:
            raise HTTPException(
                status_code=422,
                detail="File upload not allowed when content_type is text",
            )
        if not cleaned_text:
            raise HTTPException(
                status_code=422,
                detail="Text content cannot be empty",
            )
        if len(cleaned_text) > MAX_TEXT_LENGTH:
            raise HTTPException(
                status_code=422,
                detail=f"Text content exceeds {MAX_TEXT_LENGTH} characters limit",
            )

    elif content_type == "image":
        if cleaned_text:
            raise HTTPException(
                status_code=422,
                detail="Text content not allowed when content_type is image",
            )
        if file is None or not file.filename:
            raise HTTPException(
                status_code=422,
                detail="File is required for image submission",
            )
        file_bytes = await file.read()
        if len(file_bytes) > MAX_IMAGE_SIZE:
            raise HTTPException(
                status_code=422,
                detail=f"Image exceeds {MAX_IMAGE_SIZE} bytes limit (5MB)",
            )
        if not is_valid_image(file_bytes):
            raise HTTPException(
                status_code=422,
                detail="Invalid image format. Allowed formats are PNG, JPEG, WEBP",
            )
        file_name = file.filename
        file_mime = file.content_type

    elif content_type == "pdf":
        if cleaned_text:
            raise HTTPException(
                status_code=422,
                detail="Text content not allowed when content_type is pdf",
            )
        if file is None or not file.filename:
            raise HTTPException(
                status_code=422,
                detail="File is required for pdf submission",
            )
        file_bytes = await file.read()
        if len(file_bytes) > MAX_PDF_SIZE:
            raise HTTPException(
                status_code=422,
                detail=f"PDF exceeds {MAX_PDF_SIZE} bytes limit (10MB)",
            )
        if not file_bytes.startswith(b"%PDF-"):
            raise HTTPException(
                status_code=422,
                detail="Invalid PDF format. File must start with %PDF-",
            )
        file_name = file.filename
        file_mime = file.content_type

    return cleaned_text, file_bytes, file_name, file_mime


def create_app(
    repo: Optional[SubmissionRepository] = None,
    settings: Optional[Settings] = None,
) -> FastAPI:
    """Application factory for FastAPI app with injectable repository and settings."""
    app_settings = settings or Settings()
    app_repo = repo or get_repository(app_settings.repo_backend)

    app = FastAPI(
        title="Inkloom Compliance API",
        version="1.0.0",
        docs_url="/docs",
        openapi_url="/openapi.json",
    )

    app.state.settings = app_settings
    app.state.repo = app_repo

    # CORS configuration
    if app_settings.cors_origins:
        allow_all = app_settings.cors_origins == ["*"]
        app.add_middleware(
            CORSMiddleware,
            allow_origins=app_settings.cors_origins,
            allow_credentials=not allow_all,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    # Global Exception Handlers
    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(
        request: Request, exc: StarletteHTTPException
    ):
        code_map = {
            400: "bad_request",
            403: "forbidden",
            404: "not_found",
            409: "conflict",
            422: "unprocessable_entity",
            500: "internal_error",
        }
        code = code_map.get(exc.status_code, "http_error")
        message = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": code, "message": message}},
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ):
        errors = exc.errors()
        messages = []
        for err in errors:
            loc = ".".join(str(l) for l in err.get("loc", []))
            msg = err.get("msg", "Invalid input")
            messages.append(f"{loc}: {msg}" if loc else msg)
        message = "; ".join(messages) if messages else "Validation failed"
        return JSONResponse(
            status_code=422,
            content={"error": {"code": "validation_error", "message": message}},
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        logger.error("Unhandled exception: %s", exc, exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "internal_error",
                    "message": "An internal server error occurred",
                }
            },
        )

    # Routes
    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.get("/submissions", response_model=List[SubmissionListItem])
    async def list_submissions(status: Optional[str] = Query(None)):
        submissions = await app_repo.list_submissions(status=status)
        results = []
        for sub in submissions:
            flags = await app_repo.get_flags(sub.id, version=sub.version)
            flag_count = len(flags)
            needs_human_count = sum(1 for f in flags if f.needs_human)
            results.append(
                SubmissionListItem(
                    id=sub.id,
                    content_type=sub.content_type,
                    status=sub.status,
                    version=sub.version,
                    created_at=sub.created_at,
                    flag_count=flag_count,
                    needs_human_count=needs_human_count,
                )
            )
        return results

    @app.post("/submissions", status_code=status.HTTP_201_CREATED)
    async def create_submission(
        content_type: str = Form(...),
        role: str = Form(...),
        text: Optional[str] = Form(None),
        file: Optional[UploadFile] = File(None),
        x_actor: Optional[str] = Header(None, alias="X-Actor"),
    ):
        if role != "creator":
            raise HTTPException(
                status_code=403,
                detail="Only creators can create submissions",
            )

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
            text=cleaned_text,
            file_name=file_name,
            file_mime=file_mime,
            file_size=len(file_bytes) if file_bytes else None,
            file_bytes=file_bytes,
            created_at=now_iso,
            updated_at=now_iso,
        )
        await app_repo.create_submission(submission)

        actor = x_actor.strip() if x_actor and x_actor.strip() else role
        await app_repo.add_audit_event(
            sub_id,
            AuditEvent(
                actor_role=role,
                action="created",
                detail=f"Submission created with content_type={content_type}",
                timestamp=now_iso,
                actor=actor,
            ),
        )

        return submission

    @app.post("/submissions/{id}/revise")
    async def revise_submission(
        id: str,
        content_type: str = Form(...),
        role: str = Form(...),
        text: Optional[str] = Form(None),
        file: Optional[UploadFile] = File(None),
        x_actor: Optional[str] = Header(None, alias="X-Actor"),
    ):
        sub = await app_repo.get_submission(id)
        if not sub:
            raise HTTPException(status_code=404, detail="Submission not found")

        if role != "creator":
            raise HTTPException(
                status_code=403,
                detail="Only creators can revise submissions",
            )

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
        sub.text = cleaned_text
        sub.file_name = file_name
        sub.file_mime = file_mime
        sub.file_size = len(file_bytes) if file_bytes else None
        sub.file_bytes = file_bytes
        sub.updated_at = now_iso
        await app_repo.update_submission(sub)

        actor = x_actor.strip() if x_actor and x_actor.strip() else role
        await app_repo.add_audit_event(
            id,
            AuditEvent(
                actor_role=role,
                action="revised",
                detail=f"Submission revised with content_type={content_type}",
                timestamp=now_iso,
                actor=actor,
            ),
        )

        return sub

    @app.get("/submissions/{id}/file")
    async def get_submission_file(id: str):
        sub = await app_repo.get_submission(id)
        if not sub:
            raise HTTPException(status_code=404, detail="Submission not found")

        if sub.content_type == "text" or not sub.file_bytes:
            raise HTTPException(
                status_code=404,
                detail="File not found for text submission",
            )

        media_type = sub.file_mime or "application/octet-stream"
        return Response(content=sub.file_bytes, media_type=media_type)

    @app.post(
        "/submissions/{id}/flags/{flag_id}/resolution", response_model=Flag
    )
    async def resolve_flag(
        id: str,
        flag_id: str,
        payload: ResolutionRequest,
        x_actor: Optional[str] = Header(None, alias="X-Actor"),
    ):
        sub = await app_repo.get_submission(id)
        if not sub:
            raise HTTPException(status_code=404, detail="Submission not found")

        role = payload.role or "creator"
        if role != "creator":
            raise HTTPException(
                status_code=403,
                detail="Only creators can resolve flags",
            )

        if payload.action not in {"accept", "dismiss"}:
            raise HTTPException(
                status_code=422,
                detail="Action must be 'accept' or 'dismiss'",
            )

        # Retrieve flags for current version or all versions
        flags = await app_repo.get_flags(id, version=sub.version)
        target_flag = next((f for f in flags if f.id == flag_id), None)
        if not target_flag:
            all_flags = await app_repo.get_all_flags(id)
            target_flag = next((f for f in all_flags if f.id == flag_id), None)

        if not target_flag:
            raise HTTPException(status_code=404, detail="Flag not found")

        now_iso = datetime.now(timezone.utc).isoformat()
        actor = x_actor.strip() if x_actor and x_actor.strip() else role

        if payload.action == "accept":
            # Safety check: if passage is not in current text, reject with 409
            if sub.content_type == "text":
                current_text = sub.text or ""
                if target_flag.passage not in current_text:
                    raise HTTPException(
                        status_code=409,
                        detail=(
                            f"Flag passage '{target_flag.passage}' was not found in the current text"
                        ),
                    )
                if target_flag.suggested_correction:
                    sub.text = current_text.replace(
                        target_flag.passage,
                        target_flag.suggested_correction,
                        1,
                    )
                    sub.updated_at = now_iso
                    await app_repo.update_submission(sub)

            target_flag.status = "accepted"
            if payload.comment:
                target_flag.comments.append(payload.comment)
            await app_repo.update_flag(id, target_flag)

            await app_repo.add_audit_event(
                id,
                AuditEvent(
                    actor_role=role,
                    action="flag_resolved",
                    detail=f"Flag {flag_id} resolved with action 'accept'",
                    timestamp=now_iso,
                    actor=actor,
                ),
            )
        else:
            target_flag.status = "dismissed"
            if payload.comment:
                target_flag.comments.append(payload.comment)
            await app_repo.update_flag(id, target_flag)

            await app_repo.add_audit_event(
                id,
                AuditEvent(
                    actor_role=role,
                    action="flag_resolved",
                    detail=f"Flag {flag_id} resolved with action 'dismiss'",
                    timestamp=now_iso,
                    actor=actor,
                ),
            )

        return target_flag

    @app.post(
        "/submissions/{id}/flags/{flag_id}/recheck",
        response_model=RecheckResponse,
    )
    async def recheck_flag(
        id: str,
        flag_id: str,
        payload: Optional[RecheckRequest] = None,
        x_actor: Optional[str] = Header(None, alias="X-Actor"),
    ):
        role = (payload.role if payload and payload.role else "creator")
        if role != "creator":
            raise HTTPException(
                status_code=403,
                detail="Only creators can recheck flags",
            )

        sub = await app_repo.get_submission(id)
        if not sub:
            raise HTTPException(status_code=404, detail="Submission not found")

        if sub.content_type != "text":
            raise HTTPException(
                status_code=400,
                detail="Recheck is only supported for text submissions",
            )

        flags = await app_repo.get_flags(id, version=sub.version)
        target_flag = next((f for f in flags if f.id == flag_id), None)
        if not target_flag:
            all_flags = await app_repo.get_all_flags(id)
            target_flag = next((f for f in all_flags if f.id == flag_id), None)

        if not target_flag:
            raise HTTPException(status_code=404, detail="Flag not found")

        # Apply candidate correction without saving
        candidate_text = sub.text or ""
        if target_flag.suggested_correction:
            if target_flag.passage in candidate_text:
                candidate_text = candidate_text.replace(
                    target_flag.passage, target_flag.suggested_correction, 1
                )

        candidate_payload = ContentPayload(
            content_type="text",
            text=candidate_text,
        )
        new_flags, _ = run_pipeline(
            candidate_payload, submission_id=sub.id, version=sub.version
        )

        original_flag_gone = not any(
            f.passage == target_flag.passage for f in new_flags
        )
        has_needs_human = any(f.needs_human for f in new_flags)

        now_iso = datetime.now(timezone.utc).isoformat()
        actor = x_actor.strip() if x_actor and x_actor.strip() else role
        await app_repo.add_audit_event(
            id,
            AuditEvent(
                actor_role=role,
                action="recheck",
                detail=f"Recheck executed for flag {flag_id}",
                timestamp=now_iso,
                actor=actor,
            ),
        )

        return RecheckResponse(
            new_flags=new_flags,
            original_flag_gone=original_flag_gone,
            has_needs_human=has_needs_human,
        )

    @app.get("/submissions/{id}/versions", response_model=List[VersionInfo])
    async def get_submission_versions(id: str):
        sub = await app_repo.get_submission(id)
        if not sub:
            raise HTTPException(status_code=404, detail="Submission not found")

        versions = await app_repo.get_versions(id)
        results = []
        for v in versions:
            v_flags = await app_repo.get_flags(id, version=v)
            results.append(
                VersionInfo(
                    version=v,
                    flag_count=len(v_flags),
                    needs_human_count=sum(1 for f in v_flags if f.needs_human),
                )
            )
        return results

    @app.post("/submissions/{id}/check", response_model=CheckResponse)
    async def check_submission(
        id: str,
        payload: CheckRequest,
        x_actor: Optional[str] = Header(None, alias="X-Actor"),
    ):
        sub = await app_repo.get_submission(id)
        if not sub:
            raise HTTPException(status_code=404, detail="Submission not found")

        if payload.role != "creator":
            raise HTTPException(
                status_code=403, detail="Only creators can run checks"
            )

        if sub.status != "draft":
            raise HTTPException(
                status_code=409,
                detail=f"Cannot run check on submission in state '{sub.status}'. Must be 'draft'",
            )

        now_iso = datetime.now(timezone.utc).isoformat()
        sub.status = "ai_review"
        sub.updated_at = now_iso
        await app_repo.update_submission(sub)

        actor = (
            x_actor.strip() if x_actor and x_actor.strip() else payload.role
        )
        await app_repo.add_audit_event(
            id,
            AuditEvent(
                actor_role=payload.role,
                action="check_started",
                detail="Compliance check pipeline started",
                timestamp=now_iso,
                actor=actor,
            ),
        )

        content = ContentPayload(
            content_type=sub.content_type,
            text=sub.text,
            file_name=sub.file_name,
            file_mime=sub.file_mime,
            file_bytes=sub.file_bytes,
        )

        flags, degraded_modules = run_pipeline(
            content, sub.id, version=sub.version
        )

        for dm in degraded_modules:
            await app_repo.add_audit_event(
                id,
                AuditEvent(
                    actor_role=payload.role,
                    action="module_fallback",
                    detail=f"{dm.module}: {dm.error}",
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    actor=actor,
                ),
            )

        # Store flags indexed by submission version
        await app_repo.set_flags(id, flags, version=sub.version)

        # Transition to manager_review
        completed_iso = datetime.now(timezone.utc).isoformat()
        sub.status = "manager_review"
        sub.updated_at = completed_iso
        await app_repo.update_submission(sub)

        await app_repo.add_audit_event(
            id,
            AuditEvent(
                actor_role=payload.role,
                action="check_completed",
                detail=f"Check completed with {len(flags)} flags",
                timestamp=completed_iso,
                actor=actor,
            ),
        )

        return CheckResponse(
            submission=sub, flags=flags, degraded_modules=degraded_modules
        )

    @app.get(
        "/submissions/{id}",
        response_model=SubmissionDetailResponse,
    )
    async def get_submission_detail(
        id: str, version: Optional[int] = Query(None)
    ):
        sub = await app_repo.get_submission(id)
        if not sub:
            raise HTTPException(status_code=404, detail="Submission not found")

        flags = await app_repo.get_flags(id, version=version)
        comments = await app_repo.get_comments(id)
        decisions = await app_repo.get_decisions(id)

        return SubmissionDetailResponse(
            submission=sub,
            flags=flags,
            comments=comments,
            decisions=decisions,
        )

    @app.post("/submissions/{id}/decision", response_model=Decision)
    async def record_decision(
        id: str,
        payload: DecisionRequest,
        x_actor: Optional[str] = Header(None, alias="X-Actor"),
    ):
        sub = await app_repo.get_submission(id)
        if not sub:
            raise HTTPException(status_code=404, detail="Submission not found")

        if payload.decision not in {"approve", "request_changes"}:
            raise HTTPException(
                status_code=422,
                detail="Decision must be 'approve' or 'request_changes'",
            )

        if sub.status not in {"manager_review", "final_approval"}:
            raise HTTPException(
                status_code=409,
                detail=f"Cannot record decision in state '{sub.status}'",
            )

        if sub.status == "manager_review":
            if payload.role != "manager":
                raise HTTPException(
                    status_code=403,
                    detail=f"Role '{payload.role}' is not authorized for manager_review",
                )
            if payload.decision == "approve":
                sub.status = "final_approval"
            else:
                sub.status = "draft"
                sub.version += 1

        elif sub.status == "final_approval":
            if payload.role != "authorised_reviewer":
                raise HTTPException(
                    status_code=403,
                    detail=f"Role '{payload.role}' is not authorized for final_approval",
                )
            if payload.decision == "approve":
                sub.status = "approved"
            else:
                sub.status = "draft"
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

        actor = (
            x_actor.strip() if x_actor and x_actor.strip() else payload.role
        )
        await app_repo.add_audit_event(
            id,
            AuditEvent(
                actor_role=payload.role,
                action="decision_recorded",
                detail=f"Decision '{payload.decision}' recorded. Status changed to '{sub.status}', version {sub.version}",
                timestamp=now_iso,
                actor=actor,
            ),
        )

        return decision_obj

    @app.post(
        "/submissions/{id}/comments",
        response_model=Comment,
        status_code=status.HTTP_201_CREATED,
    )
    async def add_comment(
        id: str,
        payload: CommentRequest,
        x_actor: Optional[str] = Header(None, alias="X-Actor"),
    ):
        sub = await app_repo.get_submission(id)
        if not sub:
            raise HTTPException(status_code=404, detail="Submission not found")

        if payload.role not in {"creator", "manager", "authorised_reviewer"}:
            raise HTTPException(
                status_code=403,
                detail=f"Role '{payload.role}' is not authorized to comment",
            )

        cleaned_text = payload.text.strip() if payload.text else None
        if not cleaned_text:
            raise HTTPException(
                status_code=422,
                detail="Comment text cannot be empty",
            )

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

        actor = (
            x_actor.strip() if x_actor and x_actor.strip() else payload.role
        )
        await app_repo.add_audit_event(
            id,
            AuditEvent(
                actor_role=payload.role,
                action="comment_added",
                detail=f"Comment added by {payload.role} on version {sub.version}",
                timestamp=now_iso,
                actor=actor,
            ),
        )

        return comment_obj

    @app.get("/submissions/{id}/audit", response_model=List[AuditEvent])
    async def get_audit_trail(id: str):
        sub = await app_repo.get_submission(id)
        if not sub:
            raise HTTPException(status_code=404, detail="Submission not found")

        return await app_repo.get_audit_events(id)

    @app.get("/insights/recurring", response_model=RecurringInsightsResponse)
    async def recurring_insights():
        all_flags = await app_repo.get_all_flags()
        guideline_counts: Counter[str] = Counter()
        state_counts: Counter[str] = Counter()

        for flag in all_flags:
            state_counts[flag.state] += 1
            if flag.guideline_ref:
                ref_id = f"{flag.guideline_ref.document} - {flag.guideline_ref.passage_ref}"
                guideline_counts[ref_id] += 1

        top_guidelines = [
            {"guideline": g, "count": c}
            for g, c in guideline_counts.most_common(10)
        ]

        return RecurringInsightsResponse(
            top_guidelines=top_guidelines,
            state_counts=dict(state_counts),
            total_flags=len(all_flags),
        )

    @app.get("/disclosures", response_model=DisclosuresResponse)
    async def get_disclosures():
        enabled_list = app_settings.enabled_services
        items = []
        for service_id, meta in SERVICE_DEFINITIONS.items():
            is_enabled = service_id in enabled_list
            items.append(
                DisclosureItem(
                    name=meta["name"],
                    service_id=service_id,
                    description=meta["description"],
                    enabled=is_enabled,
                )
            )

        return DisclosuresResponse(
            external_services=items,
            services_enabled=enabled_list,
            human_in_the_loop_notice=(
                "Publication is always a human decision. AI recommendations "
                "are advisory and require explicit manager and authorised "
                "reviewer approval."
            ),
        )

    @app.get("/tools/contrast", response_model=ContrastResponse)
    async def check_contrast(fg: str = Query(...), bg: str = Query(...)):
        try:
            ratio = compute_contrast_ratio(fg, bg)
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid hex color input: {exc}",
            )

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

    @app.post("/demo/seed")
    async def demo_seed():
        if not app_settings.demo_mode:
            raise HTTPException(
                status_code=403,
                detail="Demo mode is disabled. Set DEMO_MODE=true to enable seeding.",
            )

        seeded = []
        now_iso = datetime.now(timezone.utc).isoformat()

        # Seed 1: draft text submission
        sub1_id = str(uuid.uuid4())
        sub1 = Submission(
            id=sub1_id,
            content_type="text",
            role="creator",
            status="draft",
            version=1,
            text="Inkloom AI helps distributed marketing teams prevent brand violations.",
            created_at=now_iso,
            updated_at=now_iso,
        )
        await app_repo.create_submission(sub1)
        await app_repo.add_audit_event(
            sub1_id,
            AuditEvent(
                actor_role="creator",
                action="created",
                detail="Demo submission 1 created (draft)",
                timestamp=now_iso,
                actor="creator",
            ),
        )
        seeded.append(sub1)

        # Seed 2: manager_review submission with flags
        sub2_id = str(uuid.uuid4())
        sub2 = Submission(
            id=sub2_id,
            content_type="text",
            role="creator",
            status="manager_review",
            version=1,
            text="Industry-leading 99.9% uptime SLA with real-time audit logging.",
            created_at=now_iso,
            updated_at=now_iso,
        )
        await app_repo.create_submission(sub2)
        content2 = ContentPayload(content_type="text", text=sub2.text)
        flags2, _ = run_pipeline(content2, sub2_id, version=1)
        await app_repo.set_flags(sub2_id, flags2, version=1)
        await app_repo.add_audit_event(
            sub2_id,
            AuditEvent(
                actor_role="creator",
                action="created",
                detail="Demo submission 2 created",
                timestamp=now_iso,
                actor="creator",
            ),
        )
        await app_repo.add_audit_event(
            sub2_id,
            AuditEvent(
                actor_role="creator",
                action="check_completed",
                detail=f"Check completed with {len(flags2)} flags",
                timestamp=now_iso,
                actor="creator",
            ),
        )
        seeded.append(sub2)

        # Seed 3: fully approved submission
        sub3_id = str(uuid.uuid4())
        sub3 = Submission(
            id=sub3_id,
            content_type="text",
            role="creator",
            status="approved",
            version=1,
            text="Trusted compliance automation for enterprise publishing.",
            created_at=now_iso,
            updated_at=now_iso,
        )
        await app_repo.create_submission(sub3)
        content3 = ContentPayload(content_type="text", text=sub3.text)
        flags3, _ = run_pipeline(content3, sub3_id, version=1)
        await app_repo.set_flags(sub3_id, flags3, version=1)

        dec1 = Decision(
            id=str(uuid.uuid4()),
            submission_id=sub3_id,
            role="manager",
            decision="approve",
            comment="Brand voice aligned.",
            version=1,
            created_at=now_iso,
        )
        await app_repo.add_decision(dec1)

        dec2 = Decision(
            id=str(uuid.uuid4()),
            submission_id=sub3_id,
            role="authorised_reviewer",
            decision="approve",
            comment="Final legal sign-off granted.",
            version=1,
            created_at=now_iso,
        )
        await app_repo.add_decision(dec2)

        await app_repo.add_audit_event(
            sub3_id,
            AuditEvent(
                actor_role="creator",
                action="created",
                detail="Demo submission 3 created",
                timestamp=now_iso,
                actor="creator",
            ),
        )
        await app_repo.add_audit_event(
            sub3_id,
            AuditEvent(
                actor_role="manager",
                action="decision_recorded",
                detail="Manager approved",
                timestamp=now_iso,
                actor="manager",
            ),
        )
        await app_repo.add_audit_event(
            sub3_id,
            AuditEvent(
                actor_role="authorised_reviewer",
                action="decision_recorded",
                detail="Authorised reviewer approved",
                timestamp=now_iso,
                actor="authorised_reviewer",
            ),
        )
        seeded.append(sub3)

        return {
            "status": "ok",
            "message": "Demo submissions seeded successfully",
            "submissions": seeded,
        }

    return app


app = create_app()
