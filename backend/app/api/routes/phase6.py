from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Literal

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.api.routes.phase3 import _owned_run
from app.db.base import get_db
from app.models import User
from app.services.filesystem_runs import FILESYSTEM_RUNS_ROOT

router = APIRouter()
_PUBLIC_ARTIFACTS = {
    "out_of_fold_predictions.csv",
    "feature_importance.csv",
    "feature_evidence.csv",
    "predictive_biomarkers.csv",
    "cross_species_predictors.csv",
    "roc_curves.svg",
    "precision_recall_curves.svg",
    "calibration_curves.svg",
}


def _csv_page(path: Path, limit: int, offset: int, model: str | None = None) -> dict[str, Any]:
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Phase 6 results are not available.")
    frame = pd.read_csv(path)
    if model and "model" in frame.columns:
        frame = frame.loc[frame["model"] == model]
    total = len(frame)
    items = frame.iloc[offset:offset + limit].astype(object)
    items = items.where(pd.notna(items), None)
    return {
        "total": int(total),
        "limit": limit,
        "offset": offset,
        "items": items.to_dict("records"),
    }


def _run_directory(run_id: str) -> Path:
    if not re.fullmatch(r"[0-9a-fA-F-]{36}", run_id):
        raise HTTPException(status_code=404, detail="Phase 6 results not found.")
    root = FILESYSTEM_RUNS_ROOT.resolve()
    directory = (root / run_id).resolve()
    try:
        directory.relative_to(root)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Phase 6 results not found.") from exc
    return directory


async def _authorize(run_id: str, db: AsyncSession, user: User) -> Path:
    await _owned_run(run_id, db, user)
    return _run_directory(run_id)


def _phase6_directory(directory: Path, species: Literal["human", "mouse"]) -> Path:
    return directory / "ml" if species == "human" else directory / "ml" / "mouse"


@router.get("/{run_id}/phase6")
async def get_phase6_summary(
    run_id: str,
    species: Literal["human", "mouse"] = Query(default="human"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    directory = await _authorize(run_id, db, current_user)
    path = _phase6_directory(directory, species) / "phase6_summary.json"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Phase 6 results are not available.")
    result = json.loads(path.read_text(encoding="utf-8"))
    if result.get("run_id") != run_id:
        raise HTTPException(status_code=404, detail="Phase 6 results are not available.")
    return result


@router.get("/{run_id}/phase6/predictions")
async def get_phase6_predictions(
    run_id: str,
    species: Literal["human", "mouse"] = Query(default="human"),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    directory = await _authorize(run_id, db, current_user)
    path = _phase6_directory(directory, species) / "out_of_fold_predictions.csv"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Phase 6 predictions are not available.")
    return _csv_page(path, limit, offset)


@router.get("/{run_id}/phase6/biomarkers")
async def get_phase6_biomarkers(
    run_id: str,
    species: Literal["human", "mouse"] = Query(default="human"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    directory = await _authorize(run_id, db, current_user)
    return _csv_page(
        _phase6_directory(directory, species) / "predictive_biomarkers.csv",
        limit,
        offset,
    )


@router.get("/{run_id}/phase6/feature-importance")
async def get_phase6_feature_importance(
    run_id: str,
    species: Literal["human", "mouse"] = Query(default="human"),
    model: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    directory = await _authorize(run_id, db, current_user)
    return _csv_page(
        _phase6_directory(directory, species) / "feature_importance.csv",
        limit,
        offset,
        model,
    )


@router.get("/{run_id}/phase6/validation")
async def get_phase6_validation(
    run_id: str,
    species: Literal["human", "mouse"] = Query(default="human"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    directory = await _authorize(run_id, db, current_user)
    path = (
        directory / "validation" / "phase6_validation.json"
        if species == "human"
        else _phase6_directory(directory, species) / "phase6_validation.json"
    )
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Phase 6 validation results are not available.")
    result: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    if result.get("run_id") != run_id:
        raise HTTPException(status_code=404, detail="Phase 6 validation results are not available.")
    return result


@router.get("/{run_id}/phase6/artifacts/{artifact_name}")
async def get_phase6_artifact(
    run_id: str,
    artifact_name: str,
    species: Literal["human", "mouse"] = Query(default="human"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    directory = await _authorize(run_id, db, current_user)
    if artifact_name not in _PUBLIC_ARTIFACTS:
        raise HTTPException(status_code=404, detail="Phase 6 artifact not found.")
    ml_directory = _phase6_directory(directory, species)
    path = (ml_directory / artifact_name).resolve()
    try:
        path.relative_to(ml_directory.resolve())
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Phase 6 artifact not found.") from exc
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Phase 6 artifact not found.")
    return FileResponse(path, filename=artifact_name)
