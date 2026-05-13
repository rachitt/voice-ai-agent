from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthedPrincipal, require_principal
from app.db.models import Tool
from app.db.session import get_db
from app.schemas.tools import ToolIn, ToolOut, ToolUpdate

router = APIRouter(prefix="/v1/tools", tags=["tools"])


@router.post("", response_model=ToolOut, status_code=status.HTTP_201_CREATED)
async def create_tool(
    body: ToolIn,
    db: AsyncSession = Depends(get_db),
    p: AuthedPrincipal = Depends(require_principal),
) -> Tool:
    tool = Tool(org_id=p.org.id, **body.model_dump())
    db.add(tool)
    await db.commit()
    await db.refresh(tool)
    return tool


@router.get("", response_model=list[ToolOut])
async def list_tools(
    db: AsyncSession = Depends(get_db),
    p: AuthedPrincipal = Depends(require_principal),
) -> list[Tool]:
    rows = (
        (await db.execute(select(Tool).where(Tool.org_id == p.org.id).order_by(Tool.name)))
        .scalars()
        .all()
    )
    return list(rows)


@router.get("/{tool_id}", response_model=ToolOut)
async def get_tool(
    tool_id: str,
    db: AsyncSession = Depends(get_db),
    p: AuthedPrincipal = Depends(require_principal),
) -> Tool:
    tool = (
        await db.execute(select(Tool).where(Tool.id == tool_id, Tool.org_id == p.org.id))
    ).scalar_one_or_none()
    if not tool:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "tool not found")
    return tool


@router.patch("/{tool_id}", response_model=ToolOut)
async def update_tool(
    tool_id: str,
    body: ToolUpdate,
    db: AsyncSession = Depends(get_db),
    p: AuthedPrincipal = Depends(require_principal),
) -> Tool:
    tool = (
        await db.execute(select(Tool).where(Tool.id == tool_id, Tool.org_id == p.org.id))
    ).scalar_one_or_none()
    if not tool:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "tool not found")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(tool, field, value)
    await db.commit()
    await db.refresh(tool)
    return tool


@router.delete("/{tool_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tool(
    tool_id: str,
    db: AsyncSession = Depends(get_db),
    p: AuthedPrincipal = Depends(require_principal),
) -> None:
    tool = (
        await db.execute(select(Tool).where(Tool.id == tool_id, Tool.org_id == p.org.id))
    ).scalar_one_or_none()
    if not tool:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "tool not found")
    await db.delete(tool)
    await db.commit()
