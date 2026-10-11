# Phase 3 Frontend

## Pages and routes

The run-scoped Phase 3 screens are authenticated React Router pages:

- `/runs/:runId/differential-expression`
- `/runs/:runId/networks`
- `/runs/:runId/network-explorer`
- `/runs/:runId/modules`
- `/runs/:runId/module-explorer`
- `/runs/:runId/integrated-analysis`

The sidebar has a **PHASE 3 — Biological Analysis** section with links to all six pages. When a run is already selected, navigation opens that run directly. Otherwise, `/phase3/select?page=...` presents runs from the active project. The run selector on each page allows switching runs; changing project clears the selected run. Existing project-scoped pages and their routes remain available under distinct sidebar labels.

## API and data handling

All result requests use the authenticated Axios client in `frontend/src/api/client.ts` and React Query. The `phase3Api` client methods consume:

- `/api/v1/runs/project/{project_id}` and `/api/v1/runs/{run_id}/datasets`
- `/api/v1/runs/{run_id}/analysis-summary`
- `/api/v1/runs/{run_id}/deg`
- `/api/v1/runs/{run_id}/networks` and its network, nodes, and edges routes
- `/api/v1/runs/{run_id}/modules` and its module and genes routes

Scientific values are rendered from API responses. The run header shows the selected run, its backend status, and datasets associated with that run. No fixed run ID or scientific sample values are embedded in the UI.

## Functionality

- **Differential Expression:** species/comparison selection, backend-derived comparison metadata and counts, full-row DEG retrieval in bounded batches for volcano and MA charts, searchable/filterable/sortable table with client-side pagination, and links to the selected species' run network. The mouse cross-study comparison is clearly marked exploratory.
- **Gene Networks:** cards for existing networks only, showing available backend network statistics and configuration, with links to network exploration and modules.
- **Network Explorer:** network selection, search within a bounded node page, a user-controlled absolute-correlation threshold and neighbor limit, selected-gene centrality/module display, neighbor table, and a Cytoscape subgraph constructed only from returned node/edge rows.
- **Modules:** module search, species filtering, backend-reported sizes/statistics, and module-to-explorer navigation.
- **Module Explorer:** module selection, search/filter/sort for member genes, DEG and network-node annotations when returned by the APIs, and a bounded Cytoscape view from saved network rows.
- **Integrated Analysis:** interactive species/network/module/gene selection, DEG significance/direction, minimum absolute log2FC, maximum adjusted p-value, minimum degree, and sorting by DEG or available centrality. It joins backend DEG rows with the selected network's paginated node rows and provides links to network/module views.

Material UI provides layout, controls, tables, and accessible status messages. Plotly renders DEG charts; Cytoscape renders bounded network views.

## Loading, errors, empty states, and exports

Pages report loading, API errors, and empty result sets separately. Missing scientific values are displayed as unavailable rather than as zero. The backend currently exposes no run-scoped CSV/JSON export endpoints, so the frontend does not synthesize exports.

The network explorer deliberately requests at most 100 nodes and 200 edges initially. The module explorer requests at most 500 module genes/nodes and 200 edges. The integrated view joins at most 500 selected-network nodes. DEG charts fetch all rows for the selected comparison through API pages, in batches of five requests, because plotting only a page would misrepresent the comparison.

## Validation and limitations

`npm --prefix frontend run type-check` and `npm --prefix frontend run build` are the frontend validation commands. No frontend unit-test runner is configured in `frontend/package.json`.

The current Phase 3 API has no symbol-search endpoint for all network nodes, no edge filter by selected gene, and no full unpaginated centrality/module export. Therefore network searches and visualizations are explicitly limited to data returned by the bounded pages. The integrated view is a paginated exploration view, not a complete all-network gene export or a new scientific analysis. No Phase 4 drift calculation is performed here.
