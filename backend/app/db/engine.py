"""Async engine. Locally a plain DSN; on Cloud Run the Cloud SQL Python Connector
(no public IP allow-listing, TLS handled by the connector)."""

from collections.abc import AsyncIterator
from typing import Any

import asyncpg
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None
_connector: Any = None


async def _cloud_sql_connect() -> asyncpg.Connection:
    global _connector
    from google.cloud.sql.connector import create_async_connector

    s = get_settings()
    if _connector is None:
        _connector = await create_async_connector()
    return await _connector.connect_async(
        s.cloud_sql_instance, "asyncpg", user=s.db_user, password=s.db_password, db=s.db_name
    )


def get_engine() -> AsyncEngine:
    global _engine, _sessionmaker
    if _engine is None:
        s = get_settings()
        if s.cloud_sql_instance:
            _engine = create_async_engine(
                "postgresql+asyncpg://", async_creator=_cloud_sql_connect, pool_size=5, max_overflow=5,
                pool_pre_ping=True,
            )
        else:
            _engine = create_async_engine(s.database_url, pool_size=5, max_overflow=5, pool_pre_ping=True)
        _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


def sessionmaker() -> async_sessionmaker[AsyncSession]:
    get_engine()
    assert _sessionmaker is not None
    return _sessionmaker


async def get_session() -> AsyncIterator[AsyncSession]:
    async with sessionmaker()() as session:
        yield session


async def raw_connection() -> asyncpg.Connection:
    """A dedicated asyncpg connection, used for LISTEN (SSE fan-out)."""
    s = get_settings()
    if s.cloud_sql_instance:
        return await _cloud_sql_connect()
    dsn = s.database_url.replace("postgresql+asyncpg://", "postgresql://")
    return await asyncpg.connect(dsn)


async def dispose() -> None:
    global _engine, _sessionmaker, _connector
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _sessionmaker = None
    if _connector is not None:
        await _connector.close_async()
        _connector = None
