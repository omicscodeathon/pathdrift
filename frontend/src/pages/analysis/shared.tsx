import { useEffect, useState } from 'react'
import { Link as RouterLink, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { Alert, Box, Button, Chip, CircularProgress, LinearProgress, MenuItem, Paper, Stack, TextField, Typography } from '@mui/material'
import { useQuery } from '@tanstack/react-query'
import { phase3Api } from '@/api/client'
import { useProjectStore } from '@/store/projectStore'
import { useAuthStore } from '@/store/authStore'

export type Species = 'human' | 'mouse'
export type Phase3View = 'differential-expression' | 'networks' | 'network-explorer' | 'ppi-network' | 'modules' | 'module-explorer' | 'integrated-analysis' | 'cross-species' | 'orthology' | 'drift' | 'biomarkers' | 'gene-loss' | 'hub-genes' | 'pathways' | 'key-drifted-pathways' | 'morphology' | 'ml'
export type Page<T> = { items: T[]; total: number; limit: number; offset: number }
export type Run = { id: string; project_name?: string; status: string; stage: string; created_at: string; completed_at?: string | null; datasets: number }
export type RunDataset = { id: string; accession: string | null; name: string; species: Species; sample_count: number | null; gene_count: number | null }
export type DEG = {
  gene_id: string
  ensembl_id: string
  gene_symbol: string | null
  species: Species
  comparison: string
  log2fc: number | null
  pvalue: number | null
  adjusted_p_value: number | null
  statistic: number | null
  base_mean: number | null
  average_expression: number | null
  direction: string | null
  significant: boolean
  testable?: boolean
  method: string
  thresholds: Record<string, unknown> | null
}
export type IntegratedGene = {
  gene_id: string
  ensembl_id: string
  gene_symbol: string | null
  species: Species
  comparison: string
  log2fc: number | null
  pvalue: number | null
  adjusted_p_value: number | null
  base_mean: number | null
  average_expression: number | null
  direction: string | null
  significant: boolean
  degree: number | null
  weighted_degree: number | null
  betweenness_centrality: number | null
  closeness_centrality: number | null
  eigenvector_centrality: number | null
  module_id: string | null
}
export type Network = {
  network_id: string
  dataset_id: string
  name: string
  species: Species
  disease_state: string
  method: string
  summary: Record<string, unknown> | null
  configuration: Record<string, unknown> | null
}
export type NetworkNode = {
  gene_id: string
  ensembl_id: string
  gene_symbol: string | null
  degree: number
  weighted_degree: number
  betweenness_centrality: number | null
  closeness_centrality: number | null
  eigenvector_centrality: number | null
  module_id: string | null
}
export type Edge = {
  source_gene_id: string
  source_ensembl_id: string
  target_gene_id: string
  target_ensembl_id: string
  correlation: number
  absolute_correlation: number
  pvalue: number | null
  adjusted_p_value: number | null
  weight: number
}
export type Module = {
  module_id: string
  module_key: string
  network_id: string
  network_name: string
  species: Species
  size: number
  detection_method: string
  parameters: Record<string, unknown> | null
  statistics: Record<string, unknown> | null
}
export type ModuleGene = {
  gene_id: string
  ensembl_id: string
  gene_symbol: string | null
  membership: number | null
  degree?: number | null
  weighted_degree?: number | null
  betweenness_centrality?: number | null
  closeness_centrality?: number | null
  eigenvector_centrality?: number | null
}
export type Summary = {
  run_status: string
  phase3: Record<string, unknown>
  differential_expression: Array<{ species: Species; comparison: string; tested_genes: number; significant_genes: number }>
  networks: Array<{ network_id: string; name: string; species: Species; summary: Record<string, unknown> | null }>
  module_count: number
}

export const PAGE_SIZE = 50
export const DEG_FETCH_LIMIT = 5000
export const NETWORK_NODE_LIMIT = 100
export const NETWORK_EDGE_LIMIT = 200
export const MODULE_LIMIT = 500
export const CY_STYLE = [
  { selector: 'node', style: { 'background-color': '#1677a8', label: 'data(label)', color: '#fff', 'font-size': 9, width: 26, height: 26 } },
  { selector: 'node:selected', style: { 'background-color': '#c64a3b', 'border-width': 2, 'border-color': '#172554' } },
  { selector: 'edge', style: { width: 'mapData(weight, 0, 1, 0.5, 3)', 'line-color': '#94a3b8', opacity: 0.65 } },
]

export function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {}
}

export function numberValue(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

export function display(value: unknown): string {
  if (value == null || value === '') return 'Not provided'
  if (typeof value === 'number') return value.toLocaleString(undefined, { maximumFractionDigits: 4 })
  if (typeof value === 'string' || typeof value === 'boolean') return String(value)
  return JSON.stringify(value)
}

export function useRunContext(runId: string | undefined) {
  const userId = useAuthStore((state) => state.user?.id)
  const setCurrentRun = useProjectStore((state) => state.setCurrentRun)
  const { data: runs = [], isLoading: runsLoading, isError: runsError } = useQuery({
    queryKey: ['saved-analysis-runs', userId],
    queryFn: () => phase3Api.savedRuns().then((response) => response.data as Run[]),
  })
  const { data: summary, isLoading: summaryLoading, isError: summaryError } = useQuery({
    queryKey: ['phase3-summary', runId],
    queryFn: () => phase3Api.summary(runId!).then((response) => response.data as Summary),
    enabled: !!runId,
  })
  const { data: datasets = [], isLoading: datasetsLoading, isError: datasetsError } = useQuery({
    queryKey: ['phase3-datasets', runId],
    queryFn: () => phase3Api.datasets(runId!).then((response) => response.data as RunDataset[]),
    enabled: !!runId,
  })
  useEffect(() => {
    if (runId) setCurrentRun(runId)
  }, [runId, setCurrentRun])
  const run = runs.find((item) => item.id === runId)
  return {
    runs, run, summary, datasets,
    loading: runsLoading || summaryLoading || datasetsLoading,
    error: runsError || (!!runId && (summaryError || datasetsError)),
  }
}

export function RunSelector({ runId, runs, view }: { runId: string; runs: Run[]; view: Phase3View }) {
  const navigate = useNavigate()
  const setCurrentRun = useProjectStore((state) => state.setCurrentRun)
  return (
    <TextField
      select size="small" label="Analysis run" value={runId}
      onChange={(event) => {
        const id = event.target.value
        setCurrentRun(id)
        navigate(phase3RunPath(id, view))
      }}
      sx={{ minWidth: { xs: '100%', sm: 330 } }}
    >
        {!runs.some((run) => run.id === runId) && <MenuItem value={runId}>Current run · {runId}</MenuItem>}
        {runs.map((run) => <MenuItem key={run.id} value={run.id}>{run.project_name ?? 'Saved analysis'} · {new Date(run.created_at).toLocaleDateString()} · {run.status}</MenuItem>)}
    </TextField>
  )
}

export function phase3RunPath(runId: string, view: Phase3View) {
  return `/runs/${runId}/${view === 'differential-expression' ? 'deg' : view}`
}

export function RunHeader({ runId, view, title, subtitle }: { runId: string; view: Phase3View; title: string; subtitle: string }) {
  const context = useRunContext(runId)
  if (!runId) return <RunPicker />
  if (context.loading) return <LinearProgress sx={{ mb: 2 }} />
  if (context.error) return <Alert severity="error">Unable to load run context from the backend. Check that this run exists and that your account can access it.</Alert>
  return (
    <Paper variant="outlined" sx={{ p: 2, mb: 2.5 }}>
      <Stack direction={{ xs: 'column', md: 'row' }} justifyContent="space-between" alignItems={{ xs: 'stretch', md: 'center' }} spacing={2}>
        <Box>
          <Typography variant="h4" fontWeight={800}>{title}</Typography>
          <Typography color="text.secondary">{subtitle}</Typography>
        </Box>
        <RunSelector runId={runId} runs={context.runs} view={view} />
      </Stack>
      <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap" sx={{ mt: 1.5, alignItems: 'center' }}>
        <Chip size="small" label={`Run ${runId}`} />
        <Chip size="small" variant="outlined" label={`Status: ${context.summary?.run_status ?? context.run?.status ?? 'Not reported'}`} />
        {context.datasets.map((dataset) => (
          <Chip key={dataset.id} size="small" variant="outlined" label={`${dataset.accession ?? dataset.name} · ${dataset.species} · ${display(dataset.sample_count)} samples`} />
        ))}
      </Stack>
    </Paper>
  )
}

export function RunPicker() {
  const [searchParams] = useSearchParams()
  const currentRunId = useProjectStore((state) => state.currentRunId)
  const setCurrentRun = useProjectStore((state) => state.setCurrentRun)
  const userId = useAuthStore((state) => state.user?.id)
  const navigate = useNavigate()
  const requestedPage = searchParams.get('page') || 'differential-expression'
  const pages: Phase3View[] = ['differential-expression', 'networks', 'network-explorer', 'ppi-network', 'modules', 'module-explorer', 'integrated-analysis', 'cross-species', 'orthology', 'drift', 'biomarkers', 'gene-loss', 'hub-genes', 'pathways', 'key-drifted-pathways', 'morphology', 'ml']
  const page: Phase3View = pages.includes(requestedPage as Phase3View) ? requestedPage as Phase3View : 'differential-expression'
  const pageTitle: Record<Phase3View, string> = {
    'differential-expression': 'Differential Expression',
    networks: 'Gene Networks',
    'network-explorer': 'Network Explorer',
    'ppi-network': 'PPI Network',
    modules: 'Modules',
    'module-explorer': 'Module Explorer',
    'integrated-analysis': 'Integrated Analysis',
    'cross-species': 'Cross-Species Comparison',
    orthology: 'Orthology',
    drift: 'Network Drift',
    biomarkers: 'Biomarker Candidates',
    'gene-loss': 'Gene Loss Results',
    'hub-genes': 'Hub Genes',
    pathways: 'Pathway Enrichment',
    'key-drifted-pathways': 'Key Drifted Pathways',
    morphology: 'Morphology & Phenotypes',
    ml: 'Machine Learning',
  }
  const {
    data: runs = [],
    isLoading,
    isError,
  } = useQuery({
    queryKey: ['saved-analysis-runs', userId],
    queryFn: () => phase3Api.savedRuns().then((response) => response.data as Run[]),
  })
  useEffect(() => {
    if (isLoading || isError || !runs.length || runs.some((run) => run.id === currentRunId)) return
    const latestCompletedRun = runs.find((run) => run.status.toUpperCase() === 'COMPLETED')
    setCurrentRun(latestCompletedRun?.id ?? runs[0].id)
  }, [currentRunId, isError, isLoading, runs, setCurrentRun])
  return (
    <Paper variant="outlined" sx={{ p: 3 }}>
      <Typography variant="h5" fontWeight={700}>Choose a saved run for {pageTitle[page]}</Typography>
      <Typography color="text.secondary" sx={{ mb: 2 }}>Open the saved {pageTitle[page]} results from one of your completed analyses.</Typography>
      {isLoading && <LinearProgress />}
      {isError && <Alert severity="error">Could not load your saved analysis results.</Alert>}
      {!isLoading && !isError && !runs.length && (
        <Alert severity="info" action={<Button component={RouterLink} to="/" color="inherit" size="small">Go to Dashboard</Button>}>
          No saved analysis results are available for your account.
        </Alert>
      )}
      {!!runs.length && (
        <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1.5} alignItems="stretch">
          <TextField
            select
            label="Saved analysis"
            value={runs.some((run) => run.id === currentRunId) ? currentRunId! : ''}
            onChange={(event) => setCurrentRun(event.target.value || null)}
            fullWidth
          >
            {runs.map((run) => <MenuItem key={run.id} value={run.id}>{run.project_name ?? 'Saved analysis'} · {new Date(run.created_at).toLocaleString()} · {run.status}</MenuItem>)}
          </TextField>
          <Button
            variant="contained"
            disabled={!runs.some((run) => run.id === currentRunId)}
            onClick={() => navigate(phase3RunPath(currentRunId!, page))}
            sx={{ minWidth: 180 }}
          >
            Open {pageTitle[page]}
          </Button>
        </Stack>
      )}
    </Paper>
  )
}

export function useRunId() {
  return useParams<{ runId: string }>().runId
}

export function ResultState({ loading, error, empty, children }: { loading: boolean; error: boolean; empty: boolean; children: React.ReactNode }) {
  if (loading) return <Box sx={{ py: 4, textAlign: 'center' }}><CircularProgress /></Box>
  if (error) return <Alert severity="error">Could not load these results. The API request failed; refresh or choose another run.</Alert>
  if (empty) return <Alert severity="info">No saved results are available for this selection in the selected run.</Alert>
  return <>{children}</>
}

export function StatCard({ label, value }: { label: string; value: unknown }) {
  return <Paper variant="outlined" sx={{ p: 2, height: '100%' }}>
    <Typography variant="caption" color="text.secondary" fontWeight={700}>{label}</Typography>
    <Typography variant="h5" fontWeight={800} sx={{ mt: 0.5 }}>{display(value)}</Typography>
  </Paper>
}

export async function fetchAllDeg(runId: string, species: Species, comparison?: string): Promise<DEG[]> {
  const first = await phase3Api.deg(runId, { species, comparison, limit: DEG_FETCH_LIMIT, offset: 0 })
  const page = first.data as Page<DEG>
  const offsets = Array.from({ length: Math.ceil(Math.max(0, page.total - page.items.length) / DEG_FETCH_LIMIT) }, (_, i) => (i + 1) * DEG_FETCH_LIMIT)
  const rest: DEG[] = []
  for (let index = 0; index < offsets.length; index += 5) {
    const responses = await Promise.all(offsets.slice(index, index + 5).map((offset) =>
      phase3Api.deg(runId, { species, comparison, limit: DEG_FETCH_LIMIT, offset }),
    ))
    rest.push(...responses.flatMap((response) => (response.data as Page<DEG>).items))
  }
  return [...page.items, ...rest]
}

export async function fetchAllIntegrated(runId: string, species: Species): Promise<IntegratedGene[]> {
  const first = await phase3Api.integrated(runId, { species, limit: 500, offset: 0 })
  const page = first.data as Page<IntegratedGene>
  const offsets = Array.from({ length: Math.ceil(Math.max(0, page.total - page.items.length) / 500) }, (_, i) => (i + 1) * 500)
  const rest: IntegratedGene[] = []
  for (let index = 0; index < offsets.length; index += 5) {
    const responses = await Promise.all(offsets.slice(index, index + 5).map((offset) =>
      phase3Api.integrated(runId, { species, limit: 500, offset }),
    ))
    rest.push(...responses.flatMap((response) => (response.data as Page<IntegratedGene>).items))
  }
  return [...page.items, ...rest]
}

export function useObjectUrl(blob: Blob | undefined) {
  const [url, setUrl] = useState<string>()
  useEffect(() => {
    if (!blob) {
      setUrl(undefined)
      return
    }
    const nextUrl = URL.createObjectURL(blob)
    setUrl(nextUrl)
    return () => URL.revokeObjectURL(nextUrl)
  }, [blob])
  return url
}

export function useSpeciesComparisons(runId: string | undefined) {
  const { data: summary, isLoading, isError } = useQuery({
    queryKey: ['phase3-summary', runId],
    queryFn: () => phase3Api.summary(runId!).then((response) => response.data as Summary),
    enabled: !!runId,
  })
  return { comparisons: summary?.differential_expression ?? [], summary, isLoading, isError }
}

export function useNetworks(runId: string | undefined) {
  return useQuery({
    queryKey: ['phase3-networks', runId],
    queryFn: () => phase3Api.networks(runId!).then((response) => (response.data as { items: Network[] }).items),
    enabled: !!runId,
  })
}

export function summaryValue(summary: Record<string, unknown> | null, ...keys: string[]) {
  const record = asRecord(summary)
  for (const key of keys) if (record[key] != null) return record[key]
  return null
}

export function useAllModules(runId: string | undefined) {
  return useQuery({
    queryKey: ['phase3-modules', runId],
    queryFn: () => phase3Api.modules(runId!, { limit: MODULE_LIMIT, offset: 0 }).then((response) => response.data as Page<Module>),
    enabled: !!runId,
  })
}

export function useSelectedModule(runId: string | undefined) {
  const { data, isLoading, isError } = useAllModules(runId)
  const [searchParams, setSearchParams] = useSearchParams()
  const moduleId = searchParams.get('module') ?? ''
  const choose = (id: string) => setSearchParams((params) => { params.set('module', id); return params }, { replace: true })
  const selected = data?.items.find((module) => module.module_id === moduleId)
  const detail = useQuery({
    queryKey: ['phase3-module-detail', runId, moduleId],
    queryFn: () => phase3Api.module(runId!, moduleId).then((response) => response.data as Module),
    enabled: !!runId && !!moduleId,
  })
  const genes = useQuery({
    queryKey: ['phase3-module-genes', runId, moduleId],
    queryFn: () => phase3Api.moduleGenes(runId!, moduleId, 500, 0).then((response) => response.data as Page<ModuleGene>),
    enabled: !!runId && !!moduleId,
  })
  return { data, isLoading, isError, moduleId, choose, selected, detail, genes }
}
