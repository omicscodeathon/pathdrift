# Acquired datasets

PathDrift presents acquired public data separately from project-imported datasets:

- **Acquired public datasets** are the repository-level cohorts in `data/pathdrift/manifests/dataset_manifest.json`. They appear at the top of the **Datasets** page and are browsable without copying them into a project.
- **Project datasets** are uploaded or acquired for the selected project and appear in the project dataset table. These records are stored in the application database and are the datasets eligible for project analysis workflows.

## Current acquisition manifest

The manifest currently records three validated datasets. The table's gene counts are the counts used for analysis; `raw_gene_count` records rows in the acquired source matrix:

| Accession | Species | Analysis samples | Healthy | Cancer | Genes | Expression source |
|---|---|---:|---:|---:|---:|---|
| TCGA-BRCA | Human | 19 | 10 | 9 | 43,254 | GDC STAR counts, processed as log2(CPM + 1) |
| GSE155577 | Mouse | 26 | 0 | 26 | 47,729 | GEO study-normalized RNA-seq values |
| GSE116385 | Mouse | 8 | 8 | 0 | 24,391 | GEO RPKM values for normal mammary cell populations |

For TCGA-BRCA, 20 raw aliquots and 60,660 source gene rows were retrieved; patient-grouped analysis uses 19 samples and 43,254 genes after filtering, excluding a repeated tumor aliquot. The TCGA adjacent-normal samples are used for the primary tumor contrast rather than mixing in GTEx.

GSE155577 contains 24 in-vivo tumor-cell samples and two cultured tumor-cell-line samples, with no healthy mammary controls. Its 47,730 source gene rows become 47,729 analysis genes; `RatActivatedNeu` remains represented in the raw source but is excluded from internal analysis because it has no verified mouse Ensembl Gene ID. Mouse tumor-versus-normal analysis therefore requires a separate healthy cohort.

GSE116385 is a selected subset of the 23-sample GEO series: it contains eight healthy mouse mammary samples (two each of adult basal, fetal mammary stem, luminal progenitor, and mature luminal populations); the other 15 tumor-model samples are not included. GEO's normal-mammary supplementary file contains 24,391 unique source-provided mouse gene symbols and study-normalized RPKM values, not Ensembl IDs or raw counts. The processed matrix preserves all 24,391 identifiers and values as supplied, without count normalization. The gene symbols are not asserted to be Ensembl-validated.

For Phase 3, these eight healthy samples were used in a separate, explicitly **exploratory cross-study** mouse comparison against 12 biological tumor replicates from GSE155577. The tumor cohort has 24 in-vivo sorted EpCAM-positive/negative fractions and two cultured cell-line samples; the cell lines were excluded and each matched in-vivo fraction pair was averaged before testing. The analysis mapped 15,215 shared genes through unique mouse-symbol entries in the local Ensembl release 116 one-to-one mapping table and used log2(x + 1) expression with Welch's t-test and Benjamini-Hochberg correction. Results, all tested-gene rows, sample provenance, mapping, checksums, and plots are under `results/runs/<run-id>/deg/mouse/cross_study_exploratory/`.

This comparison is **not confirmatory**: tumor/healthy status is perfectly confounded with GEO study, assay/platform, and processing; the normal cohort also combines fetal and adult mammary populations. The reported significance count must not be treated as a validated tumor signature. A same-study healthy mouse control cohort is needed for confirmatory mouse DEG.

The source record, platform, source data type, genome build when available, download date, normalization method, sample identifiers, clinical coverage, and analysis notes are retained in the manifest. SHA-256 checksums are recorded for each cohort's raw expression matrix, metadata, and processed matrix; GSE116385 also records the checksum and GEO URL for its original supplementary file. Dataset file paths are repository-relative. The Datasets page's **View dataset** action lets users browse the full expression matrix in pages alongside all sample metadata.

## Acquisition quality control

The **Acquisition QC** page now shows one current QC result per acquired accession, selecting the newest complete per-dataset result rather than repeating datasets for each analysis run. All three manifest cohorts have QC outputs: TCGA-BRCA (20 raw aliquots), GSE155577 (26 samples), and GSE116385 (8 samples). The QC sample counts describe the files actually assessed and can differ from the manifest's analysis sample counts.

Each cohort section includes its QC summary, sample-level metrics, saved PCA/correlation/clustering images, and a table of per-sample PCA coordinates. Human and mouse cohorts are shown separately. GSE116385 is assessed from its GEO-provided RPKM values using source gene symbols; its symbols are not labelled as Ensembl-validated IDs. Its QC filter retained 11,486 of the 24,391 source rows at the configured expression threshold. The saved results live under `results/runs/<run-id>/qc/<accession>/`.

The page reads these existing results; it does not create another analysis run just to display them.

## API preview

The read-only endpoints used by the Datasets page are:

- `GET /api/v1/data-acquisition/datasets` — acquired dataset entries.
- `GET /api/v1/data-acquisition/datasets/{dataset_id}?offset=0&limit=100` — manifest entry with a page of expression rows and all sample metadata rows. Increase `offset` to browse the full matrix; `limit` is capped at 250.
- `GET /api/v1/runs/acquisition-qc` — one latest QC result per acquired accession.
- `GET /api/v1/runs/acquisition-qc/{accession}` — summary, sample QC, PCA coordinates, correlations, and clustering assignments.
- `GET /api/v1/runs/acquisition-qc/{accession}/artifacts/{artifact_name}` — a saved per-dataset QC image or table.

Dataset paths are resolved from the server-side manifest and constrained to the repository root; clients cannot supply arbitrary file paths. The UI requests pages of 50, 100, or 250 genes while keeping all sample columns visible, and includes every metadata record.
