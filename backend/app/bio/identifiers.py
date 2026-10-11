from __future__ import annotations

import re
from typing import List, Tuple

import pandas as pd


ENSEMBL_GENE_PATTERNS = {
    "human": re.compile(r"^ENSG\d+(?:_PAR_Y)?$"),
    "mouse": re.compile(r"^ENSMUSG\d+$"),
}


def enforce_ensembl_gene_ids(expression: pd.DataFrame, species: str) -> Tuple[pd.DataFrame, List[str]]:
    """Normalize stable Ensembl gene IDs and exclude unverified feature labels."""
    species_key = species.strip().lower()
    pattern = ENSEMBL_GENE_PATTERNS.get(species_key)
    if pattern is None:
        raise ValueError(f"Unsupported species for Ensembl gene-ID validation: {species}")

    normalized_ids = pd.Index(expression.index.astype(str).str.strip())
    normalized_ids = normalized_ids.str.replace(r"\.\d+(?=_PAR_Y$|$)", "", regex=True)
    valid_mask = normalized_ids.to_series(index=expression.index).map(lambda gene_id: bool(pattern.fullmatch(gene_id))).to_numpy()
    excluded_ids = sorted(set(normalized_ids[~valid_mask].tolist()))
    filtered = expression.loc[valid_mask].copy()
    filtered.index = normalized_ids[valid_mask]
    if filtered.empty:
        raise ValueError(f"No {species.title()} Ensembl Gene IDs remain after identifier validation")
    return filtered, excluded_ids