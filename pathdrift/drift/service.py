from __future__ import annotations

import json
import logging
import subprocess
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..acquisition.registry import ROOT, json_safe, open_session
from ..cross_species.conservation import network_conservation_summary
from ..cross_species.edge_mapping import align_edges
from ..cross_species.module_mapping import align_modules
from ..cross_species.node_mapping import build_node_alignment
from ..cross_species.repository import load_cancer_networks
from ..orthology.ensembl import fetch_human_mouse_homologies
from ..orthology.mapping import primary_one_to_one
from ..orthology.repository import persist_orthology
from ..orthology.validation import validate_orthology
from .plots import write_drift_figures
from .repository import clear_phase4_results, persist_alignment, persist_drift, persist_summary
from .scoring import DEFAULT_THRESHOLDS, DEFAULT_WEIGHTS, compute_gene_drift
from .statistics import summarize_drift

logger = logging.getLogger("pathdrift.phase4")

DEFAULT_CONFIGURATION = {
    "primary_orthology": {
        "orthology_type": "ortholog_one2one",
        "min_confidence": 1.0,
        "rationale": "Direct node comparisons require a unique high-confidence human-mouse correspondence.",
    },
    "rewiring_threshold": {
        "absolute_signed_correlation_difference": 0.05,
        "rationale": "A shared mapped edge is labelled REWIRED when the absolute difference in signed correlations meets this threshold.",
    },
    "gene_drift_weights": {
        **DEFAULT_WEIGHTS,
        "rationale": {
            "edge_loss": "fraction of mapped human-neighbor relations absent from the mouse ortholog neighborhood",
            "neighbor_discordance": "one minus the Jaccard similarity of mapped human and mouse neighborhoods",
            "degree_difference": "absolute total-degree difference divided by the larger degree observed in either network",
        },
    },
    "gene_drift_thresholds": {
        **DEFAULT_THRESHOLDS,
        "rationale": "LOW_DRIFT is below moderate; MODERATE_DRIFT is moderate inclusive and below high; HIGH_DRIFT is high inclusive.",
    },
    "module_thresholds": {
        "conserved": 0.7,
        "partially_conserved": 0.3,
        "rationale": "Thresholds apply to Jaccard overlap of ortholog-mapped human module genes and candidate mouse module genes. More than one candidate sharing mapped genes is FRAGMENTED.",
    },
}


def run_phase4(run_id: str, *, stage: str = "phase4", force: bool = False) -> dict:
    if stage not in {"orthology", "cross-species", "drift", "phase4"}:
        raise ValueError(f"Unsupported Phase 4 stage: {stage}")
    manifest = _validate_run(run_id)
    output_root = ROOT / "results" / "runs" / run_id
    orthology_root = output_root / "orthology"
    cross_species_root = output_root / "cross_species"
    drift_root = output_root / "drift"
    session = open_session()
    try:
        from app.models import RunPhase4Summary

        previous = session.execute(
            select(RunPhase4Summary).where(RunPhase4Summary.run_id == run_id)
        ).scalar_one_or_none()
        completed_rank = {
            "ORTHOLOGY_COMPLETE": 1,
            "CROSS_SPECIES_COMPLETE": 2,
            "COMPLETED": 3,
        }
        required_rank = {"orthology": 1, "cross-species": 2, "drift": 3, "phase4": 3}[stage]
        if (
            not force
            and previous
            and completed_rank.get(previous.status, 0) >= required_rank
        ):
            return {"status": previous.status, "run_id": run_id, **previous.summary}
        if force or previous is not None:
            clear_phase4_results(session, run_id)

        networks = load_cancer_networks(session, run_id)
        human, mouse = networks["human"], networks["mouse"]
        session.commit()
        if (
            not force
            and previous
            and completed_rank.get(previous.status, 0) >= 1
        ):
            mappings, source_metadata = _load_cached_orthology(orthology_root)
        else:
            mappings, source_metadata = fetch_human_mouse_homologies()
        primary = primary_one_to_one(
            mappings,
            min_confidence=float(DEFAULT_CONFIGURATION["primary_orthology"]["min_confidence"]),
        )
        primary_ids = set(zip(primary["human_ensembl_id"], primary["mouse_ensembl_id"]))
        orthology_summary, unmapped_human, unmapped_mouse = validate_orthology(
            mappings,
            set(human["nodes"]["gene_id"].astype(str)),
            set(mouse["nodes"]["gene_id"].astype(str)),
            min_confidence=float(DEFAULT_CONFIGURATION["primary_orthology"]["min_confidence"]),
        )
        orthology_summary.update(source_metadata)
        _write_frame(mappings, orthology_root / "orthologs.csv")
        _write_frame(unmapped_human, orthology_root / "unmapped_human_genes.csv")
        _write_frame(unmapped_mouse, orthology_root / "unmapped_mouse_genes.csv")
        _write_json(orthology_root / "orthology_summary.json", orthology_summary)
        orthology_provenance = {
            **source_metadata,
            "source_metadata": source_metadata,
            "run_id": run_id,
            "network_ids": {"human": human["network"].id, "mouse": mouse["network"].id},
            "network_gene_counts": {
                "human": len(human["nodes"]),
                "mouse": len(mouse["nodes"]),
            },
            "primary_mapping_policy": DEFAULT_CONFIGURATION["primary_orthology"],
            "non_one_to_one_relationships_retained": True,
        }
        _write_json(orthology_root / "provenance.json", orthology_provenance)
        persist_orthology(session, run_id, mappings, source_metadata, primary_ids)
        if stage == "orthology":
            summary = {"orthology": orthology_summary}
            persist_summary(session, run_id, "ORTHOLOGY_COMPLETE", DEFAULT_CONFIGURATION, summary, orthology_provenance)
            session.commit()
            return {"status": "ORTHOLOGY_COMPLETE", "run_id": run_id, **summary}

        node_alignment = build_node_alignment(mappings, human["nodes"], mouse["nodes"])
        node_alignment = node_alignment.loc[
            node_alignment["human_network_present"] | node_alignment["mouse_network_present"]
        ].copy()
        edge_alignment = align_edges(
            human["edges"],
            mouse["edges"],
            primary,
            rewiring_threshold=float(
                DEFAULT_CONFIGURATION["rewiring_threshold"]["absolute_signed_correlation_difference"]
            ),
        )
        network_summary = network_conservation_summary(
            human["nodes"], mouse["nodes"], primary, edge_alignment
        )
        network_summary.update({
            "human_network": _network_metadata(human["network"]),
            "mouse_network": _network_metadata(mouse["network"]),
        })
        _write_frame(node_alignment, cross_species_root / "node_alignment.csv")
        _write_frame(edge_alignment, cross_species_root / "edge_alignment.csv")
        _write_json(cross_species_root / "network_conservation_summary.json", network_summary)
        cross_species_provenance = {
            **orthology_provenance,
            "human_network": _network_metadata(human["network"]),
            "mouse_network": _network_metadata(mouse["network"]),
            "edge_weight": "signed Pearson/Spearman correlation stored by Phase 3",
            "rewiring_threshold": DEFAULT_CONFIGURATION["rewiring_threshold"],
        }
        _write_json(cross_species_root / "provenance.json", cross_species_provenance)
        persist_alignment(session, run_id, node_alignment, edge_alignment)
        if stage == "cross-species":
            summary = {"orthology": orthology_summary, "cross_species": network_summary}
            persist_summary(session, run_id, "CROSS_SPECIES_COMPLETE", DEFAULT_CONFIGURATION, summary, cross_species_provenance)
            session.commit()
            return {"status": "CROSS_SPECIES_COMPLETE", "run_id": run_id, **summary}

        module_thresholds = DEFAULT_CONFIGURATION["module_thresholds"]
        module_alignment = align_modules(
            human["modules"], human["module_genes"],
            mouse["modules"], mouse["module_genes"],
            primary,
            conserved_threshold=float(module_thresholds["conserved"]),
            partial_threshold=float(module_thresholds["partially_conserved"]),
        )
        genes = compute_gene_drift(
            human["nodes"], mouse["nodes"],
            human["edges"], mouse["edges"],
            primary,
            weights={key: value for key, value in DEFAULT_CONFIGURATION["gene_drift_weights"].items() if key != "rationale"},
            thresholds={key: value for key, value in DEFAULT_CONFIGURATION["gene_drift_thresholds"].items() if key != "rationale"},
            module_alignment=module_alignment,
        )
        drift_summary = summarize_drift(edge_alignment, genes, module_alignment)
        _write_frame(genes, drift_root / "gene_drift.csv")
        _write_frame(edge_alignment, drift_root / "edge_drift.csv")
        _write_frame(module_alignment, drift_root / "module_drift.csv")
        _write_json(drift_root / "drift_summary.json", drift_summary)
        for status, filename in (
            ("CONSERVED", "conserved_edges.csv"),
            ("LOST", "lost_edges.csv"),
            ("GAINED", "gained_edges.csv"),
            ("REWIRED", "rewired_edges.csv"),
            ("UNMAPPABLE", "unmappable_edges.csv"),
        ):
            _write_frame(
                edge_alignment.loc[edge_alignment["status"] == status] if not edge_alignment.empty else edge_alignment,
                drift_root / filename,
            )
        figures = write_drift_figures(genes, edge_alignment, module_alignment, drift_root / "figures")
        warnings = _scientific_warnings(human["network"], mouse["network"], network_summary)
        overall_summary = {
            "run_id": run_id,
            "human_network": _network_metadata(human["network"]),
            "mouse_network": _network_metadata(mouse["network"]),
            "orthology": {
                "source": source_metadata["source"],
                "source_version": source_metadata["source_version"],
                "retrieved_at": source_metadata["retrieved_at"],
                "total_mappings": len(mappings),
                "primary_one_to_one_mappings": len(primary),
            },
            "mapped_nodes": network_summary["shared_network_nodes"],
            "unmapped_nodes": {
                "human": orthology_summary["unmapped_human_network_genes"],
                "mouse": orthology_summary["unmapped_mouse_network_genes"],
            },
            "conserved_edges": network_summary["conserved_edges"],
            "lost_edges": network_summary["lost_edges"],
            "gained_edges": network_summary["gained_edges"],
            "rewired_edges": network_summary["rewired_edges"],
            "unmappable_edges": network_summary["unmappable_edges"],
            "network_conservation_rate": network_summary["edge_conservation_rate"],
            "top_drifted_genes": drift_summary["top_drifted_genes"],
            "module_conservation_statistics": drift_summary["module_classification_counts"],
            "warnings": warnings,
            "limitations": [
                "Network drift describes topology differences, not gene absence or expression loss.",
                "A single Phase 3 network per species is compared; sample-size and network-density differences can affect edge counts.",
                "Phase 4 does not perform pathway enrichment or infer biomarker significance.",
                "No randomization-based significance is calculated in this phase.",
            ],
            "configuration": DEFAULT_CONFIGURATION,
            "figures": [Path(path).relative_to(output_root).as_posix() for path in figures],
        }
        _write_json(output_root / "cross_species_drift_summary.json", overall_summary)
        drift_provenance = {
            **cross_species_provenance,
            "configuration": DEFAULT_CONFIGURATION,
            "software_versions": _software_versions(),
            "git_commit": _git_commit(),
            "random_seed": None,
            "randomization_performed": False,
            "output_files": [
                "drift/gene_drift.csv",
                "drift/edge_drift.csv",
                "drift/module_drift.csv",
                "cross_species_drift_summary.json",
            ],
        }
        _write_json(drift_root / "provenance.json", drift_provenance)
        persist_drift(session, run_id, genes, module_alignment)
        persist_summary(
            session,
            run_id,
            "COMPLETED",
            DEFAULT_CONFIGURATION,
            {"orthology": orthology_summary, "cross_species": network_summary, "drift": drift_summary, **overall_summary},
            drift_provenance,
        )
        session.commit()
        return {"status": "COMPLETED", **overall_summary}
    except Exception:
        session.rollback()
        logger.exception("Phase 4 %s stage failed for run %s", stage, run_id)
        raise
    finally:
        session.close()


def _validate_run(run_id: str) -> dict:
    from app.services.filesystem_runs import read_result_run_manifest

    manifest = read_result_run_manifest(run_id)
    phase3 = manifest.get("phase3") if manifest else None
    if (
        manifest is None
        or str(manifest.get("status", "")).upper() != "COMPLETED"
        or not isinstance(phase3, dict)
        or str(phase3.get("status", "")).upper() != "COMPLETED"
    ):
        raise ValueError(f"Run {run_id} does not have a completed Phase 3 manifest.")
    return manifest


def _network_metadata(network) -> dict:
    config = network.configuration or {}
    return {
        "network_id": network.id,
        "name": network.name,
        "species": str(network.species),
        "disease_state": str(network.disease_state),
        "method": network.method,
        "configuration": config,
        "summary": network.summary or {},
    }


def _scientific_warnings(human_network, mouse_network, conservation: dict) -> list[str]:
    h_density = (human_network.summary or {}).get("density")
    m_density = (mouse_network.summary or {}).get("density")
    warnings = []
    if h_density is not None and m_density is not None:
        if max(float(h_density), float(m_density)) > 5 * max(min(float(h_density), float(m_density)), 1e-12):
            warnings.append(
                "Human and mouse network densities differ by more than five-fold; edge conservation and drift rates are density-sensitive."
            )
    warnings.append(
        "Phase 3 reports its observed correlation and FDR thresholds per network; edge absence reflects those construction thresholds and available samples."
    )
    if conservation["unmappable_edges"]:
        warnings.append("Edges with endpoints lacking primary one-to-one orthology are UNMAPPABLE, not lost.")
    return warnings


def _software_versions() -> dict[str, str | None]:
    versions = {}
    for package in ("pathdrift", "pandas", "numpy", "sqlalchemy", "matplotlib"):
        try:
            versions[package] = version(package)
        except PackageNotFoundError:
            versions[package] = None
    return versions


def _git_commit() -> str | None:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None


def _write_frame(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)


def _load_cached_orthology(root: Path) -> tuple[pd.DataFrame, dict]:
    from ..orthology.mapping import normalize_mapping

    csv_path = root / "orthologs.csv"
    provenance_path = root / "provenance.json"
    if not csv_path.is_file() or not provenance_path.is_file():
        raise ValueError(
            "A previous Phase 4 orthology stage is marked complete but its validated source artifacts are missing; rerun with --force."
        )
    try:
        provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
        metadata = provenance["source_metadata"]
        frame = pd.read_csv(csv_path)
    except (OSError, json.JSONDecodeError, KeyError, ValueError) as error:
        raise ValueError("Saved Ensembl orthology stage artifacts are incomplete or invalid.") from error
    required_metadata = {"source", "source_version", "retrieved_at", "ensembl_release"}
    if not required_metadata.issubset(metadata):
        raise ValueError("Saved Ensembl orthology provenance is missing source/version/retrieval metadata.")
    frame = normalize_mapping(frame)
    if not frame["orthology_type"].str.startswith("ortholog_").all():
        raise ValueError("Saved orthology artifact contains an unsupported relationship type.")
    frame["confidence"] = pd.to_numeric(frame.get("confidence"), errors="coerce")
    frame["source"] = metadata["source"]
    frame["source_version"] = metadata["source_version"]
    return frame, metadata


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(json_safe(value), indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
