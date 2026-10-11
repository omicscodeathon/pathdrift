from __future__ import annotations

import re

import pandas as pd


_ENSEMBL_HUMAN = re.compile(r"^(ENSG\d+)(?:\.\d+)?$")
_ENSEMBL_MOUSE = re.compile(r"^(ENSMUSG\d+)(?:\.\d+)?$")


def normalize_gene_id(value: object, species: str) -> tuple[str, str]:
    original = str(value).strip()
    pattern = _ENSEMBL_HUMAN if species == "human" else _ENSEMBL_MOUSE if species == "mouse" else None
    if pattern is None:
        raise ValueError(f"Unsupported species for Ensembl normalization: {species}")
    match = pattern.fullmatch(original)
    if not match:
        raise ValueError(f"Invalid {species} Ensembl gene ID: {original!r}")
    return match.group(1), original


def normalize_mapping(frame: pd.DataFrame) -> pd.DataFrame:
    required = {"human_ensembl_id", "mouse_ensembl_id", "orthology_type"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"Ensembl orthology response lacks columns: {sorted(missing)}")
    result = frame.copy()
    human = [normalize_gene_id(value, "human") for value in result["human_ensembl_id"]]
    mouse = [normalize_gene_id(value, "mouse") for value in result["mouse_ensembl_id"]]
    result["human_original_id"] = (
        result["human_original_id"].fillna(result["human_ensembl_id"])
        if "human_original_id" in result
        else [value[1] for value in human]
    )
    result["mouse_original_id"] = (
        result["mouse_original_id"].fillna(result["mouse_ensembl_id"])
        if "mouse_original_id" in result
        else [value[1] for value in mouse]
    )
    result["human_ensembl_id"] = [value[0] for value in human]
    result["mouse_ensembl_id"] = [value[0] for value in mouse]
    result["orthology_type"] = result["orthology_type"].astype(str).str.strip().str.lower()
    result = result.drop_duplicates(
        ["human_ensembl_id", "mouse_ensembl_id", "orthology_type"]
    ).reset_index(drop=True)
    if result.empty:
        raise ValueError("Ensembl returned no human-mouse orthology mappings.")
    return classify_relationship_cardinality(result)


def classify_relationship_cardinality(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    human_degree = result.groupby("human_ensembl_id")["mouse_ensembl_id"].transform("nunique")
    mouse_degree = result.groupby("mouse_ensembl_id")["human_ensembl_id"].transform("nunique")
    result["relationship_cardinality"] = "one_to_one"
    result.loc[(human_degree > 1) & (mouse_degree == 1), "relationship_cardinality"] = "one_to_many"
    result.loc[(human_degree == 1) & (mouse_degree > 1), "relationship_cardinality"] = "many_to_one"
    result.loc[(human_degree > 1) & (mouse_degree > 1), "relationship_cardinality"] = "many_to_many"
    return result


def primary_one_to_one(frame: pd.DataFrame, min_confidence: float = 1.0) -> pd.DataFrame:
    if not 0 <= min_confidence <= 1:
        raise ValueError("Minimum orthology confidence must be between 0 and 1.")
    result = frame.loc[
        (frame["relationship_cardinality"] == "one_to_one")
        & frame["orthology_type"].eq("ortholog_one2one")
    ].copy()
    if "confidence" in result:
        confidence = pd.to_numeric(result["confidence"], errors="coerce")
        result = result.loc[confidence.ge(min_confidence)]
    if result["human_ensembl_id"].duplicated().any() or result["mouse_ensembl_id"].duplicated().any():
        raise ValueError("Ambiguous Ensembl one-to-one mappings; refusing arbitrary selection.")
    return result
