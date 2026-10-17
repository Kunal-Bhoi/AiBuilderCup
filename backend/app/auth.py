"""Authentication and authorisation (§13.1).

firebase mode: verify the Firebase ID token on every request. org_id and role come from
custom claims set server-side (scripts/seed_org.py); never from the request body.
dev mode: a fixed principal so the frontend and tests work before Firebase is wired.
X-Dev-User / X-Dev-Role / X-Dev-Org override it, which lets tests exercise role gates."""

import asyncio
from dataclasses import dataclass

from fastapi import Depends, Request
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.engine import get_session
from app.db.models import Membership, Organisation, User
from app.domain.enums import Role
from app.errors import AppError, ErrorCode

DEV_ORG = "org_dev"
DEV_USER = "user_dev"


@dataclass(frozen=True)
class Principal:
    user_id: str
    org_id: str
    role: Role
    email: str

    @property
    def can_decide(self) -> bool:
        return self.role in (Role.APPROVER, Role.OWNER)


_firebase_app = None
_known: set[tuple[str, str, str]] = set()


def _verify_firebase(token: str) -> dict:
    global _firebase_app
    import firebase_admin
    from firebase_admin import auth as fb_auth

    if _firebase_app is None:
        s = get_settings()
        opts = {"projectId": s.firebase_project or s.gcp_project} if (s.firebase_project or s.gcp_project) else None
        _firebase_app = firebase_admin.initialize_app(options=opts)
    # Public keys are cached by firebase_admin and refreshed on rotation.
    return fb_auth.verify_id_token(token, app=_firebase_app)


async def _ensure_identity(session: AsyncSession, p: Principal) -> None:
    """Upsert the user (and in dev mode the org + membership) once per process."""
    key = (p.user_id, p.org_id, p.role.value)
    if key in _known:
        return
    await session.execute(
        insert(User).values(id=p.user_id, email=p.email.lower()).on_conflict_do_nothing(index_elements=["id"])
    )
    if get_settings().auth_mode == "dev":
        await session.execute(
            insert(Organisation).values(id=p.org_id, name="Development organisation").on_conflict_do_nothing()
        )
        await session.execute(
            insert(Membership)
            .values(org_id=p.org_id, user_id=p.user_id, role=p.role.value)
            .on_conflict_do_update(index_elements=["org_id", "user_id"], set_={"role": p.role.value})
        )
    await session.commit()
    _known.add(key)


async def get_principal(request: Request, session: AsyncSession = Depends(get_session)) -> Principal:
    s = get_settings()
    if s.auth_mode == "dev":
        role_header = request.headers.get("X-Dev-Role", Role.APPROVER.value).upper()
        try:
            role = Role(role_header)
        except ValueError:
            raise AppError(ErrorCode.VALIDATION_FAILED, "X-Dev-Role must be OWNER, APPROVER or VIEWER.")
        user_id = request.headers.get("X-Dev-User", DEV_USER)
        p = Principal(
            user_id=user_id,
            org_id=request.headers.get("X-Dev-Org", DEV_ORG),
            role=role,
            email=f"{user_id}@dev.local",
        )
        await _ensure_identity(session, p)
        return p

    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        raise AppError(ErrorCode.UNAUTHENTICATED, "A Firebase ID token is required.")
    try:
        claims = await asyncio.to_thread(_verify_firebase, header.removeprefix("Bearer ").strip())
    except Exception:
        raise AppError(ErrorCode.UNAUTHENTICATED, "The ID token is invalid or expired.")

    org_id, role = claims.get("org_id"), claims.get("role")
    if not org_id or role not in {r.value for r in Role}:
        raise AppError(ErrorCode.FORBIDDEN_ORG_MISMATCH, "This account is not a member of any organisation.")
    p = Principal(user_id=claims["uid"], org_id=org_id, role=Role(role), email=claims.get("email") or f"{claims['uid']}@unknown")
    await _ensure_identity(session, p)
    return p


def require_approver(p: Principal = Depends(get_principal)) -> Principal:
    if not p.can_decide:
        raise AppError(ErrorCode.FORBIDDEN_ORG_MISMATCH, "Your role does not permit recording decisions or issuing reports.")
    return p
