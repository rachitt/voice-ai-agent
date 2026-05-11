from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import Principal, require_api_key
from app.db.models import PhoneNumber
from app.db.session import get_db
from app.schemas.phone_numbers import PhoneNumberCreate, PhoneNumberOut, PhoneNumberUpdate

router = APIRouter(prefix="/v1/phone-numbers", tags=["phone-numbers"])


@router.post("", response_model=PhoneNumberOut, status_code=status.HTTP_201_CREATED)
async def create_phone_number(
    body: PhoneNumberCreate,
    db: AsyncSession = Depends(get_db),
    p: Principal = Depends(require_api_key),
) -> PhoneNumber:
    pn = PhoneNumber(org_id=p.org.id, **body.model_dump())
    db.add(pn)
    await db.commit()
    await db.refresh(pn)
    return pn


@router.get("", response_model=list[PhoneNumberOut])
async def list_phone_numbers(
    db: AsyncSession = Depends(get_db),
    p: Principal = Depends(require_api_key),
) -> list[PhoneNumber]:
    rows = (
        await db.execute(
            select(PhoneNumber).where(PhoneNumber.org_id == p.org.id).order_by(PhoneNumber.e164)
        )
    ).scalars().all()
    return list(rows)


@router.patch("/{pn_id}", response_model=PhoneNumberOut)
async def update_phone_number(
    pn_id: str,
    body: PhoneNumberUpdate,
    db: AsyncSession = Depends(get_db),
    p: Principal = Depends(require_api_key),
) -> PhoneNumber:
    pn = (
        await db.execute(
            select(PhoneNumber).where(PhoneNumber.id == pn_id, PhoneNumber.org_id == p.org.id)
        )
    ).scalar_one_or_none()
    if not pn:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "phone number not found")
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(pn, field, value)
    await db.commit()
    await db.refresh(pn)
    return pn
