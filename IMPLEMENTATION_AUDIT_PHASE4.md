# Phase 4 implementation audit

## Existing reusable components

- `backend/app/models/models.py` defines the gene catalogue, global `OrthologyMapping`, and run-scoped Phase 3 tables: `RunGeneNetwork`, `RunNetworkNode`, `RunNetworkEdge`, `RunNetworkModule`, and `RunModuleGene`.
- `pathdrift/phase3_repository.py` persists run-scoped Phase 3 network, node, edge, module, and gene data. `pathdrift/phase3.py` records the network method, construction configuration, and summary.
- `backend/app/services/filesystem_runs.py` validates run manifests and provides the completed-run discovery rules.
- `backend/app/bio/orthology.py` has Ensembl ID mapping and a one-to-one ambiguity check. Its existing expression alignment remains one-to-one only.
- `backend/app/bio/cross_species.py` has legacy edge-alignment and per-gene relationship helpers, but consumes a different edge schema, drops ambiguous mappings, takes absolute weights, and does not report unmappable edges.
- `backend/app/bio/drift.py` computes within-species healthy-versus-cancer drift. `DriftAnalysis` and `CrossSpeciesAnalysis` are legacy analysis-scoped models, not run-scoped Phase 4 result models.
- `backend/app/api/routes/phase3.py` exposes run-scoped network and module data. Existing `/api/v1/cross-species` and `/api/v1/drift` routes use the legacy `Analysis` workflow.
- `pathdrift/__main__.py` is the CLI entry point; it currently supports Phase 2/3 commands, not Phase 4 commands.

## Existing orthology inputs and source

- `data/pathdrift/raw/orthology/ensembl_one_to_one.tsv` contains Ensembl Compara one-to-one pairs and reports release 116 in its data. The Ensembl REST `/info/data` endpoint also reported release 116 during this audit.
- The bundled file contains only one-to-one relationships; it cannot satisfy reporting of the other orthology types. Phase 4 must retrieve the needed mapping set from Ensembl Compara or fail clearly.
- `OrthologyMapping` already stores the pair, symbols, type, confidence, source version, and load timestamp, with a pair uniqueness constraint. It lacks an explicit source field and source metadata.

## Actual Phase 3 run checked

Run `1c782941-d15c-4c3a-a291-5172f1d23937` has completed human cancer, human healthy, and mouse cancer networks in PostgreSQL. The run-scoped cancer networks each have 1,000 nodes; the human cancer network has 466 edges and the mouse cancer network has 181,915 edges. Their construction method is Spearman; the saved configuration reports a minimum absolute correlation of 0.7 and adjusted-p-value threshold of 0.05.

CSV node/edge artifacts also exist under `results/runs/<run_id>/networks/`. The saved human and mouse cancer edge data use explicit Ensembl identifiers and include correlation, weight, p-value, and adjusted p-value columns. Phase 3 module tables and CSVs are also present.

The network densities are strongly different (466 vs. 181,915 edges at 1,000 nodes), so cross-species edge rates and weight changes require explicit qualification: equal nominal thresholds do not make the observed networks equally powered or equally dense. The comparison must preserve signed correlation and the actual method/configuration metadata.

## Gaps and required Phase 4 work

- Add strict Ensembl gene-ID normalization, complete source provenance, and classification/reporting for one-to-one, one-to-many, many-to-one, and many-to-many relationships.
- Add run-scoped node/edge alignment, gene drift, and module comparison computations. The old helpers do not cover this contract and must not silently collapse ambiguous mappings.
- Persist run-scoped Phase 4 outputs without duplicating the existing Phase 3 network/module tables. Extend the schema with migration-backed Phase 4 result storage where needed.
- Add authenticated run-scoped Phase 4 API endpoints and CLI stages with pagination, restartability, and `--force`.
- Export validated run artifacts and real-data figures, plus provenance and summary output. No DEG/frontend changes are required by this Phase 4 specification.

## Required output files

- `results/runs/<run_id>/orthology/`: ortholog pairs, summary, unmapped gene lists, and provenance.
- `results/runs/<run_id>/cross_species/`: node alignment, edge alignment, and network conservation summary.
- `results/runs/<run_id>/drift/`: gene, edge, and module results; status-specific edge tables; summary; provenance; and data-derived figures.
- `results/runs/<run_id>/cross_species_drift_summary.json`.

## Scientific assumptions and safeguards

- Only Ensembl stable IDs establish orthology; symbols are display metadata and never a matching key. Version suffixes may be removed for lookup but the original identifier must be preserved.
- The initial direct network comparison uses configurable, high-confidence one-to-one mappings. Non-one-to-one rows remain reportable but cannot be silently forced into a single-node correspondence.
- An edge is lost only if both endpoints have valid one-to-one correspondences. Otherwise it is unmappable. Mouse-only edges with valid mapped endpoints are species-specific/gained.
- Undirected edges are canonicalized once, self-loops and duplicates are rejected, and signed weights are retained. Weight differences are interpretable only alongside both networks' construction parameters.
- Gene absence, expression loss, network edge loss, network rewiring, and module disruption are distinct concepts. Phase 4 reports network topology only; pathway enrichment and biomarker claims are out of scope.
- Drift weights and category/module thresholds must be explicit configuration and emitted provenance. Empty/missing networks, orthology-source failures, invalid IDs, and database failures must be reported rather than replaced with synthetic scientific results.
