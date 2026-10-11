# Phase 5 Implementation Audit

## Scope and guardrails

This audit compares the requested Phase 5 feature set with the current repository and the saved run `1c782941-d15c-4c3a-a291-5172f1d23937`. Phase 1–4 code and persisted outputs are upstream inputs and must remain compatible. No demo biological records or placeholder scientific outputs are acceptable. Biomarker identification is included as a research-only candidate prioritization output, not a clinical diagnostic or risk claim.

## Implementation progress

The first evidence-only Phase 5 slice is now implemented and executed for the saved run:

- `pathdrift phase5 --run-id <run-id> [--force]` reads completed Phase 3/4 artifacts and writes run-scoped gene-loss evidence/scores, high-priority pairs, biomarker candidates, figures, and a phase summary. Re-running without `--force` returns the saved summary; `--force` regenerates the outputs.
- Gene-loss scores use configured weights for human cancer downregulation (FDR ≤ 0.05 and log2FC ≤ -1.0) and Phase 4 network drift. Missing evidence is excluded and remaining weights are renormalized; mouse expression is reported as exploratory and excluded from scoring. The existing legacy gene-loss score is not reused.
- Biomarker candidates must pass the configured human DEG thresholds (FDR ≤ 0.05 and |log2FC| ≥ 1), have at least one additional evidence category, and have measured network support. Module membership and orthology provide context but cannot qualify a DEG by themselves. Candidates are ordered by evidence-category count, adjusted p-value, then absolute fold change; there is no composite biomarker score or clinical claim.
- Multi-metric hub tables are generated for human cancer, human healthy, mouse cancer, and mouse healthy networks. Hub support requires an assigned module, at least two available centrality/connectivity metrics, and a mean within-module percentile ≥ 0.90.
- Authenticated run-scoped summary/table APIs and a Biomarker Candidates UI page expose the saved output.
- Local pathway analysis now uses versioned GO, Reactome, and species-specific WikiPathways snapshots. The saved run generated 179,959 ORA rows across 30 gene sets and 18,200 unique input IDs, plus 2,974 pathway comparisons, including 2,224 meeting the key-drift criteria. The ORA universe is restricted to database-mapped expressed genes; GSEA is supported locally but was not run.
- Candidate exports now replace obsolete pathway-unavailable text with computed overlap evidence and describe morphology as untested rather than unavailable where clinical metadata exists. Pathology summaries list only fields with observed values.
- Run-scoped pathway-enrichment, key-drift, and descriptive morphology results are exposed in the UI and filesystem artifacts. For the saved run, 8 tumor and 9 control samples have descriptive clinical metadata; stage, diagnosis, and ICD-O morphology are recorded for the 8 tumors, grade is missing, and there are no image records or image-derived features.
- For the target run, execution produced 134 ortholog-pair evidence rows, 134 scored pairs, 27 pairs above the configured high-priority threshold, and 48 eligible biomarker research candidates from 6,116 significant human DEGs. Hub metrics cover 1,000 nodes in each of the four networks; hub-supported counts are 1 human-cancer, 31 human-healthy, 11 mouse-cancer, and 7 mouse-healthy genes. Real-data output also includes a risk-distribution figure and candidate volcano plot.
- Run-wide PPI evidence and image-derived morphology features remain unavailable. Clinical pathology fields are descriptive only; no gene/pathway morphology association is inferred. The summary status remains `PARTIAL`.
- The generated pathway-comparison files retain counts and scores without embedding enormous per-pathway gene-ID lists; enrichment rows and the one-to-one orthology artifact retain the underlying gene-level evidence.

## Reusable components

- Phase 1–4 run manifests, access checks, filesystem CSV readers, and run-scoped API helpers are in `backend/app/services/filesystem_runs.py`, `backend/app/api/routes/phase3.py`, and `backend/app/api/routes/phase4.py`.
- Phase 3 emits saved DEG, network, module, and integrated gene tables under `results/runs/<run_id>/`.
- Phase 4 emits complete orthology, node/edge alignment, gene/module drift tables, summaries, provenance, and figures under `results/runs/<run_id>/orthology`, `cross_species`, and `drift`.
- Existing gene-loss evidence helpers are in `backend/app/bio/gene_loss.py`; existing gene-loss routes are comparison-scoped and consume database records and historical file paths.
- `backend/app/bio/ppi.py` normalizes actual STRING physical-interaction responses, filters self-loops and duplicate undirected edges, and applies configured confidence cutoffs. `backend/app/api/routes/ppi.py` currently fetches a live network for one query gene; it does not persist run-wide PPI networks.
- Run-scoped local pathway generation is in `pathdrift/phase5/pathways.py` and `pathdrift/phase5/service.py`; run-scoped APIs are in `backend/app/api/routes/phase5.py`.
- Existing UI includes gene-loss, PPI, morphology, pathways, key-drifted-pathways, and Phase 3/4 explorer pages, but most Phase 5 pages are wired to project/legacy endpoints rather than the filesystem artifacts of this saved run.
- `pathdrift/__main__.py` now supports the aggregate `phase5` command. Individual stage commands are not yet implemented.

## Missing or incomplete components

- Run-scoped filesystem artifacts, gene-loss evidence/scores, high-priority pairs, multi-metric hub tables, and DEG-qualified human biomarker candidates are implemented. Outputs are not yet persisted as Phase 5 ORM records.
- No run-scoped PPI acquisition/conservation pipeline exists; current STRING access is an on-demand single-seed API call.
- No morphology image/feature artifacts are present for the saved run. The image summary helper accepts user image data but is not a validated histopathology pipeline. Phase 5 must record morphology as unavailable unless real, compatible image features are supplied.
- The new gene-loss scoring is missing-aware for its two configured components. PPI/pathway-informed integrated risk and the Phase 5 ORM persistence model/migration remain unimplemented. The existing `GeneLossRiskModel` still must not be reused as-is for scientific run-level scores.
- The ORM currently has Phase 1–4 run entities and legacy analysis-scoped entities, but no run-scoped Phase 5 GeneLoss, PPI, Morphology, Pathway, or Risk persistence models. Phase 5 artifacts remain filesystem-backed.
- Biomarker candidates now have a run-scoped artifact/API and a dedicated UI page. Candidates are explicitly research-only, sorted by evidence-category count, adjusted p-value, then absolute log2 fold change, without clinical validation. Drift and edge-change categories derive from related network comparisons and do not constitute independent validation.
- Hub metric tables have a run-scoped API and a dedicated page with network tabs for both species and health states. Hub status is withheld when fewer than two metrics or no module assignment are available.
- Existing project-level Network Explorer and PPI UI are not the run-scoped multi-evidence Network Explorer specified by Phase 5. GSEA is implemented as an opt-in local mode and has not been executed for this run.

## Database and migration requirements

- Add run-scoped models for gene-loss evidence/scores, PPI networks/edges, morphology provenance/features where available, pathway enrichment/drift membership, integrated risk evidence, and (if materialized) biomarker candidates. Link all records to `analysis_runs` and preserve raw evidence, source identifiers, and provenance.
- Add a forward-only Alembic migration; do not modify existing Phase 1–4 schema semantics.
- Store scoring configuration, configured/effective weights, thresholds, components, missing-evidence fields, database/source versions, and `evidence_summary`.
- Enforce unique constraints for source-qualified PPI undirected edges and per-run gene/pathway result keys. Index run, species, identifiers, categories, and adjusted p-values.

## Scientific dependencies and constraints

- Phase 4 cross-species inputs are actual Ensembl Compara release 116 mappings and saved network/drift tables.
- PPI requires configured authoritative data (proposed source: STRING physical interaction data) and reproducible retrieval/version metadata. Existing live STRING endpoint is not a complete run-level acquisition source.
- Pathway enrichment requires an authoritative, versioned pathway gene-set source and multiple-testing correction. Preserve universe, overlap, raw p-value, adjusted p-value, and source/version.
- Morphology cannot produce measurements for this run without real images/features; mark unavailable and omit morphology from score weights rather than filling with zeros.
- Biomarker candidates should be based on actual human DEG and network evidence and, when available, orthology/conservation and pathway context. Report candidate evidence and selection criteria transparently; do not label candidates clinically validated or claim causal effects.
- The saved run has substantial cross-species network-size/density differences (human cancer: 466 edges; mouse cancer: 181,915 edges). Edge gain/loss categories must be interpreted with this limitation and not treated as independent statistical evidence or gene deletion.

## API and frontend requirements

- Implemented API surface is under `/runs/{run_id}/phase5/`, including summary and paginated gene-loss, biomarker, hub, pathway enrichment, key-drift, and phenotype artifact endpoints.
- Biomarker Candidates, Hub Genes, Pathway Enrichment, Key Drifted Pathways, and Morphology pages consume run-scoped artifacts and label evidence limitations. Dedicated PPI, integrated-risk, and multi-evidence Network Explorer endpoints/pages remain outstanding.
- Network Explorer must return bounded real nodes/edges and references to orthology, drift, PPI, pathway, and risk evidence; arbitrary graph values or placeholder nodes are forbidden.

## Outputs required under `results/runs/<run_id>/`

- `gene_loss/gene_loss_scores.csv`, `gene_loss/gene_loss_evidence.csv`, `gene_loss/high_risk_genes.csv`, `gene_loss/summary.json`
- `ppi/human_edges.csv`, `mouse_edges.csv`, `conserved_edges.csv`, `lost_edges.csv`, `gained_edges.csv`, `ppi_gene_statistics.csv`, `ppi_summary.json`
- `morphology/image_manifest.csv`, `morphology_features.csv`, `morphology_summary.json`, `morphology_feature_distributions.csv` only when actual source data exist; otherwise a summary explicitly states unavailable.
- `pathways/pathways_summary.json`, `gene_sets.csv`, `enrichment_results.csv`, `pathway_comparisons.csv`, `key_drifted_pathways.csv`, `gsea_results.csv`, `provenance.json`, and descriptive morphology artifacts are generated. GSEA is empty unless explicitly requested.
- `biomarkers/candidate_biomarkers.csv`, `biomarkers/summary.json`, gene-loss output tables, and `phase5_summary.json` are generated. `gene_loss_risk_distribution.png` and `candidate_volcano.png` are generated from real saved data. Figure registry/database registration and a complete multi-evidence risk table remain outstanding.

## CLI and validation requirements

- Implemented CLI command is restartable `pathdrift phase5 --run-id ...`; individual stage commands remain outstanding.
- Focused tests cover score behavior with missing evidence, biomarker evidence selection, artifact generation, pathway FDR and comparison behavior, phenotype metadata, and API pagination. PPI mapping/conservation, ORM persistence, and API authorization-specific Phase 5 tests remain outstanding.
- Verify actual output row counts and resource provenance when a real-data stage completes. Do not claim real PPI/pathway/morphology evidence when the corresponding source was unavailable.

## Recommended implementation order

1. Add versioned run-wide PPI acquisition, persistence, and ortholog-aware conservation from a selected source.
2. Integrate pathway evidence into research prioritization and add the remaining multi-evidence risk outputs.
3. Design ORM models/migration for Phase 5 results, register generated figures, and provide complete run-scoped APIs.
4. Connect gene-loss, PPI, morphology, pathway, risk, and bounded Network Explorer pages to run-scoped results.
5. Add integrated risk and individual restartable stage commands with explicit missing-evidence behavior.
6. Keep morphology unavailable for this run unless real compatible images/features are supplied; do not create synthetic outputs.
7. Extend tests to source mapping/conservation, pathway FDR, ORM persistence, API authorization, restartability, and end-to-end behavior.
