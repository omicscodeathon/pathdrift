# Phase 3 implementation audit

## Scope and constraints

Phase 1 and Phase 2 already provide an application database, acquisition/preprocessing/QC, a CLI, and filesystem run artifacts. Phase 3 should extend those surfaces rather than repeat acquisition or quality control. The requested phase explicitly excludes frontend work and cross-species inference. A mouse cancer-versus-normal analysis is not currently supportable from the configured GSE155577 cohort: its 26 samples are cancer-labelled (24 in-vivo and two cell-line samples), with no controls. GSE116385 is an independent eight-sample normal-only subset and is not silently interchangeable with the GSE155577 cohort.

## Existing relevant implementation

| Area | Existing files and capabilities | Reuse / gap |
|---|---|---|
| Phase 2 orchestrator | `pathdrift/pipeline.py` — config loading, acquisition, input validation, QC, normalized matrices, result manifests, provenance and run status | Reuse the persisted Phase 2 run, QC-passed normalized matrices, `AnalysisRun`, and manifest. Add downstream stages without rerunning acquisition/QC. |
| Run registry | `pathdrift/acquisition/registry.py` — session, `AnalysisRun`, `AnalysisRunDataset`, `Dataset`, `Sample`, `SampleQC` registration | Reuse for run/dataset/sample identity; add Phase 3 associations without conflating `Analysis` with `AnalysisRun`. |
| QC / validators | `pathdrift/acquisition/qc.py`, `pathdrift/acquisition/validators.py` | Reuse QC artifacts and validation concepts; Phase 3 still needs strict expression/metadata/group validation before DEG or networks. |
| Configuration | `configs/breast_cancer.yaml`, `pathdrift/pipeline.py::load_config`, `backend/app/core/config.py` | YAML is the run-level configuration source. Existing QC thresholds are explicit; no Phase 3 DEG/network/module configuration or selection rationale exists yet. |
| Existing DEG | `backend/app/bio/deg.py::DEGAnalyzer`; `backend/app/api/routes/deg.py`; `backend/app/tasks/analysis_tasks.py::run_deg` | There is a general file-backed DEG workflow (pydeseq2 / Welch t-test) but it is tied to `Analysis`/`Dataset` and Celery jobs. It currently falls back from unavailable/failing pydeseq2 to t-test, reports all zero effects as down in its non-significant direction field, and does not provide the requested run-scoped Phase 3 persistence, validation, plots, or complete database rows. Reuse/refactor statistical helpers after making selection/failure explicit. |
| Existing networks/modules | `backend/app/bio/network.py::NetworkConstructor`, `compute_network_statistics`; `backend/app/api/routes/networks.py`; `backend/app/tasks/analysis_tasks.py::run_network_construction` | Existing Pearson/Spearman correlation, BH correction, graph metrics, Louvain module calls, and file-backed network jobs are reusable components. Current per-pair loops and whole-matrix operations need runtime/scale assessment; implementation is `Analysis`/`Dataset` scoped and lacks requested durable edge/node/module membership persistence. |
| ORM and database | `backend/app/models/models.py`; exports in `backend/app/models/__init__.py`; `backend/app/db/base.py` | Existing ORM entities include `AnalysisRun`, `AnalysisRunDataset`, `SampleQC`, `Gene`, `Analysis`, `DEGResult`, `GeneNetwork`, and `NetworkModule`. There are no `DifferentialExpression`, `NetworkNode`, `NetworkEdge`, `ModuleGene`, or `Figure` ORM models. `Gene` requires an Ensembl ID, so source symbols such as GSE116385 cannot be inserted as if they were stable IDs. |
| Database migrations | `backend/alembic/env.py`; `backend/alembic/versions/20261005_01_acquisition_qc.py`, `20261005_02_dataset_status.py` | Alembic imports `app.models.models`; migrations currently establish acquisition-run/QC storage and dataset status. Add a forward migration for new Phase 3 tables/columns; do not recreate Phase 1 entities. |
| API | `backend/app/api/routes/runs.py`, `deg.py`, `networks.py`; mounted from `backend/app/main.py` | Acquisition QC endpoints read filesystem run artifacts; existing DEG/network endpoints query `Analysis` and use result files. The requested Phase 3 API must be run-scoped, database-backed, ownership-checked and paginated. |
| CLI | `pathdrift/__main__.py`, `pathdrift/pipeline.py` | CLI currently supports `database check` and `run --config` (Phase 2). Add run-ID Phase 3 commands while preserving both commands. |
| Existing result data | `results/runs/<id>/manifest.json`, `provenance.json`, `qc/<accession>/` CSV/JSON/PNG, and `backend/uploads/data_acquisition/processed/` | Phase 2 writes normalized Parquet matrices and QC-passed sample metadata/coordinates. Phase 3 should be stored under the existing run directory and record each stage in its manifest. Older `real_breast_*` result folders belong to a separate analysis script and are not a substitute for a Phase 2 `AnalysisRun`. |
| Test coverage | `tests/unit/test_analysis_workflow.py`, `test_acquisition_qc.py`, `test_filesystem_qc_runs.py`, `test_preprocessing.py`, `test_network_drift.py`, and related unit tests | Reuse deterministic unit testing conventions. Add targeted tests for new scientific calculations, persistence/API behavior, and restart semantics. |
| Dependencies | `backend/requirements.txt` pins NumPy, SciPy, pandas, statsmodels, scikit-learn, NetworkX, pydeseq2, matplotlib, seaborn and pyarrow | Most scientific primitives are already declared. Do not add a community-detection package before checking the existing NetworkX version/API and measured needs. |

## Data facts that constrain Phase 3

- The authoritative acquisition manifest is `data/pathdrift/manifests/dataset_manifest.json`.
- TCGA-BRCA has 20 raw aliquots (10 healthy, 10 cancer); the current patient-grouped manifest analysis uses 19, omitting the repeated tumor aliquot. Phase 2's normalized artifacts must be consulted for the exact QC-retained groups used by the run.
- PostgreSQL is reachable and migrated at revision `20261005_02`. The latest completed `AnalysisRun` is `1c782941-d15c-4c3a-a291-5172f1d23937`; it registers TCGA-BRCA and GSE155577 and points to QC-normalized Parquet matrices under `data/processed/<run-id>/` with metadata under `data/raw/`. Its TCGA matrix contains 44,601 genes and 20 samples (10 cancer, 10 healthy); one patient contributes duplicate tumor aliquots and a matched normal. The manifest's 19-sample count is therefore not the exact cohort stored in this Phase 2 run.
- The repository `.venv` has PyArrow and PyDESeq2 installed, and both QC-normalized Parquet files for that completed run are readable. The configured `backend/venv` does not have the same scientific/read dependencies; commands that process the real run need an explicitly selected environment with the pinned backend requirements.
- GSE155577 has 26 cancer-labelled samples and no healthy/control samples. Its metadata distinguishes 24 in-vivo tumor-derived samples from two cultured tumor-cell-line samples.
- GSE116385 has eight normal mouse mammary samples only. It is a separate GEO series and normal-only; combining it with GSE155577 for a contrast would require an explicit, scientifically validated cross-study design and is not implied by the current configuration.
- `configs/breast_cancer.yaml` keeps GTEx disabled and declares TCGA adjacent-normal as the primary human reference. The implementation must report unavailable comparisons rather than silently acquiring, substituting, or fabricating controls.

## Conflicts and risks

1. The ORM is in `backend/app/models/`, not a `backend/app/models.py` module; no phase-specific `DifferentialExpression`, edge, node, membership, or figure model currently exists.
2. Existing `DEGResult` and `GeneNetwork` belong to the older `Analysis` workflow and hold result file paths/summary counts. They are not sufficient alone for run-scoped row-level persistence and complete edge/member data.
3. Existing `NetworkModule` stores a module summary/path but does not establish `Network -> Module -> ModuleGene -> Gene` foreign-key membership.
4. Gene identity must accommodate source-provided identifiers without misrepresenting mouse symbols as Ensembl IDs. The existing `Gene` model is Ensembl-only.
5. Phase 2 `AnalysisRun` is distinct from `Analysis`; downstream FK design and API authorization must keep that distinction explicit and preserve existing clients.
6. GSE155577 has no control group, so mouse DEG must be recorded as unavailable with a scientific reason. The eight-sample GSE116385 cohort is normal-only and does not change this.
7. A full all-pairs correlation network is quadratic in gene count. Configurable variance/filter rules, realistic sample sizes, memory/runtime bounds, and recorded filtering must be designed before real-data execution; arbitrary silent top-N truncation would violate the specification. For the real run, the user explicitly approved a 1,000-gene maximum-variance cap, which is recorded in the run configuration and network summaries.
8. A completed Phase 2 run and PostgreSQL are available locally, but run-specific provenance must be used instead of hard-coded acquisition-manifest paths. No new Phase 3 results should be claimed until a migration and real-data execution are verified.

## Implementation plan

1. Trace current Phase 2 artifact paths, run status/config/provenance, ORM constraints, migration state, API authentication, CLI, and tests. Confirm database/runtime readiness without exposing credentials.
2. Extend the run configuration with explicit DEG, network, and module settings. Implement an input validator that checks file/metadata/sample/gene/numeric/normalization/group conditions and emits a scientific error for unsupported contrasts.
3. Implement species-specific DEG selection based on declared data type and normalization: use a count model only for verified raw counts; use an appropriate continuous-expression method for normalized matrices; never silently fall back. Persist all tested genes to CSV and PostgreSQL and generate actual-data figures only for valid comparisons.
4. Implement configurable expression-derived networks, correction/thresholding, centrality/network statistics, and deterministic modules. Persist node/edge/module/membership records and export complete result files; never treat a DEG list as a network.
5. Add run-scoped DB models and forward Alembic migration only after validating ownership, stable/source gene identity, uniqueness, and cascades. Add authenticated, paginated PostgreSQL API endpoints and CLI subcommands with idempotent stage behavior.
6. Add deterministic unit/integration tests. Execute the valid human contrast on Phase 2 QC-passed data if runtime/database prerequisites are available. Record mouse comparison as unavailable unless the configured mouse source includes a valid control group. Verify result files against database rows and record stage provenance and limitations.

## Audit completion gate

This audit identified reusable Phase 2 QC and legacy analysis components and the missing Phase 3 persistence layer. The implementation gate was satisfied against the exact Phase 2 run before migration and execution.

## Executed Phase 3 performance settings and results

- Network analysis uses the 1,000 highest-variance genes remaining after the configured variance filter. This cap applies to networks only; the human differential-expression analysis still tested 23,800 genes.
- Correlation/FDR definitions are unchanged. Each 1,000-gene network tested all 499,500 undirected gene pairs using Spearman correlation, the configured absolute-correlation threshold, and Benjamini-Hochberg adjustment.
- Upper-triangle edge indexing is vectorized. Betweenness centrality uses a deterministic sample of eight sources; closeness remains exact for these 1,000-node networks. Network summaries record these settings.
- The Phase 3 CLI supports `--max-network-genes` so an explicit cap can also be applied to an existing run snapshot. The effective value is persisted in the run configuration and result manifest.
- Run `1c782941-d15c-4c3a-a291-5172f1d23937` completed. Human cancer, human healthy, and mouse cancer networks each contain 1,000 nodes, with 466, 41,459, and 181,915 retained edges respectively. The human DEG contrast tested 23,800 genes (6,116 significant).

## Mouse cancer-versus-healthy exploratory DEG

The acquired healthy mouse samples were included in a separately labelled cross-study exploratory comparison:

- **Cases:** 12 biological tumor replicates from GSE155577 (24 in-vivo sorted samples combined as matched EpCAM-positive/negative pairs); two cultured cell-line samples were excluded.
- **Controls:** all eight healthy mammary samples from GSE116385.
- **Genes:** 15,215 unique, shared mouse genes mapped from source symbols to Ensembl IDs; all 15,215 result rows are exported, and the 623 genes with no measurable within-group variance are explicitly untestable (null p-values), not significant.
- **Method:** Welch's unequal-variance t-test on log2(x + 1) expression, with Benjamini-Hochberg adjustment and the configured alpha/log2-fold-change thresholds.
- **Saved results:** `results/runs/1c782941-d15c-4c3a-a291-5172f1d23937/deg/mouse/cross_study_exploratory/` contains the complete and significant-gene CSVs, sample metadata and paired-sample provenance, gene mapping, JSON summary/checksums, and PNG/SVG volcano and MA plots. The 15,215 gene-level records and four figure records are persisted in PostgreSQL and queryable through the authenticated run DEG API using `species=mouse` and `comparison=cancer_vs_healthy_cross_study_exploratory`.
- **Interpretation:** the recorded exploratory output has 10,288 rows passing the configured statistical thresholds. This is not confirmatory evidence: cancer status is perfectly confounded with study, assay/platform, and processing, and the healthy cohort mixes fetal/adult mammary cell populations. Do not interpret the large significant set as a validated tumor signature or combine it with human results. A same-study healthy control cohort is needed for confirmatory mouse DEG.
