from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import Principal, require_api_key
from app.db.models import Tool
from app.db.session import get_db
from app.schemas.tools import ToolIn, ToolOut

router = APIRouter(prefix="/v1/tools", tags=["tools"])


@router.post("", response_model=ToolOut, status_code=status.HTTP_201_CREATED)
async def create_tool(
    body: ToolIn,
    db: AsyncSession = Depends(get_db),
    p: Principal = Depends(require_api_key),
) -> Tool:
    tool = Tool(org_id=p.org.id, **body.model_dump())
    db.add(tool)
    await db.commit()
    await db.refresh(tool)
    return tool


@router.get("", response_model=list[ToolOut])
async def list_tools(
    db: AsyncSession = Depends(get_db),
    p: Principal = Depends(require_api_key),
) -> list[Tool]:
    rows = (
        await db.execute(select(Tool).where(Tool.org_id == p.org.id).order_by(Tool.name))
    ).scalars().all()
    return list(rows)


@router.get("/{tool_id}", response_model=ToolOut)
async def get_tool(
    tool_id: str,
    db: AsyncSession = Depends(get_db),
    p: Principal = Depends(require_api_key),
) -> Tool:
    tool = (
        await db.execute(select(Tool).where(Tool.id == tool_id, Tool.org_id == p.org.id))
    ).scalar_one_or_none()
    if not tool:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "tool not found")
    return tool


@router.delete("/{tool_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tool(
    tool_id: str,
    db: AsyncSession = Depends(get_db),
    p: Principal = Depends(require_api_key),
) -> None:
    tool = (
        await db.execute(select(Tool).where(Tool.id == tool_id, Tool.org_id == p.org.id))
    ).scalar_one_or_none()
    if not tool:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "tool not found")
    await db.delete(tool)
    await db.commit()
