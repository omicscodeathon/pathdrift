from __future__ import annotations

import math
from typing import Any

import pandas as pd
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .acquisition.registry import json_safe


def _finite(value: Any) -> float | None:
    if value is None or pd.isna(value):
        return None
    converted = float(value)
    return converted if math.isfinite(converted) else None


def ensure_gene_catalog(session: Session, gene_ids: set[str], species: str) -> dict[str, str]:
    from app.models import Gene, SpeciesEnum

    species_value = SpeciesEnum(species)
    ids = sorted(gene_ids)
    found: dict[str, Gene] = {}
    for offset in range(0, len(ids), 1000):
        batch = ids[offset:offset + 1000]
        found.update({
            gene.ensembl_id: gene
            for gene in session.execute(
                select(Gene).where(Gene.species == species_value, Gene.ensembl_id.in_(batch))
            ).scalars()
        })
    missing = [gene_id for gene_id in ids if gene_id not in found]
    for offset in range(0, len(missing), 1000):
        session.add_all([
            Gene(ensembl_id=gene_id, species=species_value)
            for gene_id in missing[offset:offset + 1000]
        ])
        session.flush()
        batch = missing[offset:offset + 1000]
        found.update({
            gene.ensembl_id: gene
            for gene in session.execute(
                select(Gene).where(Gene.species == species_value, Gene.ensembl_id.in_(batch))
            ).scalars()
        })
    return {ensembl_id: gene.id for ensembl_id, gene in found.items()}


def persist_de_results(
    session: Session,
    *,
    run_id: str,
    dataset_id: str,
    species: str,
    comparison: str,
    results: pd.DataFrame,
    summary: dict,
) -> int:
    from app.models import RunDifferentialExpression, RunFigure

    session.execute(delete(RunFigure).where(
        RunFigure.run_id == run_id,
        RunFigure.dataset_id == dataset_id,
        RunFigure.stage == "deg",
    ))
    gene_map = ensure_gene_catalog(
        session,
        set(results["gene_id"].astype(str)),
        species,
    )
    session.execute(delete(RunDifferentialExpression).where(
        RunDifferentialExpression.run_id == run_id,
        RunDifferentialExpression.dataset_id == dataset_id,
        RunDifferentialExpression.comparison == comparison,
    ))
    rows = []
    for row in results.to_dict(orient="records"):
        rows.append(RunDifferentialExpression(
            run_id=run_id,
            dataset_id=dataset_id,
            gene_id=gene_map[str(row["gene_id"])],
            species=species,
            comparison=comparison,
            method=str(row["method"]),
            log2fc=_finite(row.get("log2fc")),
            pvalue=_finite(row.get("pvalue")),
            adjusted_p_value=_finite(row.get("adjusted_p_value")),
            statistic=_finite(row.get("statistic")),
            base_mean=_finite(row.get("base_mean")),
            average_expression=_finite(row.get("average_expression")),
            direction=str(row["direction"]),
            significant=bool(row["significant"]),
            thresholds={
                "alpha": summary["alpha"],
                "lfc_threshold": summary["lfc_threshold"],
                "fdr_method": summary.get("fdr_method", "Benjamini-Hochberg"),
            },
        ))
    for offset in range(0, len(rows), 1000):
        session.add_all(rows[offset:offset + 1000])
        session.flush()
    return len(rows)


def persist_network_result(
    session: Session,
    *,
    run_id: str,
    dataset_id: str,
    species: str,
    state: str,
    name: str,
    method: str,
    result: dict,
    module_result: dict | None,
) -> str:
    from app.models import (
        RunGeneNetwork,
        RunModuleGene,
        RunNetworkEdge,
        RunNetworkModule,
        RunNetworkNode,
    )

    network = session.execute(select(RunGeneNetwork).where(
        RunGeneNetwork.run_id == run_id,
        RunGeneNetwork.dataset_id == dataset_id,
        RunGeneNetwork.name == name,
    )).scalar_one_or_none()
    if network is not None:
        session.delete(network)
        session.flush()
    network = RunGeneNetwork(
        run_id=run_id,
        dataset_id=dataset_id,
        name=name,
        species=species,
        disease_state=state,
        method=method,
        configuration=json_safe(result["summary"].get("filtering", {})),
        summary=json_safe(result["summary"]),
    )
    session.add(network)
    session.flush()

    nodes = result["nodes"] if module_result is None else module_result["nodes"]
    gene_ids = set(nodes["gene_id"].astype(str))
    gene_ids.update(result["edges"]["source_gene"].astype(str))
    gene_ids.update(result["edges"]["target_gene"].astype(str))
    gene_map = ensure_gene_catalog(session, gene_ids, species)

    module_map: dict[str, str] = {}
    if module_result is not None:
        for module in module_result["modules"].to_dict(orient="records"):
            entity = RunNetworkModule(
                network_id=network.id,
                module_key=str(module["module_id"]),
                size=int(module["size"]),
                detection_method=str(module["detection_method"]),
                parameters={
                    "resolution": module["resolution"],
                    "min_module_size": module["min_module_size"],
                },
                statistics=json_safe(module),
            )
            session.add(entity)
            session.flush()
            module_map[str(module["module_id"])] = entity.id
        session.add_all([
            RunModuleGene(
                module_id=module_map[str(row["module_id"])],
                gene_id=gene_map[str(row["gene_id"])],
                membership=None,
            )
            for row in module_result["genes"].to_dict(orient="records")
        ])
        session.flush()

    node_records = []
    for row in nodes.to_dict(orient="records"):
        module_key = row.get("module_id")
        node_records.append(RunNetworkNode(
            network_id=network.id,
            gene_id=gene_map[str(row["gene_id"])],
            module_id=module_map.get(str(module_key)) if module_key else None,
            degree=int(row["degree"]),
            weighted_degree=float(row["weighted_degree"]),
            betweenness_centrality=_finite(row.get("betweenness_centrality")),
            closeness_centrality=_finite(row.get("closeness_centrality")),
            eigenvector_centrality=_finite(row.get("eigenvector_centrality")),
        ))
    for offset in range(0, len(node_records), 1000):
        session.add_all(node_records[offset:offset + 1000])
        session.flush()

    edge_records = [
        RunNetworkEdge(
            network_id=network.id,
            source_gene_id=gene_map[str(row["source_gene"])],
            target_gene_id=gene_map[str(row["target_gene"])],
            correlation=float(row["correlation"]),
            absolute_correlation=float(row["absolute_correlation"]),
            pvalue=float(row["p_value"]),
            adjusted_p_value=float(row["adjusted_p_value"]),
            weight=float(row["weight"]),
        )
        for row in result["edges"].to_dict(orient="records")
    ]
    for offset in range(0, len(edge_records), 1000):
        session.add_all(edge_records[offset:offset + 1000])
        session.flush()
    return network.id


def delete_phase3_results(session: Session, run_id: str, *, stage: str = "phase3") -> None:
    from app.models import (
        RunDifferentialExpression,
        RunFigure,
        RunGeneNetwork,
    )

    if stage in {"phase3", "deg"}:
        session.execute(delete(RunFigure).where(
            RunFigure.run_id == run_id,
            RunFigure.stage == "deg",
        ))
        session.execute(delete(RunDifferentialExpression).where(RunDifferentialExpression.run_id == run_id))
    if stage in {"phase3", "networks", "modules"}:
        session.execute(delete(RunGeneNetwork).where(RunGeneNetwork.run_id == run_id))
    session.flush()
