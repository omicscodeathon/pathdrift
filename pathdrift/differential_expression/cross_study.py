from __future__ import annotations

import re

import numpy as np
import pandas as pd

from .validation import ExpressionValidationError, normalize_ensembl_id


_REPLICATE_PATTERN = re.compile(r"Day(?P<day>\d+)_rep(?P<replicate>\d+)", re.IGNORECASE)
_EPCAM_PATTERN = re.compile(r"EpCAM\((?P<status>[+-])\)", re.IGNORECASE)


def prepare_mouse_cross_study_expression(
    tumor_expression: pd.DataFrame,
    tumor_metadata: pd.DataFrame,
    healthy_expression: pd.DataFrame,
    healthy_metadata: pd.DataFrame,
    gene_mapping: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict]:
    required_tumor_metadata = {
        "sample_id",
        "disease_state",
        "geo_title",
        "geo_characteristics",
    }
    required_healthy_metadata = {"sample_id", "disease_state", "geo_title"}
    required_mapping = {
        "mouse_ensembl_id",
        "mouse_symbol",
        "orthology_type",
    }
    if not required_tumor_metadata.issubset(tumor_metadata.columns):
        raise ExpressionValidationError("GSE155577 metadata lacks the fields required to select tumor replicates.")
    if not required_healthy_metadata.issubset(healthy_metadata.columns):
        raise ExpressionValidationError("GSE116385 metadata lacks sample IDs, disease state, or source titles.")
    if not required_mapping.issubset(gene_mapping.columns):
        raise ExpressionValidationError("Mouse gene mapping lacks stable IDs, symbols, or orthology type.")
    if tumor_expression.index.has_duplicates or healthy_expression.index.has_duplicates:
        raise ExpressionValidationError("Cross-study input matrices must have unique gene identifiers.")

    tumor_expression = tumor_expression.copy()
    tumor_expression.index = tumor_expression.index.map(normalize_ensembl_id)
    tumor_expression.columns = tumor_expression.columns.astype(str)
    healthy_expression = healthy_expression.copy()
    healthy_expression.index = healthy_expression.index.astype(str).str.strip()
    healthy_expression.columns = healthy_expression.columns.astype(str)
    if tumor_expression.index.has_duplicates:
        raise ExpressionValidationError("Tumor matrix IDs are duplicated after Ensembl version normalization.")
    if healthy_expression.index.str.casefold().duplicated().any():
        raise ExpressionValidationError("Healthy source gene symbols are duplicated after case normalization.")

    tumor_metadata = tumor_metadata.copy()
    tumor_metadata["sample_id"] = tumor_metadata["sample_id"].astype(str).str.strip()
    healthy_metadata = healthy_metadata.copy()
    healthy_metadata["sample_id"] = healthy_metadata["sample_id"].astype(str).str.strip()
    if tumor_metadata["sample_id"].duplicated().any() or healthy_metadata["sample_id"].duplicated().any():
        raise ExpressionValidationError("Cross-study sample metadata contains duplicate sample IDs.")
    if set(tumor_metadata["sample_id"]) != set(tumor_expression.columns):
        raise ExpressionValidationError("GSE155577 metadata and expression sample IDs do not match exactly.")
    if set(healthy_metadata["sample_id"]) != set(healthy_expression.columns):
        raise ExpressionValidationError("GSE116385 metadata and expression sample IDs do not match exactly.")
    if not tumor_metadata["disease_state"].astype(str).str.casefold().eq("cancer").all():
        raise ExpressionValidationError("GSE155577 contains an unexpected non-cancer sample label.")
    if not healthy_metadata["disease_state"].astype(str).str.casefold().isin(
        {"healthy", "normal", "control"}
    ).all():
        raise ExpressionValidationError("GSE116385 contains an unexpected non-healthy sample label.")

    tumor_metadata["geo_title"] = tumor_metadata["geo_title"].fillna("").astype(str)
    tumor_metadata["geo_characteristics"] = tumor_metadata["geo_characteristics"].fillna("").astype(str)
    in_vivo = ~(
        tumor_metadata["geo_characteristics"].str.contains("in vitro cell culture", case=False)
        | tumor_metadata["geo_title"].str.contains("cell line", case=False)
    )
    selected_tumors = tumor_metadata.loc[in_vivo].copy()
    excluded_tumors = tumor_metadata.loc[~in_vivo, "sample_id"].astype(str).tolist()
    if not excluded_tumors:
        raise ExpressionValidationError("Could not verify and exclude GSE155577 cultured-cell-line samples.")
    selected_tumors["day"] = selected_tumors["geo_title"].str.extract(_REPLICATE_PATTERN)["day"]
    selected_tumors["replicate"] = selected_tumors["geo_title"].str.extract(_REPLICATE_PATTERN)["replicate"]
    selected_tumors["epcam_status"] = selected_tumors["geo_title"].str.extract(_EPCAM_PATTERN)["status"]
    if selected_tumors[["day", "replicate", "epcam_status"]].isna().any().any():
        raise ExpressionValidationError("Could not identify day, replicate, and EpCAM fraction for every in-vivo tumor sample.")

    selected_tumors["treatment"] = selected_tumors["geo_characteristics"].str.extract(
        r"treatment:\s*([^|]+)",
        flags=re.IGNORECASE,
    )[0].str.strip()
    if selected_tumors["treatment"].isna().any():
        raise ExpressionValidationError("Could not identify treatment group for every in-vivo tumor sample.")
    selected_tumors["biological_replicate"] = (
        selected_tumors["treatment"].str.casefold()
        + "|day"
        + selected_tumors["day"].astype(str)
        + "|rep"
        + selected_tumors["replicate"].astype(str)
    )
    pair_sizes = selected_tumors.groupby("biological_replicate", dropna=False).size()
    pair_fractions = selected_tumors.groupby("biological_replicate")["epcam_status"].agg(
        lambda values: set(values.astype(str))
    )
    if not pair_sizes.eq(2).all() or not pair_fractions.map(lambda values: values == {"+", "-"}).all():
        raise ExpressionValidationError(
            "Each in-vivo tumor replicate must have exactly one EpCAM-positive and one EpCAM-negative sample."
        )

    numeric_tumor = tumor_expression.apply(pd.to_numeric, errors="coerce")
    numeric_healthy = healthy_expression.apply(pd.to_numeric, errors="coerce")
    if (
        not np.isfinite(numeric_tumor.to_numpy(dtype=float)).all()
        or not np.isfinite(numeric_healthy.to_numpy(dtype=float)).all()
    ):
        raise ExpressionValidationError("Cross-study matrices contain missing or non-finite values.")
    if (numeric_tumor < 0).any().any() or (numeric_healthy < 0).any().any():
        raise ExpressionValidationError("Log2(x+1) harmonization requires non-negative source expression.")

    mapping = gene_mapping.loc[
        gene_mapping["orthology_type"].astype(str).str.casefold().eq("ortholog_one2one")
    ].dropna(subset=["mouse_ensembl_id", "mouse_symbol"]).copy()
    mapping["mouse_ensembl_id"] = mapping["mouse_ensembl_id"].astype(str).map(normalize_ensembl_id)
    mapping["symbol_key"] = mapping["mouse_symbol"].astype(str).str.strip().str.casefold()
    mapping["mouse_symbol"] = mapping["mouse_symbol"].astype(str).str.strip()
    mapping = mapping.loc[
        ~mapping["symbol_key"].duplicated(keep=False)
        & ~mapping["mouse_ensembl_id"].duplicated(keep=False)
    ]
    symbol_to_id = dict(zip(mapping["symbol_key"], mapping["mouse_ensembl_id"]))
    healthy_symbol_to_id = {
        symbol_to_id[symbol.casefold()]: symbol
        for symbol in healthy_expression.index.astype(str)
        if symbol.casefold() in symbol_to_id
    }
    shared_ids = sorted(set(healthy_symbol_to_id).intersection(numeric_tumor.index))
    if len(shared_ids) < 2:
        raise ExpressionValidationError("Fewer than two uniquely mapped genes are shared across the mouse cohorts.")

    tumor_log = np.log2(numeric_tumor.loc[shared_ids, selected_tumors["sample_id"].tolist()] + 1.0)
    healthy_symbols = [healthy_symbol_to_id[gene_id] for gene_id in shared_ids]
    healthy_log = np.log2(numeric_healthy.loc[healthy_symbols] + 1.0)
    healthy_log.index = shared_ids
    healthy_log = healthy_log.loc[shared_ids]

    composite_columns: dict[str, pd.Series] = {}
    composite_metadata: list[dict[str, str]] = []
    for replicate, rows in selected_tumors.groupby("biological_replicate", sort=True):
        source_samples = rows["sample_id"].astype(str).tolist()
        day = str(rows["day"].iloc[0])
        replicate_number = str(rows["replicate"].iloc[0])
        sample_id = f"GSE155577:day{day}:rep{replicate_number}"
        composite_columns[sample_id] = tumor_log.loc[:, source_samples].mean(axis=1)
        composite_metadata.append({
            "sample_id": sample_id,
            "disease_state": "cancer",
            "source_accession": "GSE155577",
            "source_sample_ids": ";".join(source_samples),
            "source_geo_sample_ids": ";".join(rows["geo_sample_id"].astype(str)),
            "source_titles": " | ".join(rows["geo_title"].astype(str)),
            "biological_unit": "tumor specimen; mean log2 abundance of paired EpCAM fractions",
            "treatment": str(rows["treatment"].iloc[0]),
            "collection_day": day,
            "replicate": replicate_number,
        })
    tumor_composites = pd.DataFrame(composite_columns, index=shared_ids)
    healthy_log.columns = [f"GSE116385:{sample_id}" for sample_id in healthy_log.columns]
    expression = pd.concat([tumor_composites, healthy_log], axis=1)

    healthy_metadata["sample_id"] = healthy_metadata["sample_id"].map(
        lambda sample_id: f"GSE116385:{sample_id}"
    )
    healthy_rows = []
    for row in healthy_metadata.to_dict(orient="records"):
        healthy_rows.append({
            "sample_id": row["sample_id"],
            "disease_state": "healthy",
            "source_accession": "GSE116385",
            "source_sample_ids": row["sample_id"].split(":", 1)[1],
            "source_geo_sample_ids": str(row.get("geo_sample_id", "")),
            "source_titles": str(row["geo_title"]),
            "biological_unit": "GEO-provided normal mammary cell population",
            "treatment": "",
            "collection_day": "",
            "replicate": "",
            "healthy_cell_population": str(row.get("geo_title", "")),
        })
    sample_metadata = pd.DataFrame(composite_metadata + healthy_rows)
    gene_table = mapping.set_index("mouse_ensembl_id").loc[shared_ids].reset_index()
    gene_table = gene_table.rename(columns={
        "mouse_ensembl_id": "gene_id",
        "mouse_symbol": "gene_symbol",
    })
    gene_table["healthy_source_gene_symbol"] = gene_table["gene_id"].map(healthy_symbol_to_id)
    gene_table = gene_table[["gene_id", "gene_symbol", "healthy_source_gene_symbol"]]

    info = {
        "shared_genes_tested": len(shared_ids),
        "healthy_genes_available": len(healthy_expression),
        "mouse_one_to_one_symbols_available": len(mapping),
        "tumor_source_sample_count": len(selected_tumors),
        "tumor_cell_line_samples_excluded": excluded_tumors,
        "tumor_biological_replicates": len(composite_columns),
        "healthy_samples": len(healthy_rows),
        "tumor_normalization": "GEO-provided DESeq2-normalized counts; log2(x + 1) applied",
        "healthy_normalization": "GEO-provided RPKM; log2(x + 1) applied",
        "paired_tumor_fraction_handling": (
            "For each day/treatment/replicate, log2 expression was averaged across the matched "
            "EpCAM-positive and EpCAM-negative fractions to form one tumor specimen observation."
        ),
        "gene_mapping": (
            "Exact case-insensitive mouse gene-symbol mapping through the local Ensembl release 116 "
            "one-to-one orthology table; duplicate symbols and IDs were excluded."
        ),
    }
    return expression, sample_metadata, gene_table, info
