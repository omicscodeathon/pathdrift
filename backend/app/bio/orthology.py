"""
Orthology Engine

Manages human–mouse one-to-one orthology mappings.

Data source: Ensembl Compara (loaded via scripts/seed_orthology.py or the
/api/v1/orthology/seed endpoint which calls the Ensembl REST API).

Provides:
  - map_human_to_mouse(gene_list) → DataFrame
  - map_mouse_to_human(gene_list) → DataFrame
  - filter_one_to_one(df)         → only high-confidence 1:1 orthologues
  - align_expression_matrices(human_df, mouse_df, mapping) → aligned DataFrames

Orthology matching NEVER falls back to raw symbol matching without warning,
because human/mouse gene symbols are not always equivalent.
"""
import pandas as pd
import numpy as np
import httpx
import structlog
from typing import Optional, List, Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models import OrthologyMapping

logger = structlog.get_logger(__name__)

ENSEMBL_REST_URL = "https://rest.ensembl.org"


class OrthologyEngine:
    """
    Maps genes between human and mouse using stored Ensembl orthology data.
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_mapping_count(self) -> int:
        from sqlalchemy import func
        result = await self.db.execute(
            select(func.count()).select_from(OrthologyMapping)
        )
        return result.scalar() or 0

    async def map_human_to_mouse(
        self,
        human_ensembl_ids: List[str],
        one_to_one_only: bool = True,
        min_confidence: Optional[float] = None,
    ) -> pd.DataFrame:
        """
        Returns a DataFrame mapping human Ensembl IDs to mouse Ensembl IDs.

        Columns: human_ensembl_id, mouse_ensembl_id, human_symbol, mouse_symbol,
                 orthology_type, confidence
        """
        result = await self.db.execute(
            select(OrthologyMapping).where(
                OrthologyMapping.human_ensembl_id.in_(human_ensembl_ids)
            )
        )
        rows = result.scalars().all()
        df = pd.DataFrame(
            [
                {
                    "human_ensembl_id": r.human_ensembl_id,
                    "mouse_ensembl_id": r.mouse_ensembl_id,
                    "human_symbol": r.human_symbol,
                    "mouse_symbol": r.mouse_symbol,
                    "orthology_type": r.orthology_type,
                    "confidence": r.confidence,
                }
                for r in rows
            ]
        )
        if df.empty:
            logger.warning("orthology_no_mappings_found", n_queried=len(human_ensembl_ids))
            return df

        if one_to_one_only:
            df = df[df["orthology_type"] == "ortholog_one2one"]
        if min_confidence is not None:
            df = df[df["confidence"] >= min_confidence]

        return df

    async def align_expression_matrices(
        self,
        human_expr: pd.DataFrame,
        mouse_expr: pd.DataFrame,
        one_to_one_only: bool = True,
        min_confidence: Optional[float] = None,
    ) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        """
        Align human and mouse expression matrices via orthology.

        Returns
        -------
        human_aligned : pd.DataFrame
            Human expression indexed by human Ensembl ID, restricted to orthologous genes.
        mouse_aligned : pd.DataFrame
            Mouse expression indexed by mouse Ensembl ID (same row order), restricted to orthologous genes.
        mapping_used : pd.DataFrame
            The orthology mapping applied (for reproducibility record).
        """
        human_ids = human_expr.index.tolist()
        mapping = await self.map_human_to_mouse(
            human_ids, one_to_one_only=one_to_one_only, min_confidence=min_confidence
        )

        if mapping.empty:
            raise ValueError(
                "No orthology mappings found for the provided human genes. "
                "Ensure orthology data has been loaded via scripts/seed_orthology.py "
                "and that genes use Ensembl IDs (ENSG...)."
            )

        # Only keep pairs where both genes are present
        mapping = mapping[
            mapping["human_ensembl_id"].isin(human_expr.index)
            & mapping["mouse_ensembl_id"].isin(mouse_expr.index)
        ]

        if mapping.empty:
            raise ValueError(
                "No orthologous genes found in both expression matrices. "
                "Check that gene identifiers are Ensembl IDs."
            )

        # Deduplicate: one human → one mouse only
        mapping = mapping.drop_duplicates(subset="human_ensembl_id")
        mapping = mapping.drop_duplicates(subset="mouse_ensembl_id")

        human_aligned = human_expr.loc[mapping["human_ensembl_id"].values].copy()
        mouse_aligned = mouse_expr.loc[mapping["mouse_ensembl_id"].values].copy()
        # Rename mouse rows to human IDs for direct comparison
        mouse_aligned.index = mapping["human_ensembl_id"].values

        logger.info(
            "orthology_alignment_done",
            n_orthologous_genes=len(mapping),
            pct_human=f"{len(mapping)/len(human_expr):.1%}",
            pct_mouse=f"{len(mapping)/len(mouse_expr):.1%}",
        )
        return human_aligned, mouse_aligned, mapping


async def fetch_ensembl_orthologues(
    species_from: str = "homo_sapiens",
    species_to: str = "mus_musculus",
    type_filter: str = "ortholog_one2one",
    batch_size: int = 100,
) -> pd.DataFrame:
    """
    Fetch orthology data from the Ensembl REST API.
    Used by scripts/seed_orthology.py to populate the DB.

    NOTE: This is rate-limited; the seed script handles pagination and delays.
    """
    url = f"{ENSEMBL_REST_URL}/homology/species/{species_from}/{species_to}"
    params = {
        "content-type": "application/json",
        "type": type_filter,
        "format": "condensed",
    }
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()

    rows = []
    for item in data.get("data", []):
        for homol in item.get("homologies", []):
            if homol.get("type") == type_filter:
                rows.append(
                    {
                        "human_ensembl_id": item["id"],
                        "mouse_ensembl_id": homol["target"]["id"],
                        "human_symbol": item.get("display_label"),
                        "mouse_symbol": homol["target"].get("display_label"),
                        "orthology_type": homol["type"],
                        "confidence": 1.0 if type_filter == "ortholog_one2one" else 0.5,
                    }
                )
    return pd.DataFrame(rows)
