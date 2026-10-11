from __future__ import annotations

import json
import hashlib
import logging
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from ..acquisition.registry import ROOT
from .scoring import (
    DEFAULT_CONFIGURATION,
    build_biomarker_candidates,
    build_gene_loss_tables,
    compute_hub_metrics,
)
from .pathways import (
    COMPARISON_COLUMNS,
    ORA_COLUMNS,
    Pathway,
    build_pathway_gene_sets,
    compare_pathways,
    load_gene_identifier_maps,
    load_pathway_libraries,
    ranked_gsea,
    run_over_representation,
)
from .phenotype import build_phenotype_metadata

logger = logging.getLogger("pathdrift.phase5")

REQUIRED_INPUTS = (
    Path("deg/human/all_genes.csv"),
    Path("deg/human/significant_genes.csv"),
    Path("deg/mouse/cross_study_exploratory/all_genes.csv"),
    Path("networks/human_cancer_nodes.csv"),
    Path("drift/gene_drift.csv"),
    Path("orthology/orthologs.csv"),
)


def run_phase5(run_id: str, *, force: bool = False, run_gsea: bool = False) -> dict[str, Any]:
    if len(run_id) != 36 or any(character not in "0123456789abcdefABCDEF-" for character in run_id):
        raise ValueError("run_id must be a UUID.")
    run_directory = (ROOT / "results" / "runs" / run_id).resolve()
    try:
        run_directory.relative_to((ROOT / "results" / "runs").resolve())
    except ValueError as exc:
        raise ValueError("The requested run path is invalid.") from exc
    manifest_path = run_directory / "manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"Saved analysis manifest is missing for run {run_id}.")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or manifest.get("run_id") != run_id:
        raise ValueError(f"Saved analysis manifest does not match run {run_id}.")
    phase3 = manifest.get("phase3")
    if (
        str(manifest.get("status", "")).upper() != "COMPLETED"
        or not isinstance(phase3, dict)
        or str(phase3.get("status", "")).upper() != "COMPLETED"
    ):
        raise ValueError(f"Run {run_id} does not have a completed Phase 3 manifest.")

    summary_path = run_directory / "phase5_summary.json"
    if summary_path.is_file() and not force and not run_gsea:
        cached_summary = json.loads(summary_path.read_text(encoding="utf-8"))
        if not isinstance(cached_summary, dict) or cached_summary.get("run_id") != run_id:
            raise ValueError(f"Saved Phase 5 summary does not match run {run_id}.")
        if cached_summary.get("analysis_version") == "phase5-pathway-local-2":
            return cached_summary
    missing = [str(path) for path in REQUIRED_INPUTS if not (run_directory / path).is_file()]
    if missing:
        raise FileNotFoundError(f"Required Phase 3/4 artifacts are missing: {', '.join(missing)}.")

    human_deg = _read_csv(run_directory / "deg/human/all_genes.csv")
    human_significant = _read_csv(run_directory / "deg/human/significant_genes.csv")
    mouse_deg = _read_csv(run_directory / "deg/mouse/cross_study_exploratory/all_genes.csv")
    human_nodes = _read_csv(run_directory / "networks/human_cancer_nodes.csv")
    drift = _read_csv(run_directory / "drift/gene_drift.csv")
    orthology = _read_csv(run_directory / "orthology/orthologs.csv")
    human_edges_path = run_directory / "networks/human_healthy/human_cancer_edges.csv"
    human_edges = _read_csv(human_edges_path) if human_edges_path.is_file() else None

    evidence, scores, high_risk = build_gene_loss_tables(
        human_deg,
        mouse_deg,
        drift,
        orthology,
    )
    biomarkers = build_biomarker_candidates(human_significant, human_nodes, drift, orthology, human_edges)

    gene_loss_dir = run_directory / "gene_loss"
    hub_dir = run_directory / "hub_genes"
    biomarkers_dir = run_directory / "biomarkers"
    gene_loss_dir.mkdir(parents=True, exist_ok=True)
    biomarkers_dir.mkdir(parents=True, exist_ok=True)
    hub_dir.mkdir(parents=True, exist_ok=True)
    _write_csv(gene_loss_dir / "gene_loss_evidence.csv", evidence)
    _write_csv(gene_loss_dir / "gene_loss_scores.csv", scores)
    _write_csv(gene_loss_dir / "high_risk_genes.csv", high_risk)
    hub_summaries = _write_hub_gene_tables(run_directory, hub_dir)
    pathway_summary, biomarkers, morphology_summary = _write_pathway_analysis(
        run_directory,
        manifest,
        human_deg,
        mouse_deg,
        biomarkers,
        run_gsea=run_gsea,
    )
    _write_csv(biomarkers_dir / "candidate_biomarkers.csv", biomarkers)
    _write_phase5_figures(run_directory, scores, biomarkers)

    unavailable = {
        "ppi": {
            "status": "UNAVAILABLE",
            "reason": "No run-wide, versioned PPI reference network was acquired for this run. Co-expression edges are not treated as PPI evidence.",
            "source": None,
            "rows": 0,
        },
    }
    for stage, stage_summary in unavailable.items():
        _write_json(run_directory / stage / f"{stage}_summary.json", stage_summary)

    now = datetime.now(timezone.utc).isoformat()
    summary = {
        "analysis_version": "phase5-pathway-local-2",
        "status": "PARTIAL",
        "run_id": run_id,
        "generated_at": now,
        "stages": {
            "gene_loss": {
                "status": "COMPLETED",
                "evidence_rows": len(evidence),
                "scored_gene_pairs": int(scores["risk_score"].notna().sum()) if "risk_score" in scores else 0,
                "high_risk_gene_pairs": len(high_risk),
                "configuration": DEFAULT_CONFIGURATION,
                "limitations": [
                    "Research prioritization only, not a clinical risk estimate.",
                    "Human cancer and mouse cancer networks differ substantially in size and density.",
                    "Mouse expression is from an independent-study exploratory comparison and is reported but excluded from the score.",
                    "Absence of a one-to-one orthology record is not proof of genomic deletion.",
                    "Missing evidence is null and excluded from the normalized score; it is not replaced with zero.",
                ],
            },
            "biomarkers": {
                "status": "COMPLETED",
                "candidate_count": len(biomarkers),
                "significant_human_deg_input_count": len(human_significant),
                "eligible_multi_evidence_candidate_count": len(biomarkers),
                "evidence_category_counts": _biomarker_category_counts(biomarkers),
                "selection_basis": DEFAULT_CONFIGURATION["biomarker_selection"],
                "clinical_validation": False,
                "limitations": [
                    "Candidates are research-only and have not undergone independent or clinical validation.",
                    "Drift and lost/gained interaction evidence derive from related saved network comparisons and are not independent validation.",
                    "The human and mouse cancer networks differ substantially in size and density.",
                ],
            },
            "hub_genes": {
                "status": "COMPLETED" if hub_summaries else "UNAVAILABLE",
                "networks": hub_summaries,
                "method": (
                    "Within-module arithmetic mean percentile of available degree, weighted degree, "
                    "betweenness, eigenvector centrality, closeness, and intramodular connectivity; "
                    "hub-supported when at least two metrics are available and their mean percentile "
                    "is >= 0.90. Missing metrics are excluded."
                ),
            },
            "pathways": pathway_summary,
            "morphology": morphology_summary,
            **unavailable,
        },
        "input_artifacts": [str(path).replace("\\", "/") for path in REQUIRED_INPUTS],
        "figures": [
            "gene_loss/gene_loss_risk_distribution.png",
            "biomarkers/candidate_volcano.png",
            "pathways/enrichment_results.csv",
            "pathways/pathway_comparisons.csv",
            "pathways/key_drifted_pathways.csv",
            "morphology/phenotype_variables.csv",
        ],
        "provenance": {
            "source_run_manifest": "manifest.json",
            "source_phase4_orthology": "orthology/orthologs.csv",
            "source_phase4_gene_drift": "drift/gene_drift.csv",
            "source_human_deg": "deg/human/all_genes.csv",
            "source_mouse_deg": "deg/mouse/cross_study_exploratory/all_genes.csv",
            "source_human_cancer_nodes": "networks/human_cancer_nodes.csv",
            "source_human_cancer_edges": "networks/human_healthy/human_cancer_edges.csv",
            "mouse_expression_design": "Exploratory cross-study comparison; not matched-control evidence.",
            "configuration": DEFAULT_CONFIGURATION,
            "pathway_analysis": pathway_summary.get("provenance", {}),
        },
    }
    _write_json(gene_loss_dir / "summary.json", summary["stages"]["gene_loss"])
    _write_json(biomarkers_dir / "summary.json", summary["stages"]["biomarkers"])
    _write_json(run_directory / "phase5_summary.json", summary)
    logger.info(
        "Phase 5 evidence generated for run %s: %s gene pairs, %s biomarker candidates",
        run_id,
        len(evidence),
        len(biomarkers),
    )
    return summary


def _write_pathway_analysis(
    run_directory: Path,
    manifest: dict[str, Any],
    human_deg: pd.DataFrame,
    mouse_deg: pd.DataFrame,
    biomarkers: pd.DataFrame,
    *,
    run_gsea: bool,
) -> tuple[dict[str, Any], pd.DataFrame, dict[str, Any]]:
    reference_dir = ROOT / "data" / "pathdrift" / "reference" / "pathways" / "2026-10-06"
    pathway_dir = run_directory / "pathways"
    morphology_dir = run_directory / "morphology"
    pathway_dir.mkdir(parents=True, exist_ok=True)
    morphology_dir.mkdir(parents=True, exist_ok=True)
    sample_metadata, phenotype_variables, morphology_summary = build_phenotype_metadata(
        run_directory,
        ROOT,
        manifest,
    )
    _write_csv(morphology_dir / "phenotype_sample_metadata.csv", sample_metadata)
    _write_csv(morphology_dir / "phenotype_variables.csv", phenotype_variables)
    _write_json(morphology_dir / "morphology_summary.json", morphology_summary)

    required_reference_files = (
        "go-basic.obo",
        "goa_human.gaf.gz",
        "goa_mouse.gaf.gz",
        "ReactomePathways.gmt.zip",
        "wikipathways-20260910-gmt-Homo_sapiens.gmt",
        "wikipathways-20260910-gmt-Mus_musculus.gmt",
        "ensembl_human_gene_ids.tsv",
        "ensembl_mouse_gene_ids.tsv",
    )
    missing = [name for name in required_reference_files if not (reference_dir / name).is_file()]
    if missing:
        stage_summary = {
            "status": "UNAVAILABLE",
            "reason": (
                "Offline versioned pathway references are not available locally: "
                + ", ".join(missing)
                + ". No gene lists were sent to an external service."
            ),
            "fdr_threshold": 0.05,
            "gsea_status": "NOT_RUN",
            "input_gene_sets": 0,
            "ora_rows": 0,
            "comparison_rows": 0,
            "key_drifted_pathway_count": 0,
            "provenance": {"reference_directory": str(reference_dir.relative_to(ROOT)).replace("\\", "/")},
            "limitations": [
                "No pathway conclusion is available until the approved local reference snapshots are present.",
                "Mouse DEG results are an exploratory independent-study comparison.",
            ],
        }
        _write_csv(pathway_dir / "gene_sets.csv", pd.DataFrame(columns=[
            "species", "gene_set_key", "gene_set_label", "gene_id", "gene_symbol", "source_artifact",
        ]))
        _write_csv(pathway_dir / "enrichment_results.csv", pd.DataFrame(columns=ORA_COLUMNS))
        _write_csv(pathway_dir / "pathway_comparisons.csv", pd.DataFrame(columns=COMPARISON_COLUMNS))
        _write_csv(pathway_dir / "key_drifted_pathways.csv", pd.DataFrame(columns=COMPARISON_COLUMNS))
        _write_csv(pathway_dir / "gsea_results.csv", pd.DataFrame(columns=[
            "species", "database", "pathway_id", "pathway_key", "enrichment_score",
            "normalized_enrichment_score", "p_value", "adjusted_p_value",
            "leading_edge_symbols", "method", "permutation_num", "random_seed",
        ]))
        biomarkers = _attach_candidate_pathway_evidence(
            biomarkers,
            pd.DataFrame(),
            pd.DataFrame(),
            {"human": []},
            morphology_summary,
            pathway_status="UNAVAILABLE",
        )
        _write_csv(run_directory / "biomarkers" / "candidate_profiles.csv", biomarkers)
        _write_json(pathway_dir / "provenance.json", stage_summary["provenance"])
        _write_json(pathway_dir / "pathways_summary.json", stage_summary)
        return stage_summary, biomarkers, morphology_summary

    logger.info("Loading local pathway references for run %s", run_directory.name)
    gene_maps = load_gene_identifier_maps(reference_dir)
    libraries = load_pathway_libraries(reference_dir, gene_maps)
    gene_set_table, gene_sets = build_pathway_gene_sets(run_directory, gene_maps)
    logger.info(
        "Loaded %s local pathway terms and %s run-specific gene sets",
        sum(len(pathways) for pathways in libraries.values()),
        len(gene_sets),
    )
    expressed_universes = {
        "human": set(human_deg["gene_id"].dropna().astype(str)),
        "mouse": set(mouse_deg["gene_id"].dropna().astype(str)),
    }
    enrichment = run_over_representation(
        gene_sets,
        libraries,
        gene_maps,
        expressed_universes,
        fdr_threshold=0.05,
    )
    logger.info("Calculated local ORA for run %s: %s overlapping terms", run_directory.name, len(enrichment))
    _write_csv(pathway_dir / "gene_sets.csv", gene_set_table)
    _write_csv(pathway_dir / "enrichment_results.csv", enrichment)

    network_edges: dict[str, pd.DataFrame | None] = {}
    network_nodes: dict[str, pd.DataFrame | None] = {}
    for name, node_path, edge_path in (
        ("human_cancer", "networks/human_cancer_nodes.csv", "networks/human_healthy/human_cancer_edges.csv"),
        ("human_healthy", "networks/human_healthy_nodes.csv", "networks/human_healthy/human_healthy_edges.csv"),
        ("mouse_cancer", "networks/mouse_cancer_nodes.csv", "networks/mouse_cancer_edges.csv"),
        ("mouse_healthy", "networks/mouse_healthy_nodes.csv", "networks/mouse_healthy_edges.csv"),
    ):
        node_file, edge_file = run_directory / node_path, run_directory / edge_path
        network_nodes[name] = _read_csv(node_file) if node_file.is_file() else None
        network_edges[name] = _read_csv(edge_file) if edge_file.is_file() else None
    modules = {}
    for species in ("human", "mouse"):
        module_path = run_directory / "modules" / species / "module_genes.csv"
        modules[species] = _read_csv(module_path) if module_path.is_file() else None
    orthology_path = run_directory / "orthology/orthologs.csv"
    orthology = _read_csv(orthology_path) if orthology_path.is_file() else pd.DataFrame()
    comparisons = compare_pathways(
        enrichment,
        libraries,
        orthology,
        network_edges,
        network_nodes,
        modules,
        fdr_threshold=0.05,
    )
    logger.info(
        "Compared significant cross-species pathways for run %s: %s rows",
        run_directory.name,
        len(comparisons),
    )
    key_drifted = (
        comparisons.loc[comparisons["key_drifted_pathway"].fillna(False).astype(bool)].copy()
        if "key_drifted_pathway" in comparisons
        else comparisons.iloc[0:0].copy()
    )
    _write_csv(pathway_dir / "pathway_comparisons.csv", comparisons)
    _write_csv(pathway_dir / "key_drifted_pathways.csv", key_drifted)

    gsea_results: list[pd.DataFrame] = []
    if run_gsea:
        for species, ranking in (("human", human_deg), ("mouse", mouse_deg)):
            gsea_results.append(ranked_gsea(ranking, species, libraries[species], gene_maps[species]))
    gsea = pd.concat(gsea_results, ignore_index=True) if gsea_results else pd.DataFrame()
    if gsea.empty:
        gsea = pd.DataFrame(columns=[
            "species", "database", "pathway_id", "pathway_key", "enrichment_score",
            "normalized_enrichment_score", "p_value", "adjusted_p_value",
            "leading_edge_symbols", "method", "permutation_num", "random_seed",
        ])
    _write_csv(pathway_dir / "gsea_results.csv", gsea)

    biomarkers = _attach_candidate_pathway_evidence(
        biomarkers,
        enrichment,
        key_drifted,
        libraries,
        morphology_summary,
    )
    _write_csv(run_directory / "biomarkers" / "candidate_profiles.csv", biomarkers)

    source_descriptions = {
        "GO": {
            "version": "GO basic ontology snapshot plus gene associations dated 2026-05-21",
            "organism_policy": "Separate taxon-filtered human and mouse GAF annotations; ancestor propagation uses is_a and part_of.",
            "source": "Gene Ontology Consortium",
        },
        "Reactome": {
            "version": "Reactome GMT export modified 2026-06-21",
            "organism_policy": "Human R-HSA pathways only; no mouse Reactome terms are reported.",
            "source": "Reactome",
        },
        "WikiPathways": {
            "version": "2026-09-10 species-specific GMT snapshots",
            "organism_policy": "Separate Homo sapiens and Mus musculus collections; Entrez IDs map locally to Ensembl.",
            "source": "WikiPathways",
        },
        "Ensembl": {
            "version": "Local whole-gene ID maps; BioMart release is not encoded in the downloaded tables.",
            "organism_policy": "Unique Entrez and symbol mappings only for source identifiers; Ensembl stable IDs remain species-specific.",
            "source": "Ensembl BioMart",
        },
    }
    reference_hashes = {
        name: _sha256_file(reference_dir / name)
        for name in required_reference_files
    }
    input_paths = (
        "deg/human/all_genes.csv",
        "deg/human/significant_genes.csv",
        "deg/mouse/cross_study_exploratory/all_genes.csv",
        "drift/gene_drift.csv",
        "orthology/orthologs.csv",
        "networks/human_cancer_nodes.csv",
        "networks/human_healthy/human_cancer_edges.csv",
        "networks/mouse_cancer_nodes.csv",
        "networks/mouse_cancer_edges.csv",
        "modules/human/module_genes.csv",
        "modules/mouse/module_genes.csv",
    )
    provenance = {
        "analysis": "Local offline over-representation, optional local preranked GSEA, and ortholog-mapped pathway network comparison",
        "reference_directory": str(reference_dir.relative_to(ROOT)).replace("\\", "/"),
        "reference_libraries": source_descriptions,
        "reference_sha256": reference_hashes,
        "input_artifact_sha256": {
            path: _sha256_file(run_directory / path)
            for path in input_paths
            if (run_directory / path).is_file()
        },
        "identifier_policy": (
            "No gene identifiers are uploaded. Gene sets and ID conversions are computed from local snapshots. "
            "Ambiguous source-symbol/Entrez mappings are excluded rather than guessed."
        ),
        "statistics": {
            "ora": "Hypergeometric upper-tail test with Benjamini-Hochberg correction over all tested pathways within species, gene set, and database; genes outside the annotated library are excluded from that database's universe.",
            "fdr_threshold": 0.05,
            "gsea": "Local gseapy prerank against in-memory local gene sets; 1000 permutations and seed 42 when enabled.",
        },
        "comparison": {
            "orthology": "Ensembl Compara one-to-one rows only",
            "module_preservation": "Maximum Jaccard similarity of ortholog-mapped within-pathway module membership.",
            "network_edge_drift": "1 - conserved mapped within-pathway edges / union of conserved, lost, and gained mapped edges; undefined for empty unions.",
            "key_pathway_rule": "At least one species has pathway ORA FDR <= 0.05 and the measurable within-pathway mapped edge divergence is greater than zero.",
        },
    }
    _write_json(pathway_dir / "provenance.json", provenance)

    significant_counts = {
        f"{species}:{database}": int(
            ((enrichment["species"] == species) & (enrichment["database"] == database)
             & (pd.to_numeric(enrichment["adjusted_p_value"], errors="coerce") <= 0.05)).sum()
        )
        for species in ("human", "mouse")
        for database in ("GO-BP", "GO-MF", "GO-CC", "Reactome", "WikiPathways")
    }
    stage_summary = {
        "status": "COMPLETED",
        "analysis_version": "phase5-pathway-local-2",
        "reference_status": "LOCAL_VERSIONED_SNAPSHOTS",
        "fdr_threshold": 0.05,
        "gene_set_count": int(gene_set_table[["species", "gene_set_key"]].drop_duplicates().shape[0]),
        "input_gene_count": int(gene_set_table["gene_id"].nunique()) if not gene_set_table.empty else 0,
        "ora_rows": len(enrichment),
        "significant_pathway_counts": significant_counts,
        "significant_pathway_count_unit": (
            "Significant pathway-by-gene-set rows; a pathway can be counted for multiple input gene sets."
        ),
        "comparison_rows": len(comparisons),
        "key_drifted_pathway_count": len(key_drifted),
        "gsea_status": "COMPLETED" if run_gsea else "NOT_RUN; invoke with --gsea to run local preranked analysis",
        "gsea_rows": len(gsea),
        "artifacts": [
            "pathways/gene_sets.csv",
            "pathways/enrichment_results.csv",
            "pathways/pathway_comparisons.csv",
            "pathways/key_drifted_pathways.csv",
            "pathways/gsea_results.csv",
            "pathways/provenance.json",
        ],
        "limitations": [
            "Mouse DEG results compare independent studies and remain exploratory, not matched human-mouse replication.",
            "Reactome results are human-only because no mouse Reactome set was acquired.",
            "Network-edge divergence is highly sensitive to the saved network density imbalance and is not proof of biological edge deletion.",
            "ORA gene universes are database-specific expressed Ensembl genes with an unambiguous local mapping.",
            "Pathway enrichment is hypothesis-generating and is not clinical validation.",
        ],
        "provenance": provenance,
    }
    _write_json(pathway_dir / "pathways_summary.json", stage_summary)
    return stage_summary, biomarkers, morphology_summary


def _attach_candidate_pathway_evidence(
    biomarkers: pd.DataFrame,
    enrichment: pd.DataFrame,
    key_drifted: pd.DataFrame,
    libraries: dict[str, list[Pathway]],
    morphology_summary: dict[str, Any],
    *,
    pathway_status: str = "AVAILABLE",
) -> pd.DataFrame:
    result = biomarkers.copy()
    for column in (
        "enriched_pathway_ids",
        "enriched_pathway_names",
        "key_drifted_pathway_ids",
        "key_drifted_pathway_names",
        "pathway_evidence_status",
        "morphology_association_status",
        "pathway_evidence",
        "morphology_evidence",
    ):
        result[column] = ""
    if result.empty or "gene_id" not in result:
        return result
    significant = enrichment.loc[
        enrichment["species"].eq("human")
        & enrichment["gene_set_key"].eq("significant_deg")
        & (pd.to_numeric(enrichment["adjusted_p_value"], errors="coerce") <= 0.05)
    ] if not enrichment.empty else pd.DataFrame()
    human_pathways = {
        (pathway.database, pathway.pathway_id): pathway
        for pathway in libraries.get("human", [])
    }
    significant_by_gene: dict[str, list[tuple[str, str]]] = {}
    for row in significant.itertuples(index=False):
        for gene_id in str(row.overlapping_gene_ids).split("|"):
            if gene_id:
                significant_by_gene.setdefault(gene_id, []).append((str(row.pathway_id), str(row.pathway_name)))
    drift_by_gene: dict[str, list[tuple[str, str]]] = {}
    if "human_gene_set_key" in key_drifted and not key_drifted.empty:
        for row in key_drifted.loc[key_drifted["human_gene_set_key"].eq("significant_deg")].itertuples(index=False):
            pathway = human_pathways.get((str(row.database), str(row.pathway_id)))
            if pathway:
                for gene_id in pathway.gene_ids:
                    drift_by_gene.setdefault(gene_id, []).append((str(row.pathway_id), str(row.pathway_name)))
    for index, row in result.iterrows():
        gene_id = str(row.get("gene_id", ""))
        enriched = sorted(set(significant_by_gene.get(gene_id, [])))
        drifted = sorted(set(drift_by_gene.get(gene_id, [])))
        result.at[index, "enriched_pathway_ids"] = "|".join(pathway_id for pathway_id, _ in enriched)
        result.at[index, "enriched_pathway_names"] = "|".join(name for _, name in enriched)
        result.at[index, "key_drifted_pathway_ids"] = "|".join(pathway_id for pathway_id, _ in drifted)
        result.at[index, "key_drifted_pathway_names"] = "|".join(name for _, name in drifted)
        result.at[index, "pathway_evidence_status"] = (
            "UNAVAILABLE" if pathway_status != "AVAILABLE"
            else "SIGNIFICANT_DEG_PATHWAY_OVERLAP" if enriched
            else "NO_SIGNIFICANT_DEG_PATHWAY_OVERLAP"
        )
        result.at[index, "pathway_evidence"] = (
            "; ".join(f"{name} ({pathway_id})" for pathway_id, name in enriched)
            if pathway_status == "AVAILABLE" and enriched
            else "No significant human DEG pathway overlap at FDR <= 0.05."
            if pathway_status == "AVAILABLE"
            else "Not calculated: local pathway references are unavailable."
        )
        result.at[index, "morphology_association_status"] = str(
            morphology_summary.get("gene_or_pathway_associations", "NOT_CALCULATED")
        )
        result.at[index, "morphology_evidence"] = (
            "Not calculated; available clinical pathology metadata is descriptive only, "
            "with no gene/pathway association tested."
        )
    return result


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_hub_gene_tables(run_directory: Path, output_directory: Path) -> dict[str, dict[str, int]]:
    network_artifacts = {
        "human_cancer": ("networks/human_cancer_nodes.csv", "networks/human_healthy/human_cancer_edges.csv"),
        "human_healthy": ("networks/human_healthy_nodes.csv", "networks/human_healthy/human_healthy_edges.csv"),
        "mouse_cancer": ("networks/mouse_cancer_nodes.csv", "networks/mouse_cancer_edges.csv"),
        "mouse_healthy": ("networks/mouse_healthy_nodes.csv", "networks/mouse_healthy_edges.csv"),
    }
    summaries = {}
    for network_name, (node_relative, edge_relative) in network_artifacts.items():
        node_path, edge_path = run_directory / node_relative, run_directory / edge_relative
        if not node_path.is_file():
            continue
        nodes = _read_csv(node_path)
        edges = _read_csv(edge_path) if edge_path.is_file() else None
        hub_metrics = compute_hub_metrics(nodes, edges).sort_values(
            "hub_score", ascending=False, na_position="last", ignore_index=True
        )
        _write_csv(output_directory / f"{network_name}_hub_metrics.csv", hub_metrics)
        assigned = hub_metrics.loc[hub_metrics["module_id"].notna()] if "module_id" in hub_metrics else hub_metrics.iloc[0:0]
        supported = assigned.loc[assigned["hub_supported"].eq(True)] if "hub_supported" in assigned else assigned.iloc[0:0]
        summaries[network_name] = {
            "genes": len(hub_metrics),
            "module_assigned_genes": len(assigned),
            "hub_supported_genes": len(supported),
            "modules": int(assigned["module_id"].nunique()) if "module_id" in assigned else 0,
        }
    _write_json(output_directory / "summary.json", {"networks": summaries})
    return summaries


def _biomarker_category_counts(biomarkers: pd.DataFrame) -> dict[str, int]:
    if biomarkers.empty or "evidence_categories" not in biomarkers:
        return {}
    counts: dict[str, int] = {}
    for categories in biomarkers["evidence_categories"]:
        if isinstance(categories, (list, tuple)):
            for category in categories:
                counts[str(category)] = counts.get(str(category), 0) + 1
    return counts


def _write_phase5_figures(run_directory: Path, scores: pd.DataFrame, biomarkers: pd.DataFrame) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    gene_loss_path = run_directory / "gene_loss" / "gene_loss_risk_distribution.png"
    figure, axis = plt.subplots(figsize=(8, 5))
    scored = pd.to_numeric(scores.get("risk_score"), errors="coerce").dropna() if "risk_score" in scores else pd.Series(dtype=float)
    if not scored.empty:
        axis.hist(scored, bins=20, color="#1976d2", edgecolor="white")
        axis.set_xlabel("Evidence-aware research priority score")
        axis.set_ylabel("Ortholog pairs")
        axis.set_title("Run-scoped gene-loss evidence scores")
    else:
        axis.text(0.5, 0.5, "No scored gene pairs", ha="center", va="center", transform=axis.transAxes)
        axis.set_axis_off()
    figure.tight_layout()
    figure.savefig(gene_loss_path, dpi=160)
    plt.close(figure)

    figure, axis = plt.subplots(figsize=(8, 5))
    lfc_column = next((name for name in ("log2fc", "log2FoldChange", "log2_fold_change") if name in biomarkers), None)
    fdr_column = next((name for name in ("adjusted_p_value", "padj", "fdr") if name in biomarkers), None)
    if lfc_column and fdr_column:
        lfc = pd.to_numeric(biomarkers[lfc_column], errors="coerce")
        fdr = pd.to_numeric(biomarkers[fdr_column], errors="coerce")
        valid = lfc.notna() & fdr.notna()
        if valid.any():
            y_values = -fdr.loc[valid].clip(lower=1e-300).map(math.log10)
            categories = biomarkers.loc[valid, "cross_species_drift_category"] if "cross_species_drift_category" in biomarkers else pd.Series(index=lfc.loc[valid].index, dtype=object)
            colors = categories.map({
                "HIGH_DRIFT": "#c62828",
                "MODERATE_DRIFT": "#ed6c02",
                "LOW_DRIFT": "#2e7d32",
            }).fillna("#78909c")
            axis.scatter(lfc.loc[valid], y_values, c=colors, s=10, alpha=0.65, linewidths=0)
            axis.set_xlabel("Human cancer vs healthy log2 fold change")
            axis.set_ylabel("-log10(adjusted p-value)")
            axis.set_title("Human significant DEG biomarker candidates")
            axis.axvline(0, color="#546e7a", linewidth=0.8, alpha=0.5)
        else:
            axis.text(0.5, 0.5, "No testable candidate statistics", ha="center", va="center", transform=axis.transAxes)
            axis.set_axis_off()
    else:
        axis.text(0.5, 0.5, "DEG statistics unavailable", ha="center", va="center", transform=axis.transAxes)
        axis.set_axis_off()
    figure.tight_layout()
    figure.savefig(run_directory / "biomarkers" / "candidate_volcano.png", dpi=160)
    plt.close(figure)


def _read_csv(path: Path) -> pd.DataFrame:
    try:
        return pd.read_csv(path, low_memory=False)
    except (OSError, UnicodeError, pd.errors.ParserError) as exc:
        logger.exception("Could not read Phase 5 input artifact %s", path)
        raise ValueError(f"Could not read required Phase 5 input artifact: {path.name}.") from exc


def _write_csv(path: Path, frame: pd.DataFrame) -> None:
    frame.to_csv(path, index=False, na_rep="")


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")
