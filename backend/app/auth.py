"""Authentication, signed session tokens, role enforcement, and multi-organisation isolation."""

from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import re
import threading
import uuid
from typing import Dict, List, Optional

from fastapi import HTTPException
from pydantic import BaseModel

from app.config import Settings
from app.models import RoleType

TOKEN_TTL_HOURS = 24


class UserAccount(BaseModel):
    """Authenticated user session identity with role and organisation scope."""

    user_id: str
    email: str
    name: str
    role: RoleType
    org_id: str
    org_name: str
    brand_name: str


class _StoredUser(BaseModel):
    user_id: str
    email: str
    name: str
    role: RoleType
    org_id: str
    org_name: str
    brand_name: str
    password_hash: str
    demo_password_hint: Optional[str] = None


def _hash_password(password: str, salt: str = "inkloom-salt-v2") -> str:
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        100_000,
    )
    return digest.hex()


def _verify_password(password: str, password_hash: str) -> bool:
    computed = _hash_password(password)
    return hmac.compare_digest(computed, password_hash)


def _slugify_org(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return slug or f"org-{uuid.uuid4().hex[:6]}"


_USER_LOCK = threading.Lock()
_USERS_BY_EMAIL: Dict[str, _StoredUser] = {}


def _seed_default_users() -> None:
    seeds = [
        # BrightLeaf Organics
        ("u-bl-creator", "creator@brightleaf.co", "Maya Chen", "creator", "brightleaf", "BrightLeaf Organics", "BrightLeaf", "brightleaf123"),
        ("u-bl-manager", "manager@brightleaf.co", "Daniel Park", "manager", "brightleaf", "BrightLeaf Organics", "BrightLeaf", "brightleaf123"),
        ("u-bl-reviewer", "reviewer@brightleaf.co", "Priya Nair", "authorised_reviewer", "brightleaf", "BrightLeaf Organics", "BrightLeaf", "brightleaf123"),
        # Nike Demo
        ("u-nk-creator", "creator@nike.demo", "Jordan Rivera", "creator", "nike", "Nike Demo", "Nike", "nike123"),
        ("u-nk-manager", "manager@nike.demo", "Alex Morgan", "manager", "nike", "Nike Demo", "Nike", "nike123"),
        ("u-nk-reviewer", "reviewer@nike.demo", "Taylor Brooks", "authorised_reviewer", "nike", "Nike Demo", "Nike", "nike123"),
        # Inkloom Workspace
        ("u-il-creator", "creator@inkloom.ai", "Ken Rodrigues", "creator", "inkloom", "Inkloom Workspace", "Inkloom AI", "inkloom123"),
        ("u-il-manager", "manager@inkloom.ai", "Sera Rumao", "manager", "inkloom", "Inkloom Workspace", "Inkloom AI", "inkloom123"),
        ("u-il-reviewer", "reviewer@inkloom.ai", "Alisha Almeida", "authorised_reviewer", "inkloom", "Inkloom Workspace", "Inkloom AI", "inkloom123"),
    ]
    for uid, email, name, role, org_id, org_name, brand_name, pwd in seeds:
        _USERS_BY_EMAIL[email.lower()] = _StoredUser(
            user_id=uid,
            email=email.lower(),
            name=name,
            role=role,  # type: ignore[arg-type]
            org_id=org_id,
            org_name=org_name,
            brand_name=brand_name,
            password_hash=_hash_password(pwd),
            demo_password_hint=pwd,
        )


_seed_default_users()


def _to_public_user(stored: _StoredUser) -> UserAccount:
    return UserAccount(
        user_id=stored.user_id,
        email=stored.email,
        name=stored.name,
        role=stored.role,
        org_id=stored.org_id,
        org_name=stored.org_name,
        brand_name=stored.brand_name,
    )


def authenticate_user(email: str, password: str) -> Optional[UserAccount]:
    """Verify email and password against registered/seeded accounts."""
    norm_email = (email or "").strip().lower()
    if not norm_email or not password:
        return None
    with _USER_LOCK:
        stored = _USERS_BY_EMAIL.get(norm_email)
        if not stored:
            return None
        if not _verify_password(password, stored.password_hash):
            return None
        return _to_public_user(stored)


def register_user(
    email: str,
    password: str,
    name: str,
    role: RoleType,
    org_name: str,
    brand_name: Optional[str] = None,
    org_id: Optional[str] = None,
) -> UserAccount:
    """Register a new user in an organisation."""
    norm_email = (email or "").strip().lower()
    if not norm_email or "@" not in norm_email:
        raise HTTPException(status_code=422, detail="Valid email address is required.")
    if not password or len(password) < 6:
        raise HTTPException(status_code=422, detail="Password must be at least 6 characters.")
    clean_name = (name or "").strip()
    if not clean_name:
        raise HTTPException(status_code=422, detail="Display name is required.")
    clean_org = (org_name or "").strip()
    if not clean_org:
        raise HTTPException(status_code=422, detail="Organisation name is required.")
    if role not in {"creator", "manager", "authorised_reviewer"}:
        raise HTTPException(status_code=422, detail="Role must be creator, manager, or authorised_reviewer.")

    resolved_org_id = _slugify_org(org_id or clean_org)
    resolved_brand = (brand_name or clean_org).strip()

    with _USER_LOCK:
        if norm_email in _USERS_BY_EMAIL:
            raise HTTPException(status_code=409, detail="An account with this email already exists.")
        stored = _StoredUser(
            user_id=f"u-{uuid.uuid4().hex[:10]}",
            email=norm_email,
            name=clean_name,
            role=role,
            org_id=resolved_org_id,
            org_name=clean_org,
            brand_name=resolved_brand,
            password_hash=_hash_password(password),
        )
        _USERS_BY_EMAIL[norm_email] = stored
        return _to_public_user(stored)


def list_demo_accounts() -> List[dict]:
    """Return seeded demo accounts for quick role/organisation switching in the UI."""
    with _USER_LOCK:
        return [
            {
                "user_id": u.user_id,
                "email": u.email,
                "name": u.name,
                "role": u.role,
                "org_id": u.org_id,
                "org_name": u.org_name,
                "brand_name": u.brand_name,
                "demo_password": u.demo_password_hint,
            }
            for u in _USERS_BY_EMAIL.values()
            if u.demo_password_hint
        ]


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(text: str) -> bytes:
    pad = "=" * ((4 - len(text) % 4) % 4)
    return base64.urlsafe_b64decode(text + pad)


def create_access_token(user: UserAccount, secret: str) -> str:
    """Sign a stateless HMAC-SHA256 bearer token for the authenticated user."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user.user_id,
        "email": user.email,
        "name": user.name,
        "role": user.role,
        "org_id": user.org_id,
        "org_name": user.org_name,
        "brand_name": user.brand_name,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=TOKEN_TTL_HOURS)).timestamp()),
    }
    header_b64 = _b64url_encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode("utf-8"))
    payload_b64 = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
    sig = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    return f"{header_b64}.{payload_b64}.{_b64url_encode(sig)}"


def verify_access_token(token: str, secret: str) -> UserAccount:
    """Validate signature and expiration of a bearer token and return UserAccount."""
    parts = (token or "").strip().split(".")
    if len(parts) != 3:
        raise HTTPException(status_code=401, detail="Invalid authentication token format.")
    header_b64, payload_b64, sig_b64 = parts
    signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
    expected_sig = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    try:
        actual_sig = _b64url_decode(sig_b64)
        if not hmac.compare_digest(actual_sig, expected_sig):
            raise HTTPException(status_code=401, detail="Invalid authentication token signature.")
        payload = json.loads(_b64url_decode(payload_b64).decode("utf-8"))
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Malformed authentication token.") from exc

    exp = payload.get("exp")
    if not isinstance(exp, (int, float)) or datetime.now(timezone.utc).timestamp() > exp:
        raise HTTPException(status_code=401, detail="Authentication session expired. Please sign in again.")

    try:
        return UserAccount(
            user_id=str(payload["sub"]),
            email=str(payload["email"]),
            name=str(payload["name"]),
            role=payload["role"],
            org_id=str(payload["org_id"]),
            org_name=str(payload["org_name"]),
            brand_name=str(payload.get("brand_name") or payload["org_name"]),
        )
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Incomplete authentication claims.") from exc


def resolve_auth_context(
    authorization: Optional[str],
    settings: Settings,
) -> Optional[UserAccount]:
    """Resolve authenticated user from Authorization header, respecting settings.require_auth."""
    raw = (authorization or "").strip()
    if raw:
        if not raw.lower().startswith("bearer "):
            raise HTTPException(status_code=401, detail="Authorization header must use Bearer scheme.")
        token = raw[7:].strip()
        if not token:
            raise HTTPException(status_code=401, detail="Bearer token is missing.")
        return verify_access_token(token, settings.auth_secret)

    if settings.require_auth:
        raise HTTPException(
            status_code=401,
            detail="Authentication required. Sign in with your organisation account.",
        )
    return None
