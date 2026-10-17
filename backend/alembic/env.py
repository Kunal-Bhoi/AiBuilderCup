"""Async Alembic env. Uses the app engine so Cloud SQL and local DSNs both work.
Migrations run as a Cloud Run Job before traffic shifts, never on app startup (§15)."""

import asyncio

from alembic import context
from sqlalchemy.engine import Connection

from app.db.engine import dispose, get_engine
from app.db.models import Base

target_metadata = Base.metadata


def _run(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def _main() -> None:
    async with get_engine().connect() as conn:
        await conn.run_sync(_run)
        await conn.commit()
    await dispose()


asyncio.run(_main())
