# Phase 6 implementation audit

## Scope and outcome

Phase 6 adds run-scoped, leakage-conscious exploratory classification and a separate validation status report. It uses one labeled expression cohort at a time. It does not treat pathway enrichment, network drift, or descriptive morphology as sample-level predictors, and it does not present cross-study or cross-species results as independent validation when cohort design does not support that claim.

The workflow is deliberately marked `PARTIAL`: the current real run supports within-cohort human expression evaluation, but not sample-level network or pathway comparisons, image-derived morphology prediction, or independent external validation.

## Existing foundations and data audit

- The legacy ML engine already uses sklearn pipelines and fold-local feature selection for its database-backed experiment workflow. It is not run-scoped and its feature extraction does not establish sample-level provenance for population-derived network drift.
- Existing run artifacts are stored under `results/runs/{run_id}` and the Phase 3 API provides the run ownership check reused by Phase 6.
- For run `1c782941-d15c-4c3a-a291-5172f1d23937`, the human TCGA-BRCA matrix has 20 samples and 44,601 gene features, with 10 healthy, 10 cancer, and 18 patient groups. The manifest's original processed path is missing; the loader resolves the unique matching Phase 2 matrix under `data/processed/*/{run_id}` and records the resolved path in the output.
- Run `4ce4697e-e34a-4cd2-a88c-875eaa014c61` is a failed acquisition/QC run with no saved analysis manifest or linked analysis datasets; its QC summary is not a completed Phase 3–6 analysis and must not be mixed with the completed run's results.
- The run's mouse tumor and normal data are separate studies with differing sample types/platforms. They are not combined or represented as a matched external validation cohort.
- Saved DEG, network/module, orthology, drift, and pathway tables are cohort-level annotations. The morphology artifacts contain descriptive clinical pathology metadata only, not image-derived sample-level features or gene-to-morphology associations.

## Implemented behavior

- Loads one species/accession cohort from the completed run manifest, aligns metadata labels to expression sample IDs, rejects ambiguous/missing inputs, and restricts manifest file paths to the project workspace.
- Checks duplicate metadata/expression identifiers and reports label exclusions, metadata-to-expression mismatches, missing cells, and constant features. Imputation, variance filtering, ANOVA feature selection, scaling, and each estimator are fitted inside the training fold only.
- Uses stratified patient-group cross-validation when repeated patient identifiers are present; fails rather than splitting related samples or accepting a fold without both classes.
- Evaluates logistic regression, random forest, linear SVM, and gradient boosting with pooled out-of-fold predictions, ROC-AUC, PR-AUC, accuracy, balanced accuracy, sensitivity, specificity, precision, F1, Brier score, confusion matrices, fold-level metrics, calibration data, and percentile AUC intervals. AUC intervals resample patient groups when available.
- Aggregates feature rankings from fold-local fitted models (not from the final full-cohort fit), saves per-model importance, selection frequency, coefficient direction where supported, and a consensus candidate rank based on per-model ranks. Gene names use local Ensembl mappings; DEG, network/module, orthology, drift, pathway, and morphology annotations are joined from saved run artifacts as context only.
- Reports saved Phase 3–5 outputs as available annotations in the feature-group cards and links to their result pages. Model comparisons and ablations that cannot use those cohort-level summaries as independent sample-level predictors are labeled `NOT_EVALUATED`, not `UNAVAILABLE`; their reasons explain the leakage/pseudo-replication constraint. Missing gene-to-result matches are distinguished from missing run artifacts.
- Joins significant pathway membership to predictive genes using the saved enrichment overlap IDs. Morphology is labeled as descriptive metadata where present; it is not misrepresented as a gene-level or image-derived predictor.
- Saves out-of-fold predictions, fold-derived importance/evidence, ranked predictive features, cross-species annotations (including available exploratory mouse differential-expression evidence), fitted model artifacts, ROC/PR/calibration SVGs, and an explicit validation status JSON. Mouse evidence remains annotation-only and does not constitute independent validation.
- Adds authenticated, run-owned API endpoints for the summary, paginated predictions, predictive candidate annotations, per-model feature importance, validation status, and a fixed allowlist of report artifacts.
- Adds the run-scoped frontend at `/runs/{run_id}/ml`, with model comparison, confusion matrices, plots, preprocessing audit, links to available Phase 3–5 results, ranked gene evidence, cross-species annotations, independent-validation status, and paginated out-of-fold predictions. The run navigation section is labeled “MACHINE LEARNING”; the existing legacy prediction route remains unchanged.
- Adds `ml`, `validation`, and `phase6` CLI entry points. These invoke the same run-scoped workflow; a cached result is reused unless `--force` is passed.

## Files

- `pathdrift/phase6/dataset.py` — manifest/input resolution and labeled-cohort loading.
- `pathdrift/phase6/evaluation.py` — fold-local estimators, patient-aware splits, metrics, and intervals.
- `pathdrift/phase6/service.py` — output persistence, charts, model artifacts, and validation limitations.
- `backend/app/api/routes/phase6.py` — authenticated run-scoped read APIs.
- `backend/app/main.py` — registers Phase 6 routes under both existing run API prefixes.
- `pathdrift/__main__.py` — exposes the three Phase 6 CLI commands.
- `frontend/src/pages/Phase6MLResultsPage.tsx` — run-scoped Phase 6 result viewer.
- `frontend/src/api/client.ts` — typed Phase 6 result API client.
- `frontend/src/App.tsx`, `frontend/src/components/Layout.tsx`, and `frontend/src/pages/analysis/shared.tsx` — route, navigation, and run selection integration.
- `tests/unit/test_phase6.py` — split safety, feature pipeline, fold-derived importance, loader provenance, and cross-study refusal coverage.
- `IMPLEMENTATION_AUDIT_PHASE6.md` — implementation and scientific-limitations audit.

## Persistence and operational notes

Phase 6 writes versioned JSON/CSV/SVG/model artifacts beneath `results/runs/{run_id}/ml` (validation status under `validation`). It does not add a second PostgreSQL experiment schema: saved run artifacts are the source of truth and the read API checks existing run ownership before returning them. Model binaries are saved for reproducibility but are not exposed by the artifact-download API.

Run locally with:

```powershell
python -m pathdrift phase6 --run-id <run-uuid> --species human
```

Use `--force` to recalculate. The saved result is exploratory and must not be interpreted as clinical performance; the cohort is small and there is no independent validation dataset in this run.

## Validation

- Focused Phase 6 unit tests: 8 passed.
- Static/Pylance diagnostics on the changed Python files: no errors.
- Real run execution: completed for the 20-sample TCGA-BRCA cohort; regenerated outputs use patient-group bootstrap intervals. Verified 80 out-of-fold predictions (four models × 20 samples), five patient-grouped folds, all three SVG plots, and an explicit unavailable external-validation status.
- Frontend TypeScript type-check: passed after the evidence-availability UI change. Production Vite build previously passed with the existing large Plotly bundle warning; it was not rerun for this small UI update.
