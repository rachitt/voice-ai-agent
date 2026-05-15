"""API key CRUD for OAuth-authenticated dashboard users.

Session-cookie auth only. Long-lived API keys MUST NOT be able to mint
or revoke other API keys — that would let a compromised key
persist itself indefinitely.

Flow:
  POST   /v1/api-keys         → mint key (raw shown ONCE in response)
  GET    /v1/api-keys         → list (no raw, just metadata)
  DELETE /v1/api-keys/{id}    → soft-revoke (sets revoked_at)
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import SessionPrincipal, require_session
from app.core.security import generate_api_key
from app.db.models import ApiKey
from app.db.session import get_db
from app.schemas.api_keys import ApiKeyCreate, ApiKeyCreated, ApiKeyOut

router = APIRouter(prefix="/v1/api-keys", tags=["api-keys"])


@router.post("", response_model=ApiKeyCreated, status_code=status.HTTP_201_CREATED)
async def create_api_key(
    body: ApiKeyCreate,
    db: AsyncSession = Depends(get_db),
    p: SessionPrincipal = Depends(require_session),
) -> ApiKeyCreated:
    raw, hashed = generate_api_key("sk_live")
    key = ApiKey(
        org_id=p.org.id,
        name=body.name,
        prefix=raw[:10],
        key_hash=hashed,
    )
    db.add(key)
    await db.commit()
    await db.refresh(key)
    return ApiKeyCreated.model_validate({**ApiKeyOut.model_validate(key).model_dump(), "key": raw})


@router.get("", response_model=list[ApiKeyOut])
async def list_api_keys(
    db: AsyncSession = Depends(get_db),
    p: SessionPrincipal = Depends(require_session),
) -> list[ApiKey]:
    rows = (
        (
            await db.execute(
                select(ApiKey).where(ApiKey.org_id == p.org.id).order_by(ApiKey.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return list(rows)


@router.delete("/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_api_key(
    key_id: str,
    db: AsyncSession = Depends(get_db),
    p: SessionPrincipal = Depends(require_session),
) -> None:
    key = (
        await db.execute(select(ApiKey).where(ApiKey.id == key_id, ApiKey.org_id == p.org.id))
    ).scalar_one_or_none()
    if not key:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "api key not found")
    if key.revoked_at is None:
        key.revoked_at = datetime.now(UTC)
        await db.commit()
