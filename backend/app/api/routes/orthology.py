"""Orthology routes."""
import re

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.db.base import get_db
from app.api.deps import get_current_user
from app.models import User, OrthologyMapping

router = APIRouter()


@router.get("/stats")
async def orthology_stats(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(func.count()).select_from(OrthologyMapping))
    count = result.scalar()
    return {"total_mappings": count, "status": "loaded" if count > 0 else "not_loaded"}


@router.get("/search")
async def search_orthologues(
    human_symbol: str = None,
    mouse_symbol: str = None,
    limit: int = 50,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    query = select(OrthologyMapping)
    if human_symbol:
        query = query.where(OrthologyMapping.human_symbol.ilike(f"%{human_symbol}%"))
    if mouse_symbol:
        query = query.where(OrthologyMapping.mouse_symbol.ilike(f"%{mouse_symbol}%"))
    query = query.limit(limit)
    result = await db.execute(query)
    mappings = result.scalars().all()
    return [
        {
            "human_ensembl_id": m.human_ensembl_id,
            "mouse_ensembl_id": m.mouse_ensembl_id,
            "human_symbol": m.human_symbol,
            "mouse_symbol": m.mouse_symbol,
            "orthology_type": m.orthology_type,
            "confidence": m.confidence,
            "source_version": m.source_version,
            "ensembl_release": int(re.search(r"release\s+(\d+)", m.source_version or "", re.IGNORECASE).group(1))
            if re.search(r"release\s+(\d+)", m.source_version or "", re.IGNORECASE) else None,
        }
        for m in mappings
    ]
