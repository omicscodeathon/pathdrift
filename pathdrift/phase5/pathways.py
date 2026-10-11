from __future__ import annotations

import gzip
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import hypergeom
from statsmodels.stats.multitest import multipletests


ORA_COLUMNS = [
    "species", "gene_set_key", "gene_set_label", "database", "pathway_id",
    "pathway_name", "method", "input_gene_count", "background_gene_count",
    "pathway_gene_count", "overlap_gene_count", "overlapping_gene_ids",
    "overlapping_gene_symbols", "enrichment_ratio", "p_value", "adjusted_p_value",
    "fdr_threshold", "source_version",
]
COMPARISON_COLUMNS = [
    "human_gene_set_key", "mouse_gene_set_key", "network_state", "database",
    "pathway_id", "pathway_name", "pathway_presence", "human_fdr", "mouse_fdr",
    "human_pathway_gene_count", "mouse_pathway_gene_count", "conserved_ortholog_count",
    "human_unpaired_pathway_member_count", "mouse_unpaired_pathway_member_count",
    "conserved_edge_count",
    "lost_edge_count", "gained_edge_count", "mapped_edge_union_count",
    "pathway_drift_score", "pathway_drift_score_method", "gene_membership_drift_score",
    "human_mean_degree", "mouse_mean_degree", "module_preservation_jaccard",
    "best_matching_module_pair", "key_drifted_pathway", "ranking_reason",
    "network_density_limitation",
]


@dataclass(frozen=True)
class Pathway:
    species: str
    database: str
    pathway_id: str
    name: str
    gene_ids: frozenset[str]
    source_version: str


def _text(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value).strip()


def _truthy(values: pd.Series) -> pd.Series:
    return values.astype("string").str.lower().isin({"true", "1", "yes"})


def load_gene_identifier_maps(reference_dir: Path) -> dict[str, dict[str, dict[str, str]]]:
    maps: dict[str, dict[str, dict[str, str]]] = {}
    for species, file_name in (
        ("human", "ensembl_human_gene_ids.tsv"),
        ("mouse", "ensembl_mouse_gene_ids.tsv"),
    ):
        path = reference_dir / file_name
        frame = pd.read_csv(path, sep="\t", dtype=str, keep_default_na=False)
        required = {"Gene stable ID", "Gene name", "NCBI gene (formerly Entrezgene) ID"}
        if not required.issubset(frame.columns):
            raise ValueError(f"Ensembl identifier map has an unexpected schema: {file_name}.")
        rows: dict[str, dict[str, str]] = {}
        for row in frame.to_dict(orient="records"):
            gene_id = _text(row.get("Gene stable ID"))
            if not gene_id:
                continue
            rows[gene_id] = {
                "symbol": _text(row.get("Gene name")),
                "entrez_id": _text(row.get("NCBI gene (formerly Entrezgene) ID")),
            }
        maps[species] = rows
    return maps


def _go_ontology(path: Path) -> tuple[dict[str, tuple[str, str]], dict[str, set[str]]]:
    terms: dict[str, tuple[str, str]] = {}
    parents: dict[str, set[str]] = {}
    current: dict[str, Any] | None = None
    with path.open("r", encoding="utf-8") as source:
        for raw_line in source:
            line = raw_line.rstrip("\n")
            if line == "[Term]":
                if current and current.get("id") and current.get("name") and current.get("namespace") and not current.get("obsolete"):
                    term_id = str(current["id"])
                    terms[term_id] = (str(current["name"]), str(current["namespace"]))
                    parents[term_id] = set(current.get("parents", set()))
                current = {"parents": set()}
            elif line.startswith("["):
                if current and current.get("id") and current.get("name") and current.get("namespace") and not current.get("obsolete"):
                    term_id = str(current["id"])
                    terms[term_id] = (str(current["name"]), str(current["namespace"]))
                    parents[term_id] = set(current.get("parents", set()))
                current = None
            elif current is not None:
                if line.startswith("id: "):
                    current["id"] = line[4:]
                elif line.startswith("name: "):
                    current["name"] = line[6:]
                elif line.startswith("namespace: "):
                    current["namespace"] = line[11:]
                elif line == "is_obsolete: true":
                    current["obsolete"] = True
                elif line.startswith("is_a: "):
                    current["parents"].add(line[6:].split(" ! ", 1)[0])
                elif line.startswith("relationship: part_of "):
                    current["parents"].add(line.split()[2])
    if current and current.get("id") and current.get("name") and current.get("namespace") and not current.get("obsolete"):
        term_id = str(current["id"])
        terms[term_id] = (str(current["name"]), str(current["namespace"]))
        parents[term_id] = set(current.get("parents", set()))
    return terms, parents


def _go_ancestors(term_id: str, parents: dict[str, set[str]], cache: dict[str, set[str]]) -> set[str]:
    if term_id in cache:
        return cache[term_id]
    found: set[str] = set()
    pending = list(parents.get(term_id, set()))
    while pending:
        parent = pending.pop()
        if parent not in found:
            found.add(parent)
            pending.extend(parents.get(parent, set()) - found)
    cache[term_id] = found
    return found


def _unique_symbol_to_id(gene_map: dict[str, dict[str, str]]) -> dict[str, str]:
    symbol_to_ids: dict[str, set[str]] = {}
    for gene_id, details in gene_map.items():
        symbol = details["symbol"].casefold()
        if symbol:
            symbol_to_ids.setdefault(symbol, set()).add(gene_id)
    return {
        symbol: next(iter(gene_ids))
        for symbol, gene_ids in symbol_to_ids.items()
        if len(gene_ids) == 1
    }


def _unique_entrez_to_id(gene_map: dict[str, dict[str, str]]) -> dict[str, str]:
    entrez_to_ids: dict[str, set[str]] = {}
    for gene_id, details in gene_map.items():
        entrez_id = details["entrez_id"]
        if entrez_id:
            entrez_to_ids.setdefault(entrez_id, set()).add(gene_id)
    return {
        entrez_id: next(iter(gene_ids))
        for entrez_id, gene_ids in entrez_to_ids.items()
        if len(gene_ids) == 1
    }


def _go_pathways(
    species: str,
    gaf_path: Path,
    terms: dict[str, tuple[str, str]],
    parents: dict[str, set[str]],
    gene_map: dict[str, dict[str, str]],
    source_version: str,
) -> list[Pathway]:
    symbol_to_id = _unique_symbol_to_id(gene_map)
    annotations: dict[str, set[str]] = {}
    ancestors_cache: dict[str, set[str]] = {}
    expected_taxon = "9606" if species == "human" else "10090"
    with gzip.open(gaf_path, "rt", encoding="utf-8", errors="replace") as source:
        for line in source:
            if line.startswith("!") or not line.strip():
                continue
            fields = line.rstrip("\n").split("\t")
            if len(fields) < 13 or f"taxon:{expected_taxon}" not in fields[12].split("|"):
                continue
            if "NOT" in fields[3].split("|") or fields[6] == "ND":
                continue
            gene_id = symbol_to_id.get(fields[2].strip().casefold())
            term_id = fields[4].strip()
            if gene_id and term_id in terms:
                annotations.setdefault(term_id, set()).add(gene_id)
                for parent_id in _go_ancestors(term_id, parents, ancestors_cache):
                    if parent_id in terms:
                        annotations.setdefault(parent_id, set()).add(gene_id)
    prefix = {"biological_process": "GO-BP", "molecular_function": "GO-MF", "cellular_component": "GO-CC"}
    return [
        Pathway(species, prefix[terms[term_id][1]], term_id, terms[term_id][0],
                frozenset(gene_ids), source_version)
        for term_id, gene_ids in annotations.items()
        if term_id in terms and terms[term_id][1] in prefix
    ]


def _reactome_pathways(reference_dir: Path, gene_map: dict[str, dict[str, str]]) -> list[Pathway]:
    symbol_to_id = _unique_symbol_to_id(gene_map)
    archive = reference_dir / "ReactomePathways.gmt.zip"
    pathways: list[Pathway] = []
    with zipfile.ZipFile(archive) as source:
        members = [name for name in source.namelist() if name.endswith(".gmt")]
        if not members:
            raise ValueError("Reactome archive does not contain a GMT file.")
        with source.open(members[0]) as gmt:
            for raw_line in gmt:
                fields = raw_line.decode("utf-8").rstrip("\n").split("\t")
                if len(fields) < 3:
                    continue
                name, pathway_id = fields[0], fields[1]
                if not pathway_id.startswith("R-HSA-"):
                    continue
                gene_ids = frozenset(
                    symbol_to_id[symbol.casefold()]
                    for symbol in fields[2:]
                    if symbol.casefold() in symbol_to_id
                )
                if gene_ids:
                    pathways.append(Pathway("human", "Reactome", pathway_id, name, gene_ids, "Reactome current export 2026-06-21"))
    return pathways


def _wikipathways(
    reference_dir: Path,
    species: str,
    gene_map: dict[str, dict[str, str]],
) -> list[Pathway]:
    scientific_name = "Homo_sapiens" if species == "human" else "Mus_musculus"
    source_path = reference_dir / f"wikipathways-20260910-gmt-{scientific_name}.gmt"
    entrez_to_id = _unique_entrez_to_id(gene_map)
    pathways: list[Pathway] = []
    with source_path.open("r", encoding="utf-8") as source:
        for line in source:
            fields = line.rstrip("\n").split("\t")
            if len(fields) < 3:
                continue
            metadata = fields[0].split("%")
            if len(metadata) < 4 or metadata[3] != ("Homo sapiens" if species == "human" else "Mus musculus"):
                continue
            gene_ids = frozenset(entrez_to_id[entrez] for entrez in fields[2:] if entrez in entrez_to_id)
            if gene_ids:
                pathways.append(Pathway(
                    species, "WikiPathways", metadata[2], metadata[0], gene_ids,
                    f"WikiPathways {metadata[1].removeprefix('WikiPathways_')}",
                ))
    return pathways


def load_pathway_libraries(
    reference_dir: Path,
    gene_maps: dict[str, dict[str, dict[str, str]]],
) -> dict[str, list[Pathway]]:
    ontology_path = reference_dir / "go-basic.obo"
    gaf_paths = {
        "human": reference_dir / "goa_human.gaf.gz",
        "mouse": reference_dir / "goa_mouse.gaf.gz",
    }
    required = [ontology_path, *gaf_paths.values(), reference_dir / "ReactomePathways.gmt.zip"]
    required += [
        reference_dir / "wikipathways-20260910-gmt-Homo_sapiens.gmt",
        reference_dir / "wikipathways-20260910-gmt-Mus_musculus.gmt",
    ]
    missing = [path.name for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"Versioned pathway reference files are missing: {', '.join(missing)}.")
    terms, parents = _go_ontology(ontology_path)
    libraries: dict[str, list[Pathway]] = {"human": [], "mouse": []}
    for species in ("human", "mouse"):
        libraries[species].extend(_go_pathways(
            species, gaf_paths[species], terms, parents, gene_maps[species], "GO annotations 2026-05-21",
        ))
        libraries[species].extend(_wikipathways(reference_dir, species, gene_maps[species]))
    libraries["human"].extend(_reactome_pathways(reference_dir, gene_maps["human"]))
    return libraries


def build_pathway_gene_sets(
    run_directory: Path,
    gene_maps: dict[str, dict[str, dict[str, str]]],
    *,
    fdr_threshold: float = 0.05,
) -> tuple[pd.DataFrame, dict[tuple[str, str], set[str]]]:
    sets: dict[tuple[str, str], set[str]] = {}
    rows: list[dict[str, str]] = []
    symbols_by_id = {
        species: {gene_id: details["symbol"] for gene_id, details in mapping.items()}
        for species, mapping in gene_maps.items()
    }

    def add_set(species: str, key: str, label: str, values: Any, source: str) -> None:
        if isinstance(values, pd.DataFrame):
            identifiers = values.get("gene_id", pd.Series(dtype=str)).dropna().astype(str)
        else:
            identifiers = pd.Series(list(values), dtype=str)
        unique_ids = {gene_id.strip() for gene_id in identifiers if gene_id.strip()}
        sets[(species, key)] = unique_ids
        for gene_id in sorted(unique_ids):
            rows.append({
                "species": species,
                "gene_set_key": key,
                "gene_set_label": label,
                "gene_id": gene_id,
                "gene_symbol": symbols_by_id[species].get(gene_id, ""),
                "source_artifact": source,
            })

    human_all = pd.read_csv(run_directory / "deg/human/all_genes.csv", dtype=str, keep_default_na=False)
    mouse_all = pd.read_csv(run_directory / "deg/mouse/cross_study_exploratory/all_genes.csv", dtype=str, keep_default_na=False)
    for species, frame, artifact in (
        ("human", human_all, "deg/human/all_genes.csv"),
        ("mouse", mouse_all, "deg/mouse/cross_study_exploratory/all_genes.csv"),
    ):
        if "gene_id" not in frame:
            raise ValueError(f"{artifact} does not contain gene_id.")
        significant = _truthy(frame["significant"]) if "significant" in frame else pd.Series(False, index=frame.index)
        sig = frame.loc[significant]
        add_set(species, "significant_deg", "Significant DEGs", sig, artifact)
        direction = frame.get("direction", pd.Series("", index=frame.index)).str.upper()
        add_set(species, "upregulated_deg", "Upregulated DEGs", frame.loc[significant & direction.eq("UPREGULATED")], artifact)
        add_set(species, "downregulated_deg", "Downregulated DEGs", frame.loc[significant & direction.eq("DOWNREGULATED")], artifact)

    for species, networks in (
        ("human", ("human_cancer", "human_healthy")),
        ("mouse", ("mouse_cancer", "mouse_healthy")),
    ):
        for network_name in networks:
            path = run_directory / "hub_genes" / f"{network_name}_hub_metrics.csv"
            if path.is_file():
                hubs = pd.read_csv(path, dtype=str, keep_default_na=False)
                if {"gene_id", "hub_supported"}.issubset(hubs.columns):
                    hub_ids = hubs.loc[_truthy(hubs["hub_supported"])]
                else:
                    hub_ids = hubs.iloc[0:0]
                add_set(species, f"hub_{network_name}", f"Hub genes · {network_name.replace('_', ' ')}", hub_ids, str(path.relative_to(run_directory)))

    for species in ("human", "mouse"):
        module_path = run_directory / "modules" / species / "module_genes.csv"
        if module_path.is_file():
            modules = pd.read_csv(module_path, dtype=str, keep_default_na=False)
            if {"module_id", "gene_id"}.issubset(modules.columns):
                for module_id, frame in modules.groupby("module_id", sort=True):
                    key = f"module_{module_id}"
                    add_set(species, key, f"{species.title()} module {module_id}", frame, str(module_path.relative_to(run_directory)))

    drift_path = run_directory / "drift/gene_drift.csv"
    drift = pd.read_csv(drift_path, dtype=str, keep_default_na=False)
    drift_category = drift.get("drift_category", pd.Series("", index=drift.index)).str.upper()
    drifted = drift.loc[~drift_category.isin({"", "LOW_DRIFT", "LOW"})]
    add_set("human", "drifted_genes", "Drifted genes", drifted.rename(columns={"human_ensembl_id": "gene_id"}), "drift/gene_drift.csv")
    add_set("mouse", "drifted_genes", "Drifted genes", drifted.rename(columns={"mouse_ensembl_id": "gene_id"}), "drift/gene_drift.csv")
    for species, column in (("human", "human_ensembl_id"), ("mouse", "mouse_ensembl_id")):
        lost = pd.to_numeric(drift.get("lost_neighbor_count", pd.Series(0, index=drift.index)), errors="coerce").fillna(0).gt(0)
        gained = pd.to_numeric(drift.get("gained_neighbor_count", pd.Series(0, index=drift.index)), errors="coerce").fillna(0).gt(0)
        add_set(species, "interaction_loss_genes", "Genes with lost mapped interactions", drift.loc[lost].rename(columns={column: "gene_id"}), "drift/gene_drift.csv")
        add_set(species, "interaction_gain_genes", "Genes with gained mapped interactions", drift.loc[gained].rename(columns={column: "gene_id"}), "drift/gene_drift.csv")

    biomarker_path = run_directory / "biomarkers/candidate_biomarkers.csv"
    if biomarker_path.is_file():
        biomarkers = pd.read_csv(biomarker_path, dtype=str, keep_default_na=False)
        add_set("human", "candidate_biomarkers", "Candidate biomarkers", biomarkers, "biomarkers/candidate_biomarkers.csv")
    return pd.DataFrame(rows, columns=[
        "species", "gene_set_key", "gene_set_label", "gene_id", "gene_symbol", "source_artifact",
    ]), sets


def run_over_representation(
    gene_sets: dict[tuple[str, str], set[str]],
    libraries: dict[str, list[Pathway]],
    gene_maps: dict[str, dict[str, dict[str, str]]],
    expressed_universes: dict[str, set[str]],
    *,
    fdr_threshold: float = 0.05,
) -> pd.DataFrame:
    if not 0 < fdr_threshold <= 1:
        raise ValueError("FDR threshold must be in (0, 1].")
    records: list[dict[str, Any]] = []
    for species, pathways in libraries.items():
        if not pathways:
            continue
        expressed_ids = expressed_universes.get(species, set())
        library_universe = set().union(*(pathway.gene_ids for pathway in pathways)) & expressed_ids
        symbols = {gene_id: details["symbol"] for gene_id, details in gene_maps[species].items()}
        group_keys = sorted(key for key in gene_sets if key[0] == species)
        grouped: dict[str, list[Pathway]] = {}
        for pathway in pathways:
            grouped.setdefault(pathway.database, []).append(pathway)
        for _, gene_set_key in group_keys:
            input_ids = gene_sets[(species, gene_set_key)] & library_universe
            for database, db_pathways in grouped.items():
                relevant_pathways = [pathway for pathway in db_pathways if pathway.gene_ids & library_universe]
                universe = set().union(*(pathway.gene_ids for pathway in relevant_pathways)) & library_universe
                genes = input_ids & universe
                n = len(genes)
                N = len(universe)
                pathway_members = [set(pathway.gene_ids) & universe for pathway in relevant_pathways]
                overlaps = [genes & members for members in pathway_members]
                pathway_sizes = np.fromiter((len(members) for members in pathway_members), dtype=np.int64)
                overlap_sizes = np.fromiter((len(overlap) for overlap in overlaps), dtype=np.int64)
                if n and N:
                    p_values = np.asarray(
                        hypergeom.sf(overlap_sizes - 1, N, pathway_sizes, n),
                        dtype=float,
                    )
                else:
                    p_values = np.ones(len(relevant_pathways), dtype=float)
                pending: list[dict[str, Any]] = []
                for index, pathway in enumerate(relevant_pathways):
                    K = int(pathway_sizes[index])
                    overlap = overlaps[index]
                    k = int(overlap_sizes[index])
                    p_value = float(p_values[index])
                    ratio = ((k / n) / (K / N)) if n and K and N else 0.0
                    record = {
                        "species": species,
                        "gene_set_key": gene_set_key,
                        "gene_set_label": _gene_set_label(gene_sets, species, gene_set_key),
                        "database": database,
                        "pathway_id": pathway.pathway_id,
                        "pathway_name": pathway.name,
                        "method": "Hypergeometric over-representation; Benjamini-Hochberg within species, gene set, and database",
                        "input_gene_count": n,
                        "background_gene_count": N,
                        "pathway_gene_count": K,
                        "overlap_gene_count": k,
                        "overlapping_gene_ids": "|".join(sorted(overlap)),
                        "overlapping_gene_symbols": "|".join(sorted({symbols.get(gene_id, "") for gene_id in overlap if symbols.get(gene_id)})),
                        "enrichment_ratio": ratio,
                        "p_value": p_value,
                        "fdr_threshold": fdr_threshold,
                        "source_version": pathway.source_version,
                    }
                    pending.append(record)
                adjusted = multipletests(p_values, method="fdr_bh")[1] if len(p_values) else []
                for record, padj in zip(pending, adjusted):
                    record["adjusted_p_value"] = float(padj)
                    if record["overlap_gene_count"] > 0:
                        records.append(record)
    return pd.DataFrame(records, columns=ORA_COLUMNS)


def _gene_set_label(gene_sets: dict[tuple[str, str], set[str]], species: str, key: str) -> str:
    del gene_sets
    if key == "significant_deg":
        return "Significant DEGs"
    if key == "upregulated_deg":
        return "Upregulated DEGs"
    if key == "downregulated_deg":
        return "Downregulated DEGs"
    if key == "drifted_genes":
        return "Drifted genes"
    if key == "interaction_loss_genes":
        return "Genes with lost mapped interactions"
    if key == "interaction_gain_genes":
        return "Genes with gained mapped interactions"
    if key == "candidate_biomarkers":
        return "Candidate biomarkers"
    if key.startswith("hub_"):
        return f"Hub genes · {key[4:].replace('_', ' ')}"
    if key.startswith("module_"):
        return f"{species.title()} module {key[7:]}"
    return key


def _edge_index(frame: pd.DataFrame | None) -> dict[str, set[str]]:
    adjacency: dict[str, set[str]] = {}
    if frame is None or not {"source_gene", "target_gene"}.issubset(frame.columns):
        return adjacency
    for source, target in frame[["source_gene", "target_gene"]].dropna().astype(str).itertuples(index=False, name=None):
        if source != target:
            adjacency.setdefault(source, set()).add(target)
            adjacency.setdefault(target, set()).add(source)
    return adjacency


def _edge_set(adjacency: dict[str, set[str]], members: set[str]) -> set[tuple[str, str]]:
    edges: set[tuple[str, str]] = set()
    for source in members:
        for target in adjacency.get(source, set()):
            if target in members and source < target:
                edges.add((source, target))
    return edges


def _mean_metric(nodes: pd.DataFrame | None, members: set[str], column: str) -> float | None:
    if nodes is None or "gene_id" not in nodes or column not in nodes:
        return None
    values = pd.to_numeric(nodes.loc[nodes["gene_id"].astype(str).isin(members), column], errors="coerce").dropna()
    return float(values.mean()) if not values.empty else None


def _module_overlap(
    human_members: set[str],
    mouse_members: set[str],
    orthologs: dict[str, str],
    human_modules: dict[str, set[str]],
    mouse_modules: dict[str, set[str]],
) -> tuple[float | None, str]:
    pairs: list[tuple[float, str]] = []
    mouse_pathway_groups = {
        module_id: members & mouse_members
        for module_id, members in mouse_modules.items()
        if members & mouse_members
    }
    for human_module, human_group in human_modules.items():
        human_pathway_group = human_group & human_members
        if not human_pathway_group:
            continue
        mapped = {
            orthologs[gene_id]
            for gene_id in human_pathway_group
            if gene_id in orthologs
        } & mouse_members
        if not mapped:
            continue
        for mouse_module, mouse_group in mouse_pathway_groups.items():
            union = mapped | mouse_group
            if union:
                pairs.append((len(mapped & mouse_group) / len(union), f"{human_module}:{mouse_module}"))
    if not pairs:
        return None, ""
    score, pair = max(pairs, key=lambda item: (item[0], item[1]))
    return score, pair


def _module_groups(frame: pd.DataFrame | None, network_name: str) -> dict[str, set[str]]:
    if frame is None or not {"gene_id", "module_id"}.issubset(frame.columns):
        return {}
    selected = frame
    if "network_name" in frame.columns:
        selected = frame.loc[frame["network_name"].astype(str).eq(network_name)]
    return {
        str(module_id): set(group["gene_id"].dropna().astype(str))
        for module_id, group in selected.groupby("module_id", sort=True)
        if str(module_id).strip()
    }


def compare_pathways(
    enrichment: pd.DataFrame,
    libraries: dict[str, list[Pathway]],
    orthology_frame: pd.DataFrame,
    network_edges: dict[str, pd.DataFrame | None],
    network_nodes: dict[str, pd.DataFrame | None],
    modules: dict[str, pd.DataFrame | None],
    *,
    fdr_threshold: float = 0.05,
) -> pd.DataFrame:
    if enrichment.empty or not {"human_ensembl_id", "mouse_ensembl_id"}.issubset(orthology_frame.columns):
        return pd.DataFrame(columns=COMPARISON_COLUMNS)
    orthologs = {
        str(row.human_ensembl_id): str(row.mouse_ensembl_id)
        for row in orthology_frame.itertuples(index=False)
        if _text(getattr(row, "orthology_type", "")) == "ortholog_one2one"
        and _text(row.human_ensembl_id) and _text(row.mouse_ensembl_id)
    }
    pathways = {
        species: {
            (pathway.database, pathway.pathway_id): pathway
            for pathway in species_pathways
        }
        for species, species_pathways in libraries.items()
    }
    edge_indices = {name: _edge_index(frame) for name, frame in network_edges.items()}
    module_indices = {
        name: _module_groups(modules.get(name.split("_", 1)[0]), name)
        for name in ("human_cancer", "human_healthy", "mouse_cancer", "mouse_healthy")
    }
    comparable_sets = (
        ("significant_deg", "significant_deg", "cancer"),
        ("upregulated_deg", "upregulated_deg", "cancer"),
        ("downregulated_deg", "downregulated_deg", "cancer"),
        ("hub_human_cancer", "hub_mouse_cancer", "cancer"),
        ("hub_human_healthy", "hub_mouse_healthy", "healthy"),
        ("drifted_genes", "drifted_genes", "cancer"),
        ("interaction_loss_genes", "interaction_loss_genes", "cancer"),
        ("interaction_gain_genes", "interaction_gain_genes", "cancer"),
    )
    rows: list[dict[str, Any]] = []
    for human_set_key, mouse_set_key, network_state in comparable_sets:
        human_rows = enrichment.loc[
            enrichment["species"].eq("human") & enrichment["gene_set_key"].eq(human_set_key)
        ]
        mouse_rows = enrichment.loc[
            enrichment["species"].eq("mouse") & enrichment["gene_set_key"].eq(mouse_set_key)
        ]
        human_rows = human_rows.loc[pd.to_numeric(human_rows["adjusted_p_value"], errors="coerce") <= fdr_threshold]
        mouse_rows = mouse_rows.loc[pd.to_numeric(mouse_rows["adjusted_p_value"], errors="coerce") <= fdr_threshold]
        if human_rows.empty and mouse_rows.empty:
            continue
        human_by_term = {(row.database, row.pathway_id): row for row in human_rows.itertuples(index=False)}
        mouse_by_term = {(row.database, row.pathway_id): row for row in mouse_rows.itertuples(index=False)}
        term_keys = set(human_by_term) | set(mouse_by_term)
        human_network_name = f"human_{network_state}"
        mouse_network_name = f"mouse_{network_state}"
        for database, pathway_id in sorted(term_keys):
            human_enrichment = human_by_term.get((database, pathway_id))
            mouse_enrichment = mouse_by_term.get((database, pathway_id))
            human_pathway = pathways.get("human", {}).get((database, pathway_id))
            mouse_pathway = pathways.get("mouse", {}).get((database, pathway_id))
            if human_pathway is None or mouse_pathway is None:
                continue
            human_members, mouse_members = set(human_pathway.gene_ids), set(mouse_pathway.gene_ids)
            conserved_pairs = sorted(
                (human_gene, orthologs[human_gene])
                for human_gene in human_members
                if human_gene in orthologs and orthologs[human_gene] in mouse_members
            )
            conserved_human = {pair[0] for pair in conserved_pairs}
            conserved_mouse = {pair[1] for pair in conserved_pairs}
            human_unpaired = human_members - conserved_human
            mouse_unpaired = mouse_members - conserved_mouse
            mapped_h_edges = {
                tuple(sorted((orthologs[left], orthologs[right])))
                for left, right in _edge_set(edge_indices.get(human_network_name, {}), human_members)
                if left in orthologs and right in orthologs
            }
            mouse_edges = _edge_set(edge_indices.get(mouse_network_name, {}), mouse_members)
            conserved_edges = mapped_h_edges & mouse_edges
            lost_edges = mapped_h_edges - mouse_edges
            gained_edges = mouse_edges - mapped_h_edges
            edge_union = len(conserved_edges | lost_edges | gained_edges)
            edge_drift = (len(lost_edges) + len(gained_edges)) / edge_union if edge_union else None
            gene_denominator = len(human_members) + len(mouse_members)
            gene_drift = 1 - (2 * len(conserved_pairs) / gene_denominator) if gene_denominator else None
            module_score, module_pair = _module_overlap(
                human_members, mouse_members, orthologs,
                module_indices[human_network_name], module_indices[mouse_network_name],
            )
            h_fdr = getattr(human_enrichment, "adjusted_p_value", None)
            m_fdr = getattr(mouse_enrichment, "adjusted_p_value", None)
            h_fdr = float(h_fdr) if h_fdr is not None and not pd.isna(h_fdr) else None
            m_fdr = float(m_fdr) if m_fdr is not None and not pd.isna(m_fdr) else None
            h_sig, m_sig = h_fdr is not None and h_fdr <= fdr_threshold, m_fdr is not None and m_fdr <= fdr_threshold
            pathway_presence = "both" if h_sig and m_sig else "human_only" if h_sig else "mouse_only" if m_sig else "neither"
            key_supported = bool((h_sig or m_sig) and edge_drift is not None and edge_drift > 0)
            pathway_name = human_pathway.name or mouse_pathway.name
            reason = (
                f"Within-pathway ortholog-mapped edge divergence {edge_drift:.4f} "
                f"({len(lost_edges)} lost, {len(gained_edges)} gained, {len(conserved_edges)} conserved); "
                f"human FDR={h_fdr}, mouse FDR={m_fdr}."
            ) if edge_drift is not None else "No mapped within-pathway network edge union was available."
            rows.append({
                "human_gene_set_key": human_set_key,
                "mouse_gene_set_key": mouse_set_key,
                "network_state": network_state,
                "database": database,
                "pathway_id": pathway_id,
                "pathway_name": pathway_name,
                "pathway_presence": pathway_presence,
                "human_fdr": h_fdr,
                "mouse_fdr": m_fdr,
                "human_pathway_gene_count": len(human_members),
                "mouse_pathway_gene_count": len(mouse_members),
                "conserved_ortholog_count": len(conserved_pairs),
                "human_unpaired_pathway_member_count": len(human_unpaired),
                "mouse_unpaired_pathway_member_count": len(mouse_unpaired),
                "conserved_edge_count": len(conserved_edges),
                "lost_edge_count": len(lost_edges),
                "gained_edge_count": len(gained_edges),
                "mapped_edge_union_count": edge_union,
                "pathway_drift_score": edge_drift,
                "pathway_drift_score_method": "1 - conserved ortholog-mapped within-pathway edges / union of conserved, lost, and gained within-pathway edges; undefined when the union is empty.",
                "gene_membership_drift_score": gene_drift,
                "human_mean_degree": _mean_metric(network_nodes.get(human_network_name), human_members, "degree"),
                "mouse_mean_degree": _mean_metric(network_nodes.get(mouse_network_name), mouse_members, "degree"),
                "module_preservation_jaccard": module_score,
                "best_matching_module_pair": module_pair,
                "key_drifted_pathway": key_supported,
                "ranking_reason": reason if key_supported else "",
                "network_density_limitation": "Human/mouse cancer network densities differ substantially; edge divergence is a run-specific structural comparison, not evidence of biological deletion.",
            })
    result = pd.DataFrame(rows)
    if result.empty:
        return pd.DataFrame(columns=COMPARISON_COLUMNS)
    return result.sort_values(
        ["pathway_drift_score", "human_fdr", "mouse_fdr"],
        ascending=[False, True, True],
        na_position="last",
        ignore_index=True,
    )


def ranked_gsea(
    ranked_genes: pd.DataFrame,
    species: str,
    pathways: list[Pathway],
    gene_map: dict[str, dict[str, str]],
    *,
    permutation_num: int = 1000,
    seed: int = 42,
) -> pd.DataFrame:
    try:
        import gseapy
    except ImportError as exc:
        raise RuntimeError("GSEA requires the declared gseapy dependency.") from exc
    statistic_column = next((name for name in ("statistic", "t_statistic", "score") if name in ranked_genes), None)
    if "gene_id" not in ranked_genes or not statistic_column:
        raise ValueError("Ranked expression data must contain gene_id and a signed test statistic.")
    frame = ranked_genes[["gene_id", statistic_column]].copy()
    frame["gene_id"] = frame["gene_id"].astype(str)
    frame["gene_symbol"] = frame["gene_id"].map(
        {gene_id: value["symbol"] for gene_id, value in gene_map.items()}
    )
    frame[statistic_column] = pd.to_numeric(frame[statistic_column], errors="coerce")
    frame = frame.dropna(subset=["gene_symbol", statistic_column])
    frame = frame.loc[frame["gene_symbol"].astype(str).str.strip().ne("")]
    frame = frame.sort_values(statistic_column, ascending=False).drop_duplicates("gene_symbol")
    if frame.empty:
        return pd.DataFrame()
    gene_sets: dict[str, list[str]] = {}
    pathway_by_key: dict[str, Pathway] = {}
    for pathway in pathways:
        if pathway.species != species:
            continue
        key = f"{pathway.database}|{pathway.pathway_id}|{pathway.name}"
        members = [
            gene_map[gene_id]["symbol"]
            for gene_id in pathway.gene_ids
            if gene_id in gene_map and gene_map[gene_id]["symbol"]
        ]
        if members:
            gene_sets[key] = members
            pathway_by_key[key] = pathway
    if not gene_sets:
        return pd.DataFrame()
    result = gseapy.prerank(
        rnk=frame[["gene_symbol", statistic_column]],
        gene_sets=gene_sets,
        min_size=10,
        max_size=500,
        permutation_num=permutation_num,
        seed=seed,
        outdir=None,
        no_plot=True,
        verbose=False,
    ).res2d.reset_index()
    output = result.rename(columns={
        "Term": "pathway_key",
        "ES": "enrichment_score",
        "NES": "normalized_enrichment_score",
        "NOM p-val": "p_value",
        "FDR q-val": "adjusted_p_value",
        "Lead_genes": "leading_edge_symbols",
    })
    if "pathway_key" not in output.columns:
        output = output.rename(columns={output.columns[0]: "pathway_key"})
    output["species"] = species
    output["method"] = "GSEA preranked by saved signed test statistic; gene-set permutations"
    output["permutation_num"] = permutation_num
    output["random_seed"] = seed
    output["database"] = output["pathway_key"].map(lambda key: pathway_by_key.get(key, Pathway("", "", "", "", frozenset(), "")).database)
    output["pathway_id"] = output["pathway_key"].map(lambda key: pathway_by_key.get(key, Pathway("", "", "", "", frozenset(), "")).pathway_id)
    return output
