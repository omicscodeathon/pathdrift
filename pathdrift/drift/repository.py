from __future__ import annotations

from typing import Any, Iterable

import pandas as pd
from sqlalchemy import delete
from sqlalchemy.orm import Session

from ..acquisition.registry import json_safe


def clear_phase4_results(session: Session, run_id: str) -> None:
    from app.models import (
        RunCrossSpeciesNodeAlignment,
        RunGeneDrift,
        RunModuleDrift,
        RunNetworkEdgeDrift,
        RunOrthologyMapping,
        RunPhase4Summary,
    )

    for model in (
        RunNetworkEdgeDrift,
        RunGeneDrift,
        RunModuleDrift,
        RunCrossSpeciesNodeAlignment,
        RunOrthologyMapping,
        RunPhase4Summary,
    ):
        session.execute(delete(model).where(model.run_id == run_id))


def persist_alignment(session: Session, run_id: str, nodes: pd.DataFrame, edges: pd.DataFrame) -> None:
    from app.models import RunCrossSpeciesNodeAlignment, RunNetworkEdgeDrift

    node_rows = (
        RunCrossSpeciesNodeAlignment(
            run_id=run_id,
            human_ensembl_id=row["human_ensembl_id"],
            mouse_ensembl_id=row["mouse_ensembl_id"],
            human_symbol=_nullable_text(row.get("human_symbol")),
            mouse_symbol=_nullable_text(row.get("mouse_symbol")),
            orthology_type=row["orthology_type"],
            confidence=_finite(row.get("confidence")),
            human_network_present=bool(row["human_network_present"]),
            mouse_network_present=bool(row["mouse_network_present"]),
            is_primary=bool(row["is_primary"]),
        )
        for row in _records(nodes)
        if row["human_network_present"] or row["mouse_network_present"]
    )
    _add_chunks(session, node_rows)

    edge_rows = (
        RunNetworkEdgeDrift(
            run_id=run_id,
            human_edge_id=_nullable_text(row.get("human_edge_id")),
            mouse_edge_id=_nullable_text(row.get("mouse_edge_id")),
            human_source_gene_id=_nullable_text(row.get("human_source_gene")),
            human_target_gene_id=_nullable_text(row.get("human_target_gene")),
            mouse_source_gene_id=_nullable_text(row.get("mouse_source_gene")),
            mouse_target_gene_id=_nullable_text(row.get("mouse_target_gene")),
            human_weight=_finite(row.get("human_weight")),
            mouse_weight=_finite(row.get("mouse_weight")),
            human_p_value=_finite(row.get("human_p_value")),
            mouse_p_value=_finite(row.get("mouse_p_value")),
            human_adjusted_p_value=_finite(row.get("human_adjusted_p_value")),
            mouse_adjusted_p_value=_finite(row.get("mouse_adjusted_p_value")),
            weight_difference=_finite(row.get("weight_difference")),
            absolute_weight_difference=_finite(row.get("absolute_weight_difference")),
            relative_weight_change=_finite(row.get("relative_weight_change")),
            status=row["status"],
        )
        for row in _records(edges)
    )
    _add_chunks(session, edge_rows)


def persist_drift(session: Session, run_id: str, genes: pd.DataFrame, modules: pd.DataFrame) -> None:
    from app.models import RunGeneDrift, RunModuleDrift

    gene_rows = (
        RunGeneDrift(
            run_id=run_id,
            human_ensembl_id=row["human_ensembl_id"],
            mouse_ensembl_id=row["mouse_ensembl_id"],
            human_symbol=_nullable_text(row.get("human_symbol")),
            mouse_symbol=_nullable_text(row.get("mouse_symbol")),
            human_degree=int(row["human_degree"]),
            mouse_degree=int(row["mouse_degree"]),
            degree_difference=int(row["degree_difference"]),
            human_neighbor_count=int(row["human_neighbor_count"]),
            mouse_neighbor_count=int(row["mouse_neighbor_count"]),
            conserved_neighbor_count=int(row["conserved_neighbor_count"]),
            lost_neighbor_count=int(row["lost_neighbor_count"]),
            gained_neighbor_count=int(row["gained_neighbor_count"]),
            neighbor_similarity=float(row["neighbor_similarity"]),
            edge_loss_rate=float(row["edge_loss_rate"]),
            normalized_degree_difference=float(row["normalized_degree_difference"]),
            module_conservation=_finite(row.get("module_conservation")),
            drift_score=float(row["drift_score"]),
            drift_category=row["drift_category"],
        )
        for row in _records(genes)
    )
    _add_chunks(session, gene_rows)

    module_rows = (
        RunModuleDrift(
            run_id=run_id,
            human_module_id=str(row["human_module_id"]),
            candidate_mouse_module_id=row.get("candidate_mouse_module_id"),
            human_module_size=int(row["human_module_size"]),
            mapped_gene_count=int(row["mapped_gene_count"]),
            mouse_module_overlap=int(row["mouse_module_overlap"]),
            overlap_fraction=float(row["overlap_fraction"]),
            module_conservation_score=float(row["module_conservation_score"]),
            internal_edge_conservation=_finite(row.get("internal_edge_conservation")),
            classification=row["classification"],
        )
        for row in _records(modules)
    )
    _add_chunks(session, module_rows)


def persist_summary(
    session: Session,
    run_id: str,
    status: str,
    configuration: dict,
    summary: dict,
    provenance: dict,
) -> None:
    from app.models import RunPhase4Summary

    item = session.query(RunPhase4Summary).filter_by(run_id=run_id).one_or_none()
    if item is None:
        item = RunPhase4Summary(run_id=run_id)
        session.add(item)
    item.status = status
    item.configuration = json_safe(configuration)
    item.summary = json_safe(summary)
    item.provenance = json_safe(provenance)
    session.flush()


def _add_chunks(session: Session, items: Iterable[Any], chunk_size: int = 1000) -> None:
    chunk = []
    for item in items:
        chunk.append(item)
        if len(chunk) == chunk_size:
            session.add_all(chunk)
            session.flush()
            chunk.clear()
    if chunk:
        session.add_all(chunk)
        session.flush()


def _records(frame: pd.DataFrame):
    columns = list(frame.columns)
    for values in frame.itertuples(index=False, name=None):
        yield dict(zip(columns, values))


def _nullable_text(value: Any) -> str | None:
    if value is None or pd.isna(value):
        return None
    return str(value) or None


def _finite(value: Any) -> float | None:
    if value is None or pd.isna(value):
        return None
    number = float(value)
    return number if pd.notna(number) and abs(number) != float("inf") else None
