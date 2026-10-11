# Real-Data Implementation Report

## Sources and Preprocessing
- Human: GDC/TCGA-BRCA STAR counts, downloaded from the live GDC API on 2026-10-04. Ten primary-tumor and ten adjacent-normal files were requested; one repeated patient tumor aliquot was excluded before analysis, leaving 10 normal and 9 tumor samples.
- Mouse: NCBI GEO GSE155577 normalized expression matrix, downloaded from the study's GEO supplementary files. It contains 26 tumor-derived samples and no healthy mammary controls.
- Human processing: Ensembl version suffixes removed while preserving GENCODE `_PAR_Y` qualifiers, low-expression filtering applied, then log2(CPM + 1); 60,660 valid source Ensembl IDs became 43,254 genes across 19 patient-deduplicated samples.
- Mouse processing: GEO-provided normalized expression was passed through without count normalization. The original source matrix has 47,730 feature rows; the unmapped label `RatActivatedNeu` is retained in raw source data but excluded from all derived matrices, leaving 47,729 mouse Ensembl IDs. Of 26 GEO samples, 24 are in-vivo tumor cells and two are cultured E-A14 cell-line samples; networks use only the 24 in-vivo samples.
- The required registry is `data/registry/datasets.yaml`. It lists authoritative sample, case, aliquot, file, GSM, BioSample, and SRA identifiers, source platform/type/build, download date, gene-ID counts, and exclusions. Every analysis run also records result-to-accession provenance.
- Provenance, sample metadata, normalization methods, preprocessing logs, and matrix paths remain in `data/pathdrift/manifests/dataset_manifest.json`.

## Completed Computations
- Human DEG: Welch's t-test on log2(CPM + 1), Benjamini-Hochberg FDR, 1,942 genes passing the configured FDR and fold-change thresholds.
- Co-expression networks and module detection: Spearman networks were built separately for human normal (10 samples), human tumor (9 samples), and mouse tumor (26 samples), using the top 300 variable genes. Each network includes saved edges, node/module assignments, and topology summaries.
- Orthology: 17,146 `ortholog_one2one` human-mouse pairs retrieved from Ensembl Compara/BioMart release 116. Each pair records human/mouse Ensembl IDs, symbols for display, orthology type, confidence, and release. Human and mouse IDs are both unique; ambiguous rows are rejected rather than arbitrarily selected.
- Tumor-network alignment: 22 one-to-one orthologues were represented in both selected networks; one shared edge was observed (edge Jaccard approximately 0.000053). This is exploratory alignment, not differential network drift.
- Human GO Biological Process enrichment: completed from the significant human DEG symbols; 138 terms passed the configured FDR threshold.
- Internal ML: exploratory logistic-regression cross-validation used stratified patient-grouped folds. The five-fold AUROC/AUPRC means were 1.0 on this 19-sample subset. Fold test groups contained only 3-5 samples, so these scores are unstable and are not evidence of predictive or clinical performance.
- Identifier policy: processed matrices and network/DEG tables use species-appropriate Ensembl Gene IDs as keys. Gene symbols are produced only through an explicit Ensembl mapping table for display/pathway enrichment; Entrez, UniProt, and STRING identifiers are not substituted implicitly.

## Not Completed / Blocked
- Mouse tumor-versus-healthy DEG, mouse healthy/disease network drift, cross-species differential drift, and gene-loss risk are blocked because GSE155577 has no healthy mammary samples. Mouse-only tumor networks cannot support those contrasts.
- External validation is not performed; no independent held-out cohort was acquired.
- Morphology/PPI analysis is not included in this run.
- The real-data analysis was run by the reproducible scripts, not queued through a live user-authenticated project workflow. The frontend/API workflow now queues acquisition in a background job, but end-to-end UI acquisition against the local database has not been manually exercised.
- The cohort subset is suitable for pipeline verification and exploratory computation, not a powered or clinically validated study.

## Reproduction
From the repository root, with the project virtual environment and dependencies installed:

```powershell
.\.venv\Scripts\python backend\scripts\acquire_real_breast_data.py
.\.venv\Scripts\python backend\scripts\run_real_data_analysis.py
```

The run directory for the verified analysis is `results/runs/real_breast_20261004T114540Z/`. It contains the run manifest, human DEG table, processed matrices, network/module outputs, orthology mappings, pathway results, exploratory grouped-CV model/metrics, and HTML report.
