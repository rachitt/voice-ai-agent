from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

os.environ.setdefault("VOICE_API_KEY_PEPPER", "test-pepper")
os.environ.setdefault("VOICE_WEBHOOK_HMAC_SECRET", "test-hmac")

from app.core.config import get_settings  # noqa: E402
from app.core.security import generate_api_key  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db import models  # noqa: E402  F401 — register mappers
from app.db.session import get_db  # noqa: E402
from app.main import create_app  # noqa: E402


@pytest.fixture(scope="session")
def event_loop() -> asyncio.AbstractEventLoop:
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
def base_db_url() -> str:
    return get_settings().database_url


@pytest.fixture
async def db_engine(base_db_url: str):
    # Per-test schema isolation: new DB suffixed with uuid, dropped at teardown
    suffix = uuid.uuid4().hex[:12]
    admin_url = base_db_url.rsplit("/", 1)[0] + "/voice"
    test_db = f"voice_test_{suffix}"

    admin = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    async with admin.connect() as conn:
        await conn.exec_driver_sql(f'CREATE DATABASE "{test_db}"')
    await admin.dispose()

    test_url = base_db_url.rsplit("/", 1)[0] + f"/{test_db}"
    engine = create_async_engine(test_url, pool_pre_ping=True)
    async with engine.begin() as conn:
        await conn.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS vector")
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    await engine.dispose()
    admin = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    async with admin.connect() as conn:
        await conn.exec_driver_sql(
            f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            f"WHERE datname='{test_db}' AND pid <> pg_backend_pid()"
        )
        await conn.exec_driver_sql(f'DROP DATABASE IF EXISTS "{test_db}"')
    await admin.dispose()


@pytest.fixture
async def db_session(db_engine) -> AsyncIterator[AsyncSession]:
    SessionLocal = async_sessionmaker(db_engine, expire_on_commit=False)
    async with SessionLocal() as s:
        yield s


@pytest.fixture
async def client(db_engine) -> AsyncIterator[AsyncClient]:
    SessionLocal = async_sessionmaker(db_engine, expire_on_commit=False)

    async def _override_db() -> AsyncIterator[AsyncSession]:
        async with SessionLocal() as s:
            yield s

    app = create_app()
    app.dependency_overrides[get_db] = _override_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
async def auth_headers(db_session: AsyncSession) -> dict[str, str]:
    org = models.Org(name="Test Org", slug=f"t-{uuid.uuid4().hex[:6]}")
    db_session.add(org)
    await db_session.flush()
    raw, hashed = generate_api_key("sk_test")
    db_session.add(
        models.ApiKey(org_id=org.id, name="test", prefix=raw[:10], key_hash=hashed)
    )
    await db_session.commit()
    return {"Authorization": f"Bearer {raw}"}
