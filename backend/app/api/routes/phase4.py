from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.api.routes.phase3 import _owned_run
from app.db.base import get_db
from app.services.filesystem_runs import FILESYSTEM_RUNS_ROOT, read_result_csv
from app.models import (
    RunCrossSpeciesNodeAlignment,
    RunGeneDrift,
    RunModuleDrift,
    RunNetworkEdgeDrift,
    RunOrthologyMapping,
    RunPhase4Summary,
    User,
)

router = APIRouter()


async def _phase4_summary(run_id: str, db: AsyncSession) -> RunPhase4Summary:
    result = await db.execute(
        select(RunPhase4Summary).where(RunPhase4Summary.run_id == run_id)
    )
    summary = result.scalar_one_or_none()
    if summary is None:
        raise HTTPException(status_code=404, detail="Phase 4 results are not available for this run.")
    return summary


async def _authorize(
    run_id: str,
    db: AsyncSession,
    user: User,
    required_status: set[str],
) -> RunPhase4Summary | dict[str, Any]:
    run = await _owned_run(run_id, db, user)
    if isinstance(run, dict):
        phase3 = run.get("phase3")
        if not isinstance(phase3, dict) or str(phase3.get("status", "")).upper() != "COMPLETED":
            raise HTTPException(status_code=409, detail="Analysis run is not complete.")
        return run
    summary = await _phase4_summary(run_id, db)
    if summary.status not in required_status:
        raise HTTPException(
            status_code=409,
            detail=f"Phase 4 results are not complete for this endpoint (status: {summary.status}).",
        )
    return summary


def _filesystem_json(run_id: str, relative_path: str) -> dict[str, Any]:
    run_directory = (FILESYSTEM_RUNS_ROOT / run_id).resolve()
    target = (run_directory / relative_path).resolve()
    try:
        target.relative_to(run_directory)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Saved result artifact not found.") from exc
    if not target.is_file():
        raise HTTPException(status_code=404, detail="Saved result artifact not found.")
    try:
        result = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=500, detail="Saved result artifact could not be read.") from exc
    if not isinstance(result, dict):
        raise HTTPException(status_code=500, detail="Saved result artifact has an invalid format.")
    return result


def _filesystem_csv_page(
    run_id: str,
    relative_path: str,
    limit: int,
    offset: int,
    *,
    status: str | None = None,
) -> dict[str, Any]:
    rows = read_result_csv(run_id, relative_path)
    if status:
        rows = [row for row in rows if str(row.get("status") or "").upper() == status]
    return {
        "items": rows[offset:offset + limit],
        "total": len(rows),
        "limit": limit,
        "offset": offset,
    }


def _csv_bool(value: Any) -> bool | None:
    if value is None or not str(value).strip():
        return None
    normalized = str(value).strip().lower()
    if normalized in {"true", "1", "yes"}:
        return True
    if normalized in {"false", "0", "no"}:
        return False
    return None


def _csv_float(value: Any) -> float | None:
    if value is None or not str(value).strip():
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _phase4_edge_row(row: dict[str, str | None]) -> dict[str, Any]:
    source = row.get("human_source_gene")
    target = row.get("human_target_gene")
    mouse_source = row.get("mouse_source_gene")
    mouse_target = row.get("mouse_target_gene")
    return {
        **row,
        "id": f"{source or ''}:{target or ''}:{mouse_source or ''}:{mouse_target or ''}",
        "status": (row.get("status") or row.get("edge_classification") or "").upper(),
        "human_source_gene_id": source,
        "human_target_gene_id": target,
        "mouse_source_gene_id": mouse_source,
        "mouse_target_gene_id": mouse_target,
        "human_weight": _csv_float(row.get("human_weight")),
        "mouse_weight": _csv_float(row.get("mouse_weight")),
        "weight_difference": _csv_float(row.get("weight_difference")),
    }


def _serialize(row: Any) -> dict:
    result = {}
    for column in row.__table__.columns:
        value = getattr(row, column.name)
        result[column.name] = value.isoformat() if hasattr(value, "isoformat") else value
    return result


async def _page(
    model: Any,
    run_id: str,
    db: AsyncSession,
    limit: int,
    offset: int,
    ordering: Any,
) -> dict:
    total = await db.scalar(
        select(func.count()).select_from(model).where(model.run_id == run_id)
    )
    result = await db.execute(
        select(model)
        .where(model.run_id == run_id)
        .order_by(ordering)
        .limit(limit)
        .offset(offset)
    )
    return {
        "items": [_serialize(row) for row in result.scalars().all()],
        "total": int(total or 0),
        "limit": limit,
        "offset": offset,
    }


@router.get("/{run_id}/orthology")
async def get_run_orthology(
    run_id: str,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    run = await _authorize(run_id, db, current_user, {"ORTHOLOGY_COMPLETE", "CROSS_SPECIES_COMPLETE", "COMPLETED"})
    if isinstance(run, dict):
        rows = read_result_csv(run_id, "orthology/orthologs.csv")
        items = []
        for row in rows[offset:offset + limit]:
            items.append({
                **row,
                "confidence": _csv_float(row.get("confidence")),
                "is_primary": None,
            })
        return {"items": items, "total": len(rows), "limit": limit, "offset": offset}
    return await _page(
        RunOrthologyMapping, run_id, db, limit, offset,
        RunOrthologyMapping.human_ensembl_id,
    )


@router.get("/{run_id}/orthology/summary")
async def get_run_orthology_summary(
    run_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    summary = await _authorize(
        run_id, db, current_user, {"ORTHOLOGY_COMPLETE", "CROSS_SPECIES_COMPLETE", "COMPLETED"}
    )
    if isinstance(summary, dict):
        return _filesystem_json(run_id, "orthology/orthology_summary.json")
    return summary.summary.get("orthology", {})


@router.get("/{run_id}/cross-species/nodes")
async def get_run_cross_species_nodes(
    run_id: str,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    run = await _authorize(run_id, db, current_user, {"CROSS_SPECIES_COMPLETE", "COMPLETED"})
    if isinstance(run, dict):
        rows = _filesystem_csv_page(run_id, "cross_species/node_alignment.csv", limit, offset)
        for row in rows["items"]:
            row["confidence"] = _csv_float(row.get("confidence"))
            row["human_network_present"] = _csv_bool(row.get("human_network_present"))
            row["mouse_network_present"] = _csv_bool(row.get("mouse_network_present"))
            row["is_primary"] = _csv_bool(row.get("is_primary"))
        return rows
    return await _page(
        RunCrossSpeciesNodeAlignment, run_id, db, limit, offset,
        RunCrossSpeciesNodeAlignment.human_ensembl_id,
    )


@router.get("/{run_id}/cross-species/edges")
async def get_run_cross_species_edges(
    run_id: str,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    status: str | None = Query(None, pattern="^(CONSERVED|LOST|GAINED|REWIRED|UNMAPPABLE)$"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    run = await _authorize(run_id, db, current_user, {"CROSS_SPECIES_COMPLETE", "COMPLETED"})
    if isinstance(run, dict):
        rows = _filesystem_csv_page(run_id, "cross_species/edge_alignment.csv", limit, offset, status=status)
        rows["items"] = [_phase4_edge_row(row) for row in rows["items"]]
        return rows
    query = select(RunNetworkEdgeDrift).where(RunNetworkEdgeDrift.run_id == run_id)
    count_query = select(func.count()).select_from(RunNetworkEdgeDrift).where(RunNetworkEdgeDrift.run_id == run_id)
    if status:
        query = query.where(RunNetworkEdgeDrift.status == status)
        count_query = count_query.where(RunNetworkEdgeDrift.status == status)
    total = await db.scalar(count_query)
    result = await db.execute(
        query.order_by(RunNetworkEdgeDrift.status, RunNetworkEdgeDrift.id)
        .limit(limit)
        .offset(offset)
    )
    return {
        "items": [_serialize(row) for row in result.scalars().all()],
        "total": int(total or 0),
        "limit": limit,
        "offset": offset,
    }


@router.get("/{run_id}/cross-species/summary")
async def get_run_cross_species_summary(
    run_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    summary = await _authorize(run_id, db, current_user, {"CROSS_SPECIES_COMPLETE", "COMPLETED"})
    if isinstance(summary, dict):
        result = _filesystem_json(run_id, "cross_species/network_conservation_summary.json")
        drift = _filesystem_json(run_id, "drift/drift_summary.json")
        result["aligned_gene_count"] = drift.get("aligned_gene_count")
        result["mean_gene_drift_score"] = drift.get("mean_gene_drift_score")
        result["edge_status_counts"] = drift.get("edge_status_counts", {})
        return result
    return summary.summary.get("cross_species", {})


@router.get("/{run_id}/drift")
async def get_run_drift(
    run_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    summary = await _authorize(run_id, db, current_user, {"COMPLETED"})
    if isinstance(summary, dict):
        return {
            "cross_species": _filesystem_json(run_id, "cross_species/network_conservation_summary.json"),
            "drift": _filesystem_json(run_id, "drift/drift_summary.json"),
        }
    return summary.summary


@router.get("/{run_id}/drift/genes")
async def get_run_drift_genes(
    run_id: str,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    run = await _authorize(run_id, db, current_user, {"COMPLETED"})
    if isinstance(run, dict):
        rows = _filesystem_csv_page(run_id, "drift/gene_drift.csv", limit, offset)
        for row in rows["items"]:
            row["id"] = f"{row.get('human_ensembl_id') or ''}:{row.get('mouse_ensembl_id') or ''}"
        return rows
    return await _page(
        RunGeneDrift, run_id, db, limit, offset,
        RunGeneDrift.drift_score.desc(),
    )


@router.get("/{run_id}/drift/edges")
async def get_run_drift_edges(
    run_id: str,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    status: str | None = Query(None, pattern="^(CONSERVED|LOST|GAINED|REWIRED|UNMAPPABLE)$"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    run = await _authorize(run_id, db, current_user, {"COMPLETED"})
    if isinstance(run, dict):
        rows = _filesystem_csv_page(run_id, "drift/edge_drift.csv", limit, offset, status=status)
        rows["items"] = [_phase4_edge_row(row) for row in rows["items"]]
        return rows
    return await get_run_cross_species_edges(
        run_id, limit, offset, status, current_user, db
    )


@router.get("/{run_id}/drift/modules")
async def get_run_drift_modules(
    run_id: str,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    run = await _authorize(run_id, db, current_user, {"COMPLETED"})
    if isinstance(run, dict):
        rows = _filesystem_csv_page(run_id, "drift/module_drift.csv", limit, offset)
        for row in rows["items"]:
            row["id"] = f"{row.get('human_module_id') or ''}:{row.get('candidate_mouse_module_id') or ''}"
            row["module_conservation"] = _csv_float(row.get("module_conservation_score"))
        return rows
    return await _page(
        RunModuleDrift, run_id, db, limit, offset,
        RunModuleDrift.human_module_id,
    )


@router.get("/{run_id}/drift/summary")
async def get_run_drift_summary(
    run_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    summary = await _authorize(run_id, db, current_user, {"COMPLETED"})
    if isinstance(summary, dict):
        return _filesystem_json(run_id, "drift/drift_summary.json")
    return summary.summary.get("drift", {})
