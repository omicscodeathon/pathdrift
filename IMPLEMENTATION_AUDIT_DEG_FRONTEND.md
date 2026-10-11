# Differential Expression Frontend Audit

## Existing components and behavior

- `frontend/src/pages/DEGPage.tsx` discovers saved runs through `phase3Api.savedRuns()`, keeps the current completed `currentRunId` when available, otherwise chooses the newest completed run, stores that selection, and immediately renders the result screen. The result screen includes its own run selector.
- `frontend/src/pages/DifferentialExpressionPage.tsx` loads the run summary and complete paginated DEG rows; displays comparison metadata, counts, saved plots when present, interactive Plotly fallbacks, filters, sorting, pagination, and network links.
- `frontend/src/pages/RunQCPage.tsx` uses React Query for dataset/report/artifact requests and renders explicit loading, error, and empty states. Its artifact images are fetched as blobs and displayed with revocable object URLs. DEG follows those same patterns for saved images while using the run-scoped analysis API.
- `frontend/src/pages/analysis/shared.tsx` contains shared run context, the selector/header, result states, API pagination, and object-URL cleanup helpers.

## Existing frontend API

`frontend/src/api/client.ts` defines `phase3Api`:

- `savedRuns()` → `GET /runs/saved`
- `summary(runId)` → `GET /runs/{run_id}/analysis-summary`
- `deg(runId, params)` → `GET /runs/{run_id}/deg`
- `degArtifacts(runId, species, comparison)` → `GET /runs/{run_id}/deg/{species}/artifacts`
- `degArtifact(runId, species, artifactName, comparison)` → authenticated blob request to `GET /runs/{run_id}/deg/{species}/artifacts/{artifact_name}`

The app mounts these endpoints under `/api/v1/runs`.

## Existing backend and database support

- `backend/app/api/routes/phase3.py` contains the run ownership check, manifest-backed and ORM-backed DEG retrieval, analysis summary endpoint, and authenticated artifact listing/file routes.
- For a filesystem-backed completed run, `_filesystem_deg_page()` reads the saved CSV and returns paginated API rows. ORM-backed runs use `_deg_page()` and join `RunDifferentialExpression` to `Gene`.
- `backend/app/api/routes/runs.py` merges database runs with completed filesystem manifests for `/runs/saved`.
- `backend/app/models/models.py` defines `RunDifferentialExpression` with species, comparison, method, log2FC, p-value, adjusted p-value, statistic, base mean, average expression, direction, significance, and thresholds. The gene catalog stores Ensembl ID and optional symbol.
- The verified run is served through the filesystem-manifest branch. The relational schema and ORM retrieval path exist, but are not required to serve this saved run; no claim is made here that this run also has a database copy.
- Artifact paths are resolved beneath the selected run/species result directory, restricted to supported result extensions, and only returned after the run ownership check. The browser never reads the server filesystem directly.

## Actual result files inspected

The requested singular path `results/run/...` does not exist in this checkout. The repository's result root is `results/runs/`, and the real files are under:

`results/runs/1c782941-d15c-4c3a-a291-5172f1d23937/deg/`

Discovered files:

- `human/all_genes.csv`, `human/significant_genes.csv`, `human/summary.json`, `human/volcano.png`, `human/volcano.svg`, `human/ma_plot.png`, `human/ma_plot.svg`
- `mouse/summary.json`
- `mouse/cross_study_exploratory/all_genes.csv`, `significant_genes.csv`, `gene_mapping.csv`, `sample_metadata.csv`, `summary.json`, `volcano.png`, `volcano.svg`, `ma_plot.png`, `ma_plot.svg`
- `network_module_summary.json`

The human all-gene CSV contains `gene_id`, `log2fc`, `pvalue`, `adjusted_p_value`, `statistic`, `base_mean`, `average_expression`, `direction`, `significant`, and `method`. The CSV itself has no human `gene_symbol` column. The exploratory mouse CSV includes `gene_symbol` and `average_expression`; its `base_mean` values are not populated.

## Verified run data

Run `1c782941-d15c-4c3a-a291-5172f1d23937` has a completed Phase 3 manifest.

- Human `cancer_vs_healthy`: 23,800 tested rows, 6,116 significant genes, 2,915 upregulated and 3,201 downregulated; method `PyDESeq2 (DESeq2 Wald test)`; Benjamini-Hochberg adjustment; alpha 0.05; |log2FC| threshold 1.0; 8 case and 9 control samples.
- Mouse direct cancer-versus-control analysis is unavailable: the configured study has 26 case samples and no controls.
- A separate exploratory cross-study mouse comparison exists: 15,215 returned gene rows, 14,592 tested genes, 10,288 significant; method `Welch's t-test + Benjamini-Hochberg`; 12 case and 8 control samples; alpha 0.05; |log2FC| threshold 1.0. Its summary warns that study, assay/platform, and processing are confounded and the result is not confirmatory.
- Both species have real saved volcano and MA PNG/SVG artifacts for their available comparisons.

## Reuse and changes

Reused the existing saved-run selector/store, React Query, authenticated Phase 3 API, MUI components, Plotly charts, filesystem-backed API reader, ORM fallback, and RunQC-style blob/object-URL artifact pattern. The DEG view keeps all-gene results by default, derives summary statistics from the saved summary, presents the mouse exploratory limitation, and displays `statistic` and mean-expression columns only where returned by the API schema.

No differential-expression analysis is performed by the frontend, no synthetic result values are added, and no Phase 2 QC routes or behavior are changed.
