# Implementation Audit

## Verified in This Workspace
- The React/Vite frontend now lists only accession-backed GDC and GEO cohorts, reports the mouse-control limitation, polls acquisition job state, and reads acquired dimensions/provenance from the manifest endpoint.
- The `/data-acquisition/download` endpoint queues acquisition as a background job. It downloads real GDC/GEO matrices, runs the scientific preprocessing pipeline, mirrors artifacts for the frontend, registers the matrix with the selected project, and writes manifest metadata.
- GDC TCGA-BRCA acquisition retrieves Primary Tumor and Solid Tissue Normal STAR-count files and deduplicates repeated cases before analysis.
- GEO GSE155577 is parsed from its actual supplementary normalized-count matrix. Its values are not incorrectly re-normalized as raw counts.
- `data/registry/datasets.yaml` is generated from source metadata and the current manifest. It records the required accession/platform/build/date/sample/gene fields and actual GDC/GEO identifiers.
- Human and mouse internal matrix keys are species-validated Ensembl Gene IDs; numeric versions are normalized while the human `_PAR_Y` qualifier is retained. The unmapped GEO feature `RatActivatedNeu` remains only in the raw source and is excluded from derived data.
- Gene symbols are used only for display/pathway boundaries through explicit Ensembl mappings. Other identifier systems remain separate and require explicit mappings.
- The orthology TSVs use Ensembl Compara/BioMart release 116 and contain only `ortholog_one2one` records for primary analysis. Both human and mouse keys are unique; alignment now errors on ambiguous mappings instead of dropping one arbitrarily.
- A live downstream analysis run generated DEG, networks/modules, orthology, exploratory tumor-network alignment, GO enrichment, grouped internal CV evidence, and an HTML report. See `docs/REAL_DATA_IMPLEMENTATION_REPORT.md` and `results/runs/real_breast_20261004T114540Z/`.

## Scientific Boundaries
- GSE155577 has 26 GSM-linked samples: 24 in-vivo mammary tumor cell samples and two cultured E-A14 cell-line samples; no healthy mammary samples. Mouse tumor-versus-normal DEG/network comparison, cross-species differential drift, and gene-loss risk therefore remain blocked.
- The cross-species output compares tumor networks only; it is not a drift result. It had 22 one-to-one orthologues in both selected networks and one shared edge, so biological conclusions are not justified.
- Human DEG used 10 normal and 9 tumor TCGA samples after one repeated tumor patient aliquot was excluded. The subset validates computational execution, not a powered study.
- The five-fold patient-grouped ML AUROC/AUPRC means were 1.0, but each test fold contains only 3-5 samples. These exploratory metrics are unstable and not clinical/predictive validation. No external validation cohort was used.
- Morphology and PPI analysis were not run.
- The scripts were executed directly on real public data. The new frontend/background-job acquisition route has not yet been manually exercised end-to-end with a logged-in local project/database.

## Current Checks
- Full backend unit suite: 43 passed, including species-specific Ensembl ID, `_PAR_Y`, and ambiguous orthology rejection cases.
- Frontend TypeScript type-check: passed.
- Python compile checks for edited acquisition, preprocessing, and analysis files: passed.
- The local backend public-source search and manifest endpoints returned HTTP 200 with the verified accessions and real matrix dimensions.
- Dataset registry parsed and validated: two unique accessions, all required fields present, every registered sample ID reconciled to a raw matrix column, and source-specific Ensembl ID counts verified.
