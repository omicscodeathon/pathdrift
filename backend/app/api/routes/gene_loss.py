from __future__ import annotations

import asyncio
import os
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, Field
import pandas as pd

from app.bio.gene_loss import (
    GeneLossRiskModel,
    build_ppi_network,
    decode_image_from_data_url,
    expression_loss_evidence,
    module_disruption_evidence,
    summarize_image,
)
from app.api.deps import get_current_user
from app.db.base import get_db
from app.models import (
    Analysis, CrossSpeciesAnalysis, DEGResult, Dataset, DriftAnalysis,
    GeneNetwork, JobStatusEnum, OrthologyMapping, Project, User,
)

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


@router.get("/evidence/{comparison_id}")
async def get_gene_loss_evidence(
    comparison_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    comparison_result = await db.execute(
        select(CrossSpeciesAnalysis, Analysis.project_id)
        .join(Analysis, Analysis.id == CrossSpeciesAnalysis.analysis_id)
        .where(
            CrossSpeciesAnalysis.id == comparison_id,
            Analysis.project.has(owner_id=current_user.id),
            CrossSpeciesAnalysis.status == JobStatusEnum.COMPLETED,
        )
    )
    comparison_row = comparison_result.one_or_none()
    if not comparison_row:
        raise HTTPException(status_code=404, detail="Completed cross-species comparison not found")
    comparison, project_id = comparison_row

    drift_result = await db.execute(
        select(DriftAnalysis)
        .join(Analysis, Analysis.id == DriftAnalysis.analysis_id)
        .where(
            DriftAnalysis.id.in_([comparison.human_drift_id, comparison.mouse_drift_id]),
            Analysis.project_id == project_id,
            DriftAnalysis.status == JobStatusEnum.COMPLETED,
        )
    )
    drifts = {drift.id: drift for drift in drift_result.scalars().all()}
    human_drift = drifts.get(comparison.human_drift_id)
    mouse_drift = drifts.get(comparison.mouse_drift_id)
    if not human_drift or not mouse_drift:
        raise HTTPException(status_code=409, detail="Both completed species drift results are required")

    network_ids = [
        human_drift.healthy_network_id, human_drift.disease_network_id,
        mouse_drift.healthy_network_id, mouse_drift.disease_network_id,
    ]
    network_result = await db.execute(
        select(GeneNetwork)
        .join(Analysis, Analysis.id == GeneNetwork.analysis_id)
        .where(GeneNetwork.id.in_(network_ids), Analysis.project_id == project_id)
    )
    networks = {network.id: network for network in network_result.scalars().all()}
    human_normal_network = networks.get(human_drift.healthy_network_id)
    human_disease_network = networks.get(human_drift.disease_network_id)
    mouse_normal_network = networks.get(mouse_drift.healthy_network_id)
    mouse_disease_network = networks.get(mouse_drift.disease_network_id)

    async def read_parquet_if_available(path: Optional[str]) -> Optional[pd.DataFrame]:
        if not path or not os.path.isfile(path):
            return None
        try:
            return await asyncio.to_thread(pd.read_parquet, path)
        except (OSError, ValueError, ImportError):
            return None

    human_normal_nodes, human_disease_nodes, mouse_normal_nodes, mouse_disease_nodes, human_edge_drift, mouse_edge_drift = await asyncio.gather(
        read_parquet_if_available(human_normal_network.node_features_file_path if human_normal_network else None),
        read_parquet_if_available(human_disease_network.node_features_file_path if human_disease_network else None),
        read_parquet_if_available(mouse_normal_network.node_features_file_path if mouse_normal_network else None),
        read_parquet_if_available(mouse_disease_network.node_features_file_path if mouse_disease_network else None),
        read_parquet_if_available(human_drift.edge_drift_file_path),
        read_parquet_if_available(mouse_drift.edge_drift_file_path),
    )

    mapping_result = await db.execute(
        select(
            OrthologyMapping.human_ensembl_id,
            OrthologyMapping.mouse_ensembl_id,
            OrthologyMapping.human_symbol,
            OrthologyMapping.mouse_symbol,
        ).where(OrthologyMapping.orthology_type == "ortholog_one2one")
    )
    mappings = mapping_result.all()
    human_symbols = {str(row.human_ensembl_id): row.human_symbol for row in mappings if row.human_symbol}
    mouse_symbols = {str(row.mouse_ensembl_id): row.mouse_symbol for row in mappings if row.mouse_symbol}
    human_to_mouse = {str(row.human_ensembl_id): str(row.mouse_ensembl_id) for row in mappings}
    mouse_to_human = {str(row.mouse_ensembl_id): str(row.human_ensembl_id) for row in mappings}

    evidence_by_gene: dict[tuple[str, str], dict[str, Any]] = {}

    def get_evidence_row(species: str, gene_id: str) -> dict[str, Any]:
        key = (species, gene_id)
        if key not in evidence_by_gene:
            symbols = human_symbols if species == "human" else mouse_symbols
            counterpart_map = human_to_mouse if species == "human" else mouse_to_human
            counterpart_id = counterpart_map.get(gene_id)
            counterpart_symbols = mouse_symbols if species == "human" else human_symbols
            evidence_by_gene[key] = {
                "species": species,
                "gene_id": gene_id,
                "symbol": symbols.get(gene_id),
                "ortholog_id": counterpart_id,
                "ortholog_symbol": counterpart_symbols.get(counterpart_id) if counterpart_id else None,
                "evidence": [],
            }
        return evidence_by_gene[key]

    def feature_gene_ids(features: Optional[pd.DataFrame]) -> set[str]:
        if features is None:
            return set()
        if "gene_id" in features.columns:
            return set(features["gene_id"].dropna().astype(str))
        return set(features.index.astype(str))

    human_observed = feature_gene_ids(human_normal_nodes) | feature_gene_ids(human_disease_nodes)
    mouse_observed = feature_gene_ids(mouse_normal_nodes) | feature_gene_ids(mouse_disease_nodes)
    for gene_id in sorted(human_observed - set(human_to_mouse)):
        get_evidence_row("human", gene_id)["evidence"].append({
            "type": "Orthology loss",
            "detail": "No one-to-one Ensembl orthology mapping is recorded; this is not proof of genomic deletion.",
        })
    for gene_id in sorted(mouse_observed - set(mouse_to_human)):
        get_evidence_row("mouse", gene_id)["evidence"].append({
            "type": "Orthology loss",
            "detail": "No one-to-one Ensembl orthology mapping is recorded; this is not proof of genomic deletion.",
        })

    def add_lost_edge_evidence(species: str, edge_frame: Optional[pd.DataFrame]):
        if edge_frame is None or not {"gene1", "gene2", "type"}.issubset(edge_frame.columns):
            return 0
        lost_edges = edge_frame[edge_frame["type"] == "lost"]
        neighbors: dict[str, list[str]] = {}
        for gene1, gene2 in lost_edges[["gene1", "gene2"]].dropna().astype(str).itertuples(index=False, name=None):
            neighbors.setdefault(gene1, []).append(gene2)
            neighbors.setdefault(gene2, []).append(gene1)
        for gene_id, neighbor_ids in neighbors.items():
            get_evidence_row(species, gene_id)["evidence"].append({
                "type": "Network loss",
                "detail": f"{len(neighbor_ids)} normal-network edge(s) absent from the disease network.",
                "lost_neighbors": sorted(set(neighbor_ids))[:10],
            })
        return len(lost_edges)

    human_lost_edges = add_lost_edge_evidence("human", human_edge_drift)
    mouse_lost_edges = add_lost_edge_evidence("mouse", mouse_edge_drift)

    from app.bio.gene_loss import module_disruption_evidence
    module_changes = {
        "human": module_disruption_evidence(human_normal_nodes, human_disease_nodes)
        if human_normal_nodes is not None and human_disease_nodes is not None else {},
        "mouse": module_disruption_evidence(mouse_normal_nodes, mouse_disease_nodes)
        if mouse_normal_nodes is not None and mouse_disease_nodes is not None else {},
    }
    for species, changes in module_changes.items():
        for gene_id, change in changes.items():
            get_evidence_row(species, gene_id)["evidence"].append({
                "type": "Module loss",
                "detail": "Gene no longer belongs to the best-overlap disease module.",
                **change,
            })

    deg_results = await db.execute(
        select(DEGResult)
        .where(
            DEGResult.analysis_id.in_([human_drift.analysis_id, mouse_drift.analysis_id]),
            DEGResult.status == JobStatusEnum.COMPLETED,
            DEGResult.results_file_path.is_not(None),
        )
        .order_by(DEGResult.created_at.desc())
    )
    completed_degs = deg_results.scalars().all()
    latest_deg_by_dataset = {}
    for deg_result in completed_degs:
        latest_deg_by_dataset.setdefault(deg_result.dataset_id, deg_result)
    expression_species_assessed = {"human": False, "mouse": False}
    expression_gene_count = {"human": 0, "mouse": 0}
    from app.bio.gene_loss import expression_loss_evidence
    for species, network, drift in [
        ("human", human_disease_network, human_drift),
        ("mouse", mouse_disease_network, mouse_drift),
    ]:
        deg_result = latest_deg_by_dataset.get(network.dataset_id) if network else None
        if not deg_result or not os.path.isfile(deg_result.results_file_path):
            continue
        expression_species_assessed[species] = True
        try:
            deg_frame = await asyncio.to_thread(pd.read_parquet, deg_result.results_file_path)
        except (OSError, ValueError, ImportError):
            continue
        expression_losses = expression_loss_evidence(deg_frame)
        expression_gene_count[species] = len(expression_losses)
        for gene_id, stats in expression_losses.items():
            get_evidence_row(species, gene_id)["evidence"].append({
                "type": "Expression loss",
                "detail": "Significantly downregulated in the saved DEG analysis.",
                **stats,
                "deg_result_id": deg_result.id,
            })

    rows = [
        row for row in evidence_by_gene.values()
        if row["evidence"]
    ]
    rows.sort(key=lambda row: (row["species"], row["symbol"] or row["gene_id"]))
    evidence_counts = {
        evidence_type: sum(
            any(item["type"] == evidence_type for item in row["evidence"])
            for row in rows
        )
        for evidence_type in ["Orthology loss", "Expression loss", "Network loss", "Module loss"]
    }
    return {
        "comparison_id": comparison.id,
        "rows": rows[:5000],
        "coverage": {
            "orthology": {"available": bool(mappings), "mappings_loaded": len(mappings), "genes_with_evidence": evidence_counts["Orthology loss"]},
            "expression": {"available": any(expression_species_assessed.values()), "species_assessed": expression_species_assessed, "genes_with_evidence": evidence_counts["Expression loss"]},
            "network": {"available": human_edge_drift is not None or mouse_edge_drift is not None, "human_lost_edges": human_lost_edges, "mouse_lost_edges": mouse_lost_edges, "genes_with_evidence": evidence_counts["Network loss"]},
            "ppi": {"available": False, "message": "No PPI reference network is configured; co-expression edges are not treated as PPI evidence."},
            "module": {"available": all(frame is not None for frame in [human_normal_nodes, human_disease_nodes, mouse_normal_nodes, mouse_disease_nodes]), "genes_with_evidence": evidence_counts["Module loss"]},
        },
    }


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