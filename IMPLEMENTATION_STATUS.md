# Implementation Status

## Differential Expression results page

Status: implemented and verified against saved run `1c782941-d15c-4c3a-a291-5172f1d23937`.

- `/deg` uses the current selected completed run when valid, otherwise the newest completed saved run, then immediately loads its DEG summary and data. The run selector remains available in the result header.
- Run-scoped API data includes all genes by default. The result table supports search, significance/direction filtering, sorting, and pagination and displays the fields returned by the API.
- Summary cards, comparison details, and significance counts come from the saved run's DEG outputs and summary metadata.
- Saved volcano and MA figures are retrieved through authenticated artifact endpoints and displayed as blob-backed images. Interactive charts use only actual API rows when an artifact is unavailable.
- Both human and mouse choices are shown. Where no direct mouse cancer/control comparison exists, the UI explains that limitation; an available exploratory cross-study mouse comparison is shown with its study-design warning.
- The verified run has human results (23,800 rows, 6,116 significant) and exploratory cross-study mouse results (15,215 rows, 10,288 significant). Both comparisons have saved volcano and MA PNG/SVG files.
- Backend run/summary/DEG/artifact route handlers returned real data for both comparisons in the verified run. Route and traversal-safety regression tests are in `tests/unit/test_saved_analysis_runs.py`.
- RunQC implementation and routes were not modified.

## Verification

- Frontend TypeScript type-check: passed.
- Frontend production build: passed previously after analysis-page separation; the build reported the existing large Plotly bundle warning.
- Saved-run and DEG artifact tests: 3 passed.
- Direct invocation of the authenticated backend summary, DEG, and artifact-list route handlers against the saved manifest: passed for human and exploratory mouse results.

See `IMPLEMENTATION_AUDIT_DEG_FRONTEND.md` for the component/API audit, backend/database notes, and discovered result-file schema.

## Phase 4 cross-species network drift

Status: implemented, persisted, and verified against the real Phase 3 run `1c782941-d15c-4c3a-a291-5172f1d23937`.

- Ensembl Compara BioMart release 116 supplied 25,788 human-mouse orthology mappings; 16,092 met the configured primary one-to-one, confidence-1 policy. The complete relationship set and source provenance are retained.
- The actual human and mouse cancer networks each contain 1,000 nodes, with 466 and 181,915 edges, respectively. The density difference is substantial and is explicitly recorded as a limitation; edge differences must not be interpreted as significance or proof of biological gain/loss.
- The run produced 1,843 node-alignment rows (134 shared network nodes), 182,373 classified edge rows (1 conserved, 268 lost, 136,448 gained, 7 rewired, 45,649 unmappable), 134 gene-drift rows, and 14 module-drift rows.
- Database records match the corresponding CSV data-row counts and edge-status totals. The `COMPLETED` summary is stored at Alembic revision `20261006_02`.
- Orthology, cross-species, and drift CSV/JSON artifacts, all five status-specific edge CSVs, provenance, and three generated figures are present under `results/runs/<run_id>/`; the combined `cross_species_drift_summary.json` is present as well.
- The ten run-scoped Phase 4 routes are registered. Direct calls against the completed run verified summary retrieval, pagination, and GAINED-edge filtering (including the 136,448-row total).
- Phase 4 unit and existing orthology tests passed (20 tests); Python compilation and Phase 4-scoped diff whitespace checks passed.

See `IMPLEMENTATION_AUDIT_PHASE4.md` for the implementation audit, scientific assumptions, and network-density caveats.

## Phase 5 evidence, pathways, and phenotype metadata

Status: evidence-only Phase 5 pathway and phenotype outputs implemented and executed for saved run `1c782941-d15c-4c3a-a291-5172f1d23937`; overall Phase 5 remains partial.

- Added `pathdrift phase5 --run-id <run-id> [--force]`, run-scoped summary/table APIs, and Biomarker Candidates and Hub Genes pages linked from the sidebar.
- Generated gene-loss evidence/scores/high-risk tables, four network-specific multi-metric hub tables, and a DEG-qualified `biomarkers/candidate_biomarkers.csv`, plus summaries and figures under the run directory.
- The saved run yielded 134 ortholog-pair rows, 134 scored rows, 27 configured high-priority rows, and 48 eligible research candidates among 6,116 significant human DEGs. Candidates pass human DEG thresholds and have additional evidence including measured network support; they are ranked by evidence-category count, adjusted p-value, then absolute log2FC, and are not clinically validated.
- Hub tables cover 1,000 nodes each in human cancer, human healthy, mouse cancer, and mouse healthy networks. The 0.90 within-module mean-percentile rule requires at least two available metrics; current hub-supported counts are 1, 31, 11, and 7 respectively.
- Scores report human cancer-vs-healthy downregulation and Phase 4 network drift; available mouse cross-study expression is displayed as exploratory and not included in the score. Missing evidence remains null and is excluded from the weighted mean.
- Local, versioned GO, Reactome, and species-specific WikiPathways snapshots generated 179,959 ORA rows over 30 gene sets and 18,200 unique input IDs. The run also produced 2,974 pathway comparisons, including 2,224 key-drifted pathways. Counts are pathway-by-gene-set rows; the same pathway may recur for multiple gene sets. GSEA is available as an opt-in local mode and was not run.
- Pathway comparisons retain compact counts/scores instead of embedding large per-pathway gene-ID lists. Enrichment overlaps and the run's orthology table retain gene-level evidence.
- The run-scoped pathway-enrichment, key-drift, and morphology pages/APIs expose generated results. Candidate biomarker exports now show computed pathway overlaps instead of stale “unavailable” text; morphology evidence explicitly states that gene/pathway associations were not calculated.
- Clinical phenotype metadata covers 8 tumor and 9 control samples. Tumor stage, primary diagnosis, and ICD-O morphology are recorded for all 8 tumors; grade is missing in all 8. There are no pathology image records or image-derived features, so no image-based or inferential morphology claims are made.
- Run-wide PPI acquisition/conservation, Phase 5 ORM persistence, integrated multi-evidence risk, and the multi-evidence Network Explorer remain unimplemented. Phase 5 remains partial; no synthetic PPI or morphology results are generated.

See `IMPLEMENTATION_AUDIT_PHASE5.md` for the detailed completed/remaining scope, score configuration, provenance, and scientific limitations.

## Mouse healthy network and module results

Status: added and verified for run `1c782941-d15c-4c3a-a291-5172f1d23937`.

- Added the acquired normal mouse mammary cohort GSE116385 as a separate reference dataset linked to this run. Its 8 samples cover adult basal, fetal mammary stem, luminal progenitor, and mature luminal cells. The network input uses 15,264 uniquely mapped mouse one-to-one Ensembl genes at log2(RPKM + 1).
- Persisted a real `mouse_healthy` network with 1,000 nodes and 48,439 edges, plus 6 Louvain modules containing 992 genes. The network and module records are visible through the same APIs and frontend selectors as the other run networks.
- The cohort remains explicitly identified as an independent study; it is not a matched normal control for GSE155577. Mouse healthy module DEG statistics are therefore not inferred or filled from the exploratory cross-study DEG comparison.
- Mouse network gene symbols are backfilled from the existing one-to-one Ensembl mapping when the database catalogue lacks them. The module table now falls back to stable IDs and network node stats if API ID forms differ, displays the assigned module key for hard Louvain membership, and explains why matched mouse DEG fields are unavailable.
- Direct API checks returned the mouse healthy network, module genes with Ensembl IDs and symbols, and node metrics. The run manifest and network/module CSVs include the added cohort and results.
