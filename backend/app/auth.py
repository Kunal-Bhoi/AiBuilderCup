"""Who is acting, and what they may do.

No login: the app is directly usable. Every request acts as a default workspace user with the
APPROVER role. X-Dev-User / X-Dev-Org / X-Dev-Role override that, which is how the UI's role
switch and the tests exercise the role gates (a VIEWER cannot record decisions or issue reports).
The actor recorded on a decision is always this principal, never a value from the request body."""

from dataclasses import dataclass

from fastapi import Depends, Request
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

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


_known: set[tuple[str, str, str]] = set()


async def _ensure_identity(session: AsyncSession, p: Principal) -> None:
    """Upsert the user, org and membership once per process."""
    key = (p.user_id, p.org_id, p.role.value)
    if key in _known:
        return
    await session.execute(
        insert(User).values(id=p.user_id, email=p.email.lower()).on_conflict_do_nothing(index_elements=["id"])
    )
    await session.execute(
        insert(Organisation).values(id=p.org_id, name="Workspace").on_conflict_do_nothing()
    )
    await session.execute(
        insert(Membership)
        .values(org_id=p.org_id, user_id=p.user_id, role=p.role.value)
        .on_conflict_do_update(index_elements=["org_id", "user_id"], set_={"role": p.role.value})
    )
    await session.commit()
    _known.add(key)


async def get_principal(request: Request, session: AsyncSession = Depends(get_session)) -> Principal:
    role_header = request.headers.get("X-Dev-Role", Role.APPROVER.value).upper()
    try:
        role = Role(role_header)
    except ValueError:
        raise AppError(ErrorCode.VALIDATION_FAILED, "X-Dev-Role must be OWNER, APPROVER or VIEWER.")
    user_id = request.headers.get("X-Dev-User", DEV_USER)
    p = Principal(user_id=user_id, org_id=request.headers.get("X-Dev-Org", DEV_ORG), role=role,
                  email=f"{user_id}@workspace.local")
    await _ensure_identity(session, p)
    return p


def require_approver(p: Principal = Depends(get_principal)) -> Principal:
    if not p.can_decide:
        raise AppError(ErrorCode.FORBIDDEN_ORG_MISMATCH, "Your role does not permit recording decisions or issuing reports.")
    return p
