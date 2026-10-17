"""Create an organisation and attach a Firebase user to it with a role.
Sets the org_id/role custom claims the API trusts (never a request body value).

    uv run python scripts/seed_org.py --org org_harbourline --name "Harbourline Trading" \
        --email broker@example.com --role APPROVER
The user must already exist in Firebase Auth (they signed in once). They must sign in again
(or refresh their ID token) for new claims to apply.
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy.dialects.postgresql import insert  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.db.engine import dispose, sessionmaker  # noqa: E402
from app.db.models import Membership, Organisation, User  # noqa: E402


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--org", required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--email", required=True)
    ap.add_argument("--role", choices=["OWNER", "APPROVER", "VIEWER"], default="APPROVER")
    a = ap.parse_args()

    import firebase_admin
    from firebase_admin import auth

    s = get_settings()
    firebase_admin.initialize_app(options={"projectId": s.firebase_project or s.gcp_project})
    user = auth.get_user_by_email(a.email)
    auth.set_custom_user_claims(user.uid, {"org_id": a.org, "role": a.role})

    async with sessionmaker()() as session:
        await session.execute(insert(Organisation).values(id=a.org, name=a.name).on_conflict_do_nothing())
        await session.execute(insert(User).values(id=user.uid, email=a.email.lower()).on_conflict_do_nothing())
        await session.execute(insert(Membership).values(org_id=a.org, user_id=user.uid, role=a.role)
                              .on_conflict_do_update(index_elements=["org_id", "user_id"], set_={"role": a.role}))
        await session.commit()
    await dispose()
    print(f"{a.email} ({user.uid}) is {a.role} in {a.org}")


asyncio.run(main())
