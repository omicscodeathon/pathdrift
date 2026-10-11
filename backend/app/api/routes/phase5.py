from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.api.routes.phase3 import _owned_run
from app.db.base import get_db
from app.services.filesystem_runs import FILESYSTEM_RUNS_ROOT, read_result_csv, read_result_csv_page
from app.models import User

router = APIRouter()

ARTIFACTS = {
    "gene-loss": "gene_loss/gene_loss_scores.csv",
    "high-risk": "gene_loss/high_risk_genes.csv",
    "gene-loss-evidence": "gene_loss/gene_loss_evidence.csv",
    "biomarkers": "biomarkers/candidate_biomarkers.csv",
    "hub-human-cancer": "hub_genes/human_cancer_hub_metrics.csv",
    "hub-human-healthy": "hub_genes/human_healthy_hub_metrics.csv",
    "hub-mouse-cancer": "hub_genes/mouse_cancer_hub_metrics.csv",
    "hub-mouse-healthy": "hub_genes/mouse_healthy_hub_metrics.csv",
    "pathway-gene-sets": "pathways/gene_sets.csv",
    "pathway-enrichment": "pathways/enrichment_results.csv",
    "pathway-comparisons": "pathways/pathway_comparisons.csv",
    "key-drifted-pathways": "pathways/key_drifted_pathways.csv",
    "pathway-gsea": "pathways/gsea_results.csv",
    "candidate-profiles": "biomarkers/candidate_profiles.csv",
    "phenotype-samples": "morphology/phenotype_sample_metadata.csv",
    "phenotype-variables": "morphology/phenotype_variables.csv",
}
GENE_LOSS_SUMMARY = "gene_loss/summary.json"
GENE_LOSS_FIGURE = "gene_loss/gene_loss_risk_distribution.png"


async def _authorize_phase5(run_id: str, db: AsyncSession, user: User) -> None:
    await _owned_run(run_id, db, user)


def _phase5_summary(run_id: str) -> dict[str, Any]:
    run_directory = (FILESYSTEM_RUNS_ROOT / run_id).resolve()
    target = (run_directory / "phase5_summary.json").resolve()
    try:
        target.relative_to(run_directory)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Phase 5 results not found.") from exc
    if not target.is_file():
        raise HTTPException(status_code=409, detail="Phase 5 has not been run for this analysis.")
    try:
        summary = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=500, detail="Phase 5 summary could not be read.") from exc
    if not isinstance(summary, dict) or summary.get("run_id") != run_id:
        raise HTTPException(status_code=500, detail="Phase 5 summary has an invalid format.")
    return summary


@router.get("/{run_id}/phase5/summary")
async def get_phase5_summary(
    run_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _authorize_phase5(run_id, db, current_user)
    return _phase5_summary(run_id)


@router.get("/{run_id}/phase5/gene-loss/summary")
async def get_gene_loss_summary(
    run_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _authorize_phase5(run_id, db, current_user)
    _phase5_summary(run_id)
    run_directory = (FILESYSTEM_RUNS_ROOT / run_id).resolve()
    target = (run_directory / GENE_LOSS_SUMMARY).resolve()
    try:
        target.relative_to(run_directory)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Gene-loss summary not found.") from exc
    if not target.is_file():
        raise HTTPException(status_code=404, detail="Gene-loss summary not found.")
    try:
        result = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=500, detail="Gene-loss summary could not be read.") from exc
    if not isinstance(result, dict):
        raise HTTPException(status_code=500, detail="Gene-loss summary has an invalid format.")
    return result


@router.get("/{run_id}/phase5/gene-loss/figure")
async def get_gene_loss_figure(
    run_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _authorize_phase5(run_id, db, current_user)
    _phase5_summary(run_id)
    run_directory = (FILESYSTEM_RUNS_ROOT / run_id).resolve()
    target = (run_directory / GENE_LOSS_FIGURE).resolve()
    try:
        target.relative_to(run_directory)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Gene-loss figure not found.") from exc
    if not target.is_file():
        raise HTTPException(status_code=404, detail="Gene-loss figure not found.")
    return FileResponse(target, media_type="image/png", filename=target.name)


@router.get("/{run_id}/phase5/pathways/gene-sets")
async def get_pathway_gene_sets(
    run_id: str,
    species: str | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if species not in (None, "human", "mouse"):
        raise HTTPException(status_code=422, detail="Species must be human or mouse.")
    await _authorize_phase5(run_id, db, current_user)
    _phase5_summary(run_id)
    rows = read_result_csv(run_id, ARTIFACTS["pathway-gene-sets"])
    if species:
        rows = [row for row in rows if row.get("species") == species]
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        key = (str(row.get("species", "")), str(row.get("gene_set_key", "")))
        if key not in grouped:
            grouped[key] = {
                "species": key[0],
                "gene_set_key": key[1],
                "gene_set_label": row.get("gene_set_label"),
                "gene_count": 0,
            }
        grouped[key]["gene_count"] += 1
    return list(grouped.values())


@router.get("/{run_id}/phase5/{result_name}")
async def get_phase5_table(
    run_id: str,
    result_name: str,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    species: str | None = None,
    gene_set_key: str | None = None,
    database: str | None = None,
    significant_only: bool = False,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if species not in (None, "human", "mouse"):
        raise HTTPException(status_code=422, detail="Species must be human or mouse.")
    if gene_set_key is not None and len(gene_set_key) > 100:
        raise HTTPException(status_code=422, detail="Gene-set key is too long.")
    if database is not None and len(database) > 100:
        raise HTTPException(status_code=422, detail="Database name is too long.")
    await _authorize_phase5(run_id, db, current_user)
    summary = _phase5_summary(run_id)
    relative_path = ARTIFACTS.get(result_name)
    if relative_path is None:
        raise HTTPException(status_code=404, detail="Phase 5 result table not found.")
    if result_name in {"pathway-enrichment", "pathway-comparisons", "key-drifted-pathways"}:
        items, total = read_result_csv_page(
            run_id,
            relative_path,
            limit=limit,
            offset=offset,
            species=species,
            gene_set_key=gene_set_key,
            database=database,
            significant_only=significant_only,
        )
        return {
            "run_id": run_id,
            "status": summary.get("status"),
            "items": items,
            "total": total,
            "limit": limit,
            "offset": offset,
        }
    rows = read_result_csv(run_id, relative_path)
    if species:
        rows = [row for row in rows if row.get("species") == species]
    if gene_set_key:
        rows = [
            row for row in rows
            if gene_set_key in {
                row.get("gene_set_key"),
                row.get("human_gene_set_key"),
                row.get("mouse_gene_set_key"),
            }
        ]
    if database:
        rows = [row for row in rows if row.get("database") == database]
    if significant_only:
        def is_significant(row: dict[str, str | None]) -> bool:
            values = [
                row.get("adjusted_p_value"),
                row.get("human_fdr"),
                row.get("mouse_fdr"),
            ]
            for value in values:
                try:
                    if value is not None and float(value) <= 0.05:
                        return True
                except ValueError:
                    continue
            return False

        rows = [row for row in rows if is_significant(row)]
    return {
        "run_id": run_id,
        "status": summary.get("status"),
        "items": rows[offset:offset + limit],
        "total": len(rows),
        "limit": limit,
        "offset": offset,
    }
