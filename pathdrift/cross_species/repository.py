from __future__ import annotations

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session


def load_cancer_networks(session: Session, run_id: str) -> dict:
    from app.models import (
        Gene,
        RunGeneNetwork,
        RunModuleGene,
        RunNetworkEdge,
        RunNetworkModule,
        RunNetworkNode,
    )

    networks = session.execute(
        select(RunGeneNetwork).where(
            RunGeneNetwork.run_id == run_id,
            RunGeneNetwork.disease_state == "cancer",
            RunGeneNetwork.species.in_(["human", "mouse"]),
        )
    ).scalars().all()
    by_species: dict[str, list] = {"human": [], "mouse": []}
    for network in networks:
        by_species[str(network.species)].append(network)
    for species, matches in by_species.items():
        if len(matches) != 1:
            raise ValueError(
                f"Phase 4 requires exactly one completed {species} cancer network for run {run_id}; "
                f"found {len(matches)}. No network was substituted."
            )

    result = {}
    for species, network in (("human", by_species["human"][0]), ("mouse", by_species["mouse"][0])):
        node_rows = session.execute(
            select(
                Gene.ensembl_id.label("gene_id"),
                Gene.gene_symbol.label("gene_symbol"),
                RunNetworkNode.degree,
                RunNetworkNode.weighted_degree,
                RunNetworkNode.module_id.label("module_id"),
            )
            .join(RunNetworkNode, RunNetworkNode.gene_id == Gene.id)
            .where(RunNetworkNode.network_id == network.id)
        ).mappings().all()
        edge_rows = session.execute(
            select(
                RunNetworkEdge.id.label("edge_id"),
                Gene.ensembl_id.label("source_gene"),
                RunNetworkEdge.target_gene_id.label("_target_gene_pk"),
                RunNetworkEdge.correlation.label("weight"),
                RunNetworkEdge.pvalue.label("pvalue"),
                RunNetworkEdge.adjusted_p_value.label("adjusted_p_value"),
            )
            .join(Gene, Gene.id == RunNetworkEdge.source_gene_id)
            .where(RunNetworkEdge.network_id == network.id)
        ).mappings().all()
        target_ids = {row["_target_gene_pk"] for row in edge_rows}
        target_symbols = {
            str(gene_pk): ensembl_id
            for gene_pk, ensembl_id in session.execute(
                select(Gene.id, Gene.ensembl_id).where(Gene.id.in_(target_ids))
            ).all()
        }
        edges = pd.DataFrame([
            {
                "edge_id": row["edge_id"],
                "source_gene": row["source_gene"],
                "target_gene": target_symbols[str(row["_target_gene_pk"])],
                "weight": float(row["weight"]),
                "pvalue": float(row["pvalue"]) if row["pvalue"] is not None else None,
                "adjusted_p_value": float(row["adjusted_p_value"]) if row["adjusted_p_value"] is not None else None,
            }
            for row in edge_rows
        ], columns=["edge_id", "source_gene", "target_gene", "weight", "pvalue", "adjusted_p_value"])

        module_rows = session.execute(
            select(
                RunNetworkModule.id.label("module_id"),
                RunNetworkModule.module_key.label("module_key"),
                RunNetworkModule.size.label("size"),
                RunNetworkModule.statistics.label("statistics"),
            ).where(RunNetworkModule.network_id == network.id)
        ).mappings().all()
        modules = pd.DataFrame([dict(row) for row in module_rows], columns=["module_id", "module_key", "size", "statistics"])
        module_gene_rows = session.execute(
            select(
                RunModuleGene.module_id.label("module_id"),
                Gene.ensembl_id.label("gene_id"),
            )
            .join(Gene, Gene.id == RunModuleGene.gene_id)
            .join(RunNetworkModule, RunNetworkModule.id == RunModuleGene.module_id)
            .where(RunNetworkModule.network_id == network.id)
        ).mappings().all()
        module_genes = pd.DataFrame([dict(row) for row in module_gene_rows], columns=["module_id", "gene_id"])
        result[species] = {
            "network": network,
            "nodes": pd.DataFrame([dict(row) for row in node_rows], columns=["gene_id", "gene_symbol", "degree", "weighted_degree", "module_id"]),
            "edges": edges,
            "modules": modules,
            "module_genes": module_genes,
        }
    return result
