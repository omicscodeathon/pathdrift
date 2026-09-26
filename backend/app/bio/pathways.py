"""
Pathway Enrichment Analysis Engine

Uses gseapy for over-representation analysis (ORA) and GSEA.

Supported gene sets:
  - GO Biological Process (GO_Biological_Process_2023)
  - GO Molecular Function
  - GO Cellular Component
  - KEGG_2021_Human / KEGG_2019_Mouse
  - Reactome_2022

Input gene lists are derived from:
  - Significantly drifting genes (from node drift analysis)
  - DEG results
  - Conserved cross-species drift genes

Results include: pathway term, gene count, p-value, FDR, genes.

IMPORTANT: Results are computational predictions only.
They are not validated clinical biomarkers.
"""
import pandas as pd
import numpy as np
import structlog
from typing import List, Optional, Dict

logger = structlog.get_logger(__name__)

# Available gene sets by species
GENE_SETS_HUMAN = [
    "GO_Biological_Process_2023",
    "GO_Molecular_Function_2023",
    "GO_Cellular_Component_2023",
    "KEGG_2021_Human",
    "Reactome_2022",
    "MSigDB_Hallmark_2020",
]

GENE_SETS_MOUSE = [
    "GO_Biological_Process_2023",
    "GO_Molecular_Function_2023",
    "GO_Cellular_Component_2023",
    "KEGG_2019_Mouse",
    "Reactome_2022",
]


class PathwayAnalyzer:
    """
    Over-representation analysis using gseapy.

    Parameters
    ----------
    species : str
        'human' or 'mouse'
    fdr_threshold : float
        Adjusted p-value cutoff for significant pathways
    """

    def __init__(self, species: str = "human", fdr_threshold: float = 0.05):
        self.species = species
        self.fdr_threshold = fdr_threshold

    def run_ora(
        self,
        gene_list: List[str],
        gene_set: str,
        background_genes: Optional[List[str]] = None,
    ) -> pd.DataFrame:
        """
        Over-representation analysis.

        Parameters
        ----------
        gene_list : list[str]
            List of gene symbols (NOT Ensembl IDs — gseapy uses symbols).
        gene_set : str
            Name of the gene set library (must be in gseapy's database).
        background_genes : list[str] or None
            Background gene universe. If None, uses gseapy default.

        Returns
        -------
        pd.DataFrame with columns:
            Term, Overlap, P-value, Adjusted P-value, Odds Ratio, Genes, significant
        """
        if not gene_list:
            logger.warning("pathway_ora_empty_gene_list")
            return pd.DataFrame()

        try:
            import gseapy as gp
        except ImportError:
            logger.error("gseapy_not_installed")
            return pd.DataFrame({"error": ["gseapy not installed"]})

        logger.info(
            "pathway_ora_starting",
            n_genes=len(gene_list),
            gene_set=gene_set,
            species=self.species,
        )

        try:
            enr = gp.enrichr(
                gene_list=gene_list,
                gene_sets=gene_set,
                background=background_genes,
                outdir=None,
                verbose=False,
            )
            results = enr.results.copy()
        except Exception as e:
            logger.error("pathway_ora_failed", error=str(e))
            return pd.DataFrame({"error": [str(e)]})

        if results.empty:
            logger.info("pathway_ora_no_results")
            return results

        # Standardise column names
        results = results.rename(
            columns={
                "Adjusted P-value": "padj",
                "P-value": "pvalue",
                "Odds Ratio": "odds_ratio",
                "Term": "term",
                "Overlap": "overlap",
                "Genes": "genes",
            }
        )
        results["significant"] = results["padj"] <= self.fdr_threshold
        results = results.sort_values("padj")

        n_sig = results["significant"].sum()
        logger.info("pathway_ora_done", n_significant=int(n_sig), gene_set=gene_set)
        return results

    def run_multi_gene_set(
        self,
        gene_list: List[str],
        background_genes: Optional[List[str]] = None,
    ) -> Dict[str, pd.DataFrame]:
        """
        Run ORA for all relevant gene sets for this species.
        Returns dict: {gene_set_name: results_df}
        """
        available = GENE_SETS_HUMAN if self.species == "human" else GENE_SETS_MOUSE
        results = {}
        for gs in available:
            try:
                df = self.run_ora(gene_list, gs, background_genes)
                results[gs] = df
            except Exception as e:
                logger.warning("pathway_gene_set_failed", gene_set=gs, error=str(e))
        return results

    @staticmethod
    def symbols_from_ensembl(
        ensembl_ids: List[str], id_to_symbol_map: Dict[str, str]
    ) -> List[str]:
        """
        Convert Ensembl IDs to gene symbols for gseapy.
        Only includes IDs with known symbols. Warns about unmapped IDs.
        """
        symbols = []
        unmapped = []
        for eid in ensembl_ids:
            sym = id_to_symbol_map.get(eid)
            if sym:
                symbols.append(sym)
            else:
                unmapped.append(eid)
        if unmapped:
            logger.warning(
                "pathway_unmapped_genes",
                n_unmapped=len(unmapped),
                examples=unmapped[:5],
            )
        return symbols
