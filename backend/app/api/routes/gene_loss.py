from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, Field
import pandas as pd

from app.bio.gene_loss import GeneLossRiskModel, build_ppi_network, decode_image_from_data_url, summarize_image
from app.api.deps import get_current_user
from app.db.base import get_db
from app.models import Analysis, Dataset, GeneNetwork, Project, User

router = APIRouter()


class GeneLossRequest(BaseModel):
    analysis_id: Optional[str] = None
    dataset_id: Optional[str] = None
    network_id: Optional[str] = None
    genes: List[str] = Field(default_factory=list)
    expression: Dict[str, float] = Field(default_factory=dict)
    interactions: List[List[str]] = Field(default_factory=list)
    image_data_url: Optional[str] = None


class GeneLossResponse(BaseModel):
    image_summary: Dict[str, Any]
    network: Dict[str, List[Dict[str, Any]]]
    gene_scores: Dict[str, Dict[str, Any]]
    highest_risk_genes: List[Dict[str, Any]]


@router.post("/analyze", response_model=GeneLossResponse)
async def analyze_gene_loss(
    payload: GeneLossRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    expression = dict(payload.expression)
    genes = list(payload.genes)
    interactions = list(payload.interactions)

    analysis = None
    if payload.analysis_id:
        analysis_result = await db.execute(
            select(Analysis)
            .join(Project, Analysis.project_id == Project.id)
            .where(Analysis.id == payload.analysis_id, Project.owner_id == current_user.id)
        )
        analysis = analysis_result.scalar_one_or_none()
        if not analysis:
            raise HTTPException(status_code=404, detail="Analysis not found")

    if payload.dataset_id:
        dataset_result = await db.execute(
            select(Dataset).where(Dataset.id == payload.dataset_id, Dataset.owner_id == current_user.id)
        )
        dataset = dataset_result.scalar_one_or_none()
        if not dataset:
            raise HTTPException(status_code=404, detail="Dataset not found")
        if analysis and dataset.project_id != analysis.project_id:
            raise HTTPException(status_code=400, detail="Dataset does not belong to the selected analysis project")
        if not dataset.expression_file_path:
            raise HTTPException(status_code=400, detail="Dataset has no expression file")
        try:
            expression_df = pd.read_csv(dataset.expression_file_path, index_col=0)
            expression = expression_df.apply(pd.to_numeric, errors="coerce").mean(axis=1).dropna().to_dict()
            genes = genes or [str(gene) for gene in expression_df.index[:500]]
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Unable to read dataset expression file: {exc}") from exc

    if payload.network_id:
        network_result = await db.execute(
            select(GeneNetwork)
            .join(Dataset, GeneNetwork.dataset_id == Dataset.id)
            .where(GeneNetwork.id == payload.network_id, Dataset.owner_id == current_user.id)
        )
        network = network_result.scalar_one_or_none()
        if not network:
            raise HTTPException(status_code=404, detail="Network not found")
        if network.adjacency_file_path:
            try:
                edges_df = pd.read_parquet(network.adjacency_file_path)
                left_column = "gene1" if "gene1" in edges_df.columns else "source"
                right_column = "gene2" if "gene2" in edges_df.columns else "target"
                interactions = edges_df[[left_column, right_column]].dropna().astype(str).values.tolist()
            except Exception as exc:
                raise HTTPException(status_code=400, detail=f"Unable to read network edges: {exc}") from exc

    if not genes:
        raise HTTPException(status_code=400, detail="At least one gene or dataset is required.")

    normalized_interactions = []
    for pair in interactions:
        if len(pair) != 2:
            raise HTTPException(status_code=400, detail="Every interaction must be a pair of gene names.")
        normalized_interactions.append((str(pair[0]), str(pair[1])))

    try:
        image_summary = summarize_image(
            decode_image_from_data_url(payload.image_data_url)
            if payload.image_data_url
            else None
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid image payload: {exc}") from exc

    model = GeneLossRiskModel()
    model.fit(genes, expression, normalized_interactions)
    scores = model.predict_risk(genes, expression, normalized_interactions)
    network = build_ppi_network(genes, normalized_interactions)

    ranked = sorted(
        (
            {
                "gene": gene,
                "risk_score": float(result["risk_score"]),
                "probability": float(result["probability"]),
                "predicted_loss": bool(result["predicted_loss"]),
            }
            for gene, result in scores.items()
        ),
        key=lambda item: item["risk_score"],
        reverse=True,
    )

    return {
        "image_summary": image_summary,
        "network": network,
        "gene_scores": scores,
        "highest_risk_genes": ranked[:10],
    }