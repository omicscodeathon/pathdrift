# Phase 3 Frontend Audit

## Existing frontend

- Framework: React 18 with TypeScript, built by Vite.
- Routing: React Router v6 in `frontend/src/App.tsx`; authenticated routes render inside `Layout`.
- Sidebar: `frontend/src/components/Layout.tsx`, using Material UI Drawer/List and a grouped navigation model. It is responsive and highlights the active path.
- State: Zustand stores authentication and the current project/analysis/workflow IDs. The dashboard selects a project and analysis; there was no selected `AnalysisRun` state.
- API client: `frontend/src/api/client.ts` centralizes Axios requests under `/api/v1`, adds the JWT from local storage, and redirects on 401.
- Data fetching: React Query in pages.
- Existing analysis pages: `DEGPage.tsx`, `NetworksPage.tsx`, and `NetworkModulesPage.tsx` operate on legacy project/analysis-scoped endpoints. They are retained to avoid breaking current workflows.
- Existing run/QC pages: `RunQCPage.tsx` uses the run API for QC, not the run-scoped Phase 3 result API.
- Authentication: `RequireAuth` in `App.tsx` checks the persisted auth token; the Axios client sends it.
- Visualization and design system: Material UI, Plotly (`react-plotly.js`), Cytoscape (`react-cytoscapejs`), and the existing light theme in `App.tsx`.
- Loading/error/empty states: pages use React Query status and Material UI Alerts, LinearProgress, and empty-state panels.

## Phase 3 API and reuse

The backend registers the run-scoped Phase 3 router at `/api/v1/runs` and exposes DEG, network, module, and analysis-summary endpoints. The frontend can reuse its authenticated Axios client, React Query setup, theme, and visualization dependencies.

The new run-scoped routes are under `/runs/:runId/` and have a selected-run state in Zustand. A page without a run ID offers a picker populated from the existing project run-list API. Existing `/deg`, `/networks`, and `/network-modules` routes remain untouched.

## Files

- Reused: `App.tsx`, `Layout.tsx`, `api/client.ts`, `projectStore.ts`, Material UI, Plotly, Cytoscape.
- Added: `frontend/src/pages/Phase3Pages.tsx`, which exports run-scoped DEG, networks, network explorer, modules, module explorer, and integrated analysis pages.
- Documentation: this audit and `FRONTEND_PHASE3_IMPLEMENTATION.md`.

## Known limitations and API gaps

- Existing Phase 3 endpoints paginate DEG, nodes, edges, and module genes. The DEG visualization explicitly fetches all pages because a full volcano/MA plot requires the complete returned gene set; tables remain paginated.
- Network exploration loads only a bounded node/edge page rather than rendering the full graph. The current edge API does not provide gene-specific filtering, so selected-gene exploration uses the available bounded edge result.
- Integrated analysis joins the selected network's returned node page with the current DEG page and module assignments. It clearly represents this paginated view and does not claim to be an exhaustive integrated export.
- No run-scoped CSV export endpoint is available in the current Phase 3 API, so these pages do not fabricate browser-generated scientific exports.
- No frontend test runner is configured in `frontend/package.json`; TypeScript/build checks are the available verification gates.
