import { useEffect, useMemo, useState } from 'react'
import {
  Alert, Box, Button, Chip, CircularProgress, Divider, Grid, LinearProgress,
  MenuItem, Paper, Stack, Table, TableBody, TableCell, TableContainer,
  TableHead, TableRow, TextField, Typography, TablePagination,
} from '@mui/material'
import Plot from 'react-plotly.js'
import { useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useSnackbar } from 'notistack'
import { crossSpeciesApi, driftApi, networkApi, phase4Api } from '@/api/client'
import type { DriftResult, GeneNetwork, Species } from '@/types'
import { useProjectStore } from '@/store/projectStore'
import { asRecord, RunHeader } from '@/pages/analysis/shared'

interface DriftSummary {
  drift_id: string
  species: Species
  status: string
  global_drift_score: number | null
  n_conserved_edges: number | null
  n_gained_edges: number | null
  n_lost_edges: number | null
  total_genes: number
  distribution: Array<{ low: number; high: number; count: number }>
  top_genes: Array<{
    gene_id: string
    symbol: string | null
    drift_score: number
    module: string | null
    degree_change: number | null
  }>
}

interface GeneRelationship {
  neighbor_id: string
  symbol?: string | null
  weight?: number
  normal_weight?: number
  cancer_weight?: number
}

interface SpeciesGeneDrift {
  gene_id: string | null
  symbol: string | null
  message: string | null
  relationships: {
    normal_edges: GeneRelationship[]
    cancer_edges: GeneRelationship[]
    lost_relationships: GeneRelationship[]
    gained_relationships: GeneRelationship[]
    rewired_relationships: GeneRelationship[]
    drift_types: string[]
  } | null
}

interface PairedGeneDrift {
  human: SpeciesGeneDrift
  mouse: SpeciesGeneDrift
  drift_types: string[]
}

const SPECIES_COLORS = { human: '#1677a8', mouse: '#be5a32' }

function LegacyDriftPage() {
  const { enqueueSnackbar } = useSnackbar()
  const queryClient = useQueryClient()
  const {
    currentProjectId, currentAnalysisId, healthyNetworkId, diseaseNetworkId,
    humanDriftId, mouseDriftId, crossSpeciesId, setWorkflowIds,
  } = useProjectStore()
  const [species, setSpecies] = useState<Species>('human')
  const [selectedDriftId, setSelectedDriftId] = useState('')
  const [healthyNetwork, setHealthyNetwork] = useState(healthyNetworkId ?? '')
  const [diseaseNetwork, setDiseaseNetwork] = useState(diseaseNetworkId ?? '')
  const [selectedGeneId, setSelectedGeneId] = useState('')

  const { data: networks = [] } = useQuery({
    queryKey: ['networks', currentProjectId],
    queryFn: () => currentProjectId ? networkApi.listForProject(currentProjectId).then((response) => response.data as GeneNetwork[]) : [],
    enabled: !!currentProjectId,
  })
  const speciesNetworks = networks.filter((network) => network.species === species && network.status === 'completed')
  const normalNetworks = speciesNetworks.filter((network) => network.disease_state === 'healthy')
  const cancerNetworks = speciesNetworks.filter((network) => ['cancer', 'early_cancer', 'intermediate', 'advanced'].includes(network.disease_state))

  useEffect(() => {
    const nextHealthy = normalNetworks.find((network) => network.id === healthyNetworkId)?.id ?? normalNetworks[0]?.id ?? ''
    const nextCancer = cancerNetworks.find((network) => network.id === diseaseNetworkId)?.id ?? cancerNetworks[0]?.id ?? ''
    if (!normalNetworks.some((network) => network.id === healthyNetwork)) setHealthyNetwork(nextHealthy)
    if (!cancerNetworks.some((network) => network.id === diseaseNetwork)) setDiseaseNetwork(nextCancer)
  }, [cancerNetworks, diseaseNetwork, diseaseNetworkId, healthyNetwork, healthyNetworkId, normalNetworks])

  const { data: driftResults = [], isLoading: driftResultsLoading } = useQuery({
    queryKey: ['project-drift-results', currentProjectId],
    queryFn: () => currentProjectId ? driftApi.listForProject(currentProjectId).then((response) => response.data as DriftResult[]) : [],
    enabled: !!currentProjectId,
    refetchInterval: (query) => query.state.data?.some((result) => result.status === 'queued' || result.status === 'running') ? 4000 : false,
  })
  const matchingDrifts = driftResults.filter((result) => result.species === species)

  useEffect(() => {
    if (matchingDrifts.some((result) => result.id === selectedDriftId)) return
    const preferredId = species === 'human' ? humanDriftId : mouseDriftId
    const preferred = matchingDrifts.find((result) => result.id === preferredId)
    setSelectedDriftId(preferred?.id ?? matchingDrifts[0]?.id ?? '')
    setSelectedGeneId('')
  }, [humanDriftId, matchingDrifts, mouseDriftId, selectedDriftId, species])

  const { data: driftResult } = useQuery({
    queryKey: ['drift-result', selectedDriftId],
    queryFn: () => driftApi.get(selectedDriftId).then((response) => response.data as DriftResult),
    enabled: !!selectedDriftId,
    refetchInterval: (query) => {
      const status = (query.state.data as DriftResult | undefined)?.status
      return status === 'queued' || status === 'running' ? 3000 : false
    },
  })
  const { data: driftSummary, isLoading: summaryLoading, isError: summaryError } = useQuery({
    queryKey: ['drift-summary', selectedDriftId],
    queryFn: () => driftApi.getSummary(selectedDriftId).then((response) => response.data as DriftSummary),
    enabled: !!selectedDriftId && driftResult?.status === 'completed',
  })
  const { data: crossSpeciesResults = [] } = useQuery({
    queryKey: ['cross-species-results', currentProjectId],
    queryFn: () => currentProjectId ? crossSpeciesApi.listForProject(currentProjectId).then((response) => response.data) : [],
    enabled: !!currentProjectId && !!selectedGeneId,
  })
  const selectedComparison = crossSpeciesResults.find((comparison: {
    id: string; human_drift_id: string; mouse_drift_id: string; status: string
  }) => comparison.status === 'completed' && (
    species === 'human' ? comparison.human_drift_id === selectedDriftId : comparison.mouse_drift_id === selectedDriftId
  )) ?? crossSpeciesResults.find((comparison: { id: string; status: string }) => comparison.id === crossSpeciesId && comparison.status === 'completed')
  const { data: geneDrift, isLoading: geneDriftLoading } = useQuery({
    queryKey: ['cross-species-gene-network-drift', selectedComparison?.id, selectedGeneId, species],
    queryFn: () => crossSpeciesApi.getGeneNetworkDrift(selectedComparison.id, selectedGeneId, species).then((response) => response.data as PairedGeneDrift),
    enabled: !!selectedComparison && !!selectedGeneId,
  })

  const runMutation = useMutation({
    mutationKey: ['drift', 'run'],
    mutationFn: () => {
      if (!currentAnalysisId || !healthyNetwork || !diseaseNetwork) throw new Error('Select an analysis and both networks')
      return driftApi.run({
        analysis_id: currentAnalysisId,
        healthy_network_id: healthyNetwork,
        disease_network_id: diseaseNetwork,
        species,
      })
    },
    onSuccess: (response) => {
      const job = response.data as { id: string; result_ref?: string }
      const resultId = job.result_ref ?? job.id
      setSelectedDriftId(resultId)
      setWorkflowIds(species === 'human' ? { humanDriftId: resultId } : { mouseDriftId: resultId })
      setSelectedGeneId('')
      queryClient.invalidateQueries({ queryKey: ['project-drift-results', currentProjectId] })
      enqueueSnackbar('Network drift analysis queued', { variant: 'info' })
    },
    onError: () => enqueueSnackbar('Failed to start drift analysis', { variant: 'error' }),
  })

  const topGenes = driftSummary?.top_genes ?? []
  const histogramTrace = useMemo(() => [{
    type: 'bar' as const,
    x: driftSummary?.distribution.map((bin) => (bin.low + bin.high) / 2) ?? [],
    y: driftSummary?.distribution.map((bin) => bin.count) ?? [],
    width: driftSummary?.distribution.map((bin) => (bin.high - bin.low) * 0.84) ?? [],
    marker: { color: '#b65e42' },
    customdata: driftSummary?.distribution.map((bin) => [bin.low, bin.high]) ?? [],
    hovertemplate: 'Score %{customdata[0]:.2f}–%{customdata[1]:.2f}<br>%{y} genes<extra></extra>',
  }], [driftSummary])

  const formatRelationships = (edges: GeneRelationship[] | undefined, prefix: string) => edges?.length
    ? edges.slice(0, 8).map((edge) => (
        <Stack key={`${prefix}-${edge.neighbor_id}`} direction="row" justifyContent="space-between" alignItems="center" spacing={1} sx={{ py: 0.65, borderBottom: '1px solid', borderColor: 'divider' }}>
          <Typography variant="body2" sx={{ fontFamily: 'monospace', overflowWrap: 'anywhere' }}>
            {prefix} ── {edge.symbol || edge.neighbor_id}
          </Typography>
          <Typography variant="caption" color="text.secondary">{edge.weight?.toFixed(2) ?? ''}</Typography>
        </Stack>
      ))
    : <Typography variant="body2" color="text.secondary">No recorded edges for this gene.</Typography>

  const stateLabel = (network: GeneNetwork) => network.disease_state === 'healthy' ? 'Normal' : network.disease_state.replace('_', ' ')

  return (
    <Box sx={{ maxWidth: 1320, mx: 'auto' }}>
      <Typography variant="h4" fontWeight={800} gutterBottom>NETWORK DRIFT</Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2.5 }}>
        Quantify topology and edge-weight changes from normal to disease, then inspect the relationships behind each score.
      </Typography>

      <Paper variant="outlined" sx={{ p: 2, mb: 2.5 }}>
        <Grid container spacing={1.5} alignItems="center">
          <Grid item xs={6} md={2}>
            <TextField select fullWidth size="small" label="Species" value={species} onChange={(event) => { setSpecies(event.target.value as Species); setSelectedGeneId('') }}>
              <MenuItem value="human">Human</MenuItem><MenuItem value="mouse">Mouse</MenuItem>
            </TextField>
          </Grid>
          <Grid item xs={12} md={3}>
            <TextField select fullWidth size="small" label="Normal network" value={healthyNetwork} onChange={(event) => setHealthyNetwork(event.target.value)} disabled={!normalNetworks.length}>
              {normalNetworks.map((network) => <MenuItem key={network.id} value={network.id}>{network.name}</MenuItem>)}
            </TextField>
          </Grid>
          <Grid item xs={12} md={3}>
            <TextField select fullWidth size="small" label="Disease network" value={diseaseNetwork} onChange={(event) => setDiseaseNetwork(event.target.value)} disabled={!cancerNetworks.length}>
              {cancerNetworks.map((network) => <MenuItem key={network.id} value={network.id}>{network.name}</MenuItem>)}
            </TextField>
          </Grid>
          <Grid item xs={6} md={2}>
            <Button variant="contained" fullWidth onClick={() => runMutation.mutate()} disabled={!currentAnalysisId || !healthyNetwork || !diseaseNetwork || runMutation.isPending}>
              {runMutation.isPending ? <CircularProgress size={19} color="inherit" /> : 'Run Drift'}
            </Button>
          </Grid>
          <Grid item xs={12} md={2}>
            <TextField select fullWidth size="small" label="Saved drift result" value={selectedDriftId} onChange={(event) => { setSelectedDriftId(event.target.value); setSelectedGeneId('') }} disabled={!matchingDrifts.length}>
              {matchingDrifts.map((result) => (
                <MenuItem key={result.id} value={result.id}>{result.status} · {new Date(result.created_at).toLocaleDateString()}</MenuItem>
              ))}
            </TextField>
          </Grid>
          {!currentAnalysisId && <Grid item xs={12}><Alert severity="warning">Select or create an analysis on Dashboard before starting drift detection.</Alert></Grid>}
          {networks.length > 0 && (!normalNetworks.length || !cancerNetworks.length) && (
            <Grid item xs={12}><Alert severity="info">Choose or build both a completed normal and disease network for {species}.</Alert></Grid>
          )}
        </Grid>
      </Paper>

      {runMutation.isSuccess && !selectedDriftId && <Alert severity="info" sx={{ mb: 2 }}>Drift analysis queued.</Alert>}
      {driftResult?.status === 'queued' || driftResult?.status === 'running' ? <Alert severity="info" sx={{ mb: 2 }}>Drift analysis is {driftResult.status}.</Alert> : null}
      {driftResult?.status === 'failed' && <Alert severity="error" sx={{ mb: 2 }}>Drift analysis failed. Check job details and verify the selected networks.</Alert>}
      {summaryLoading && <LinearProgress sx={{ mb: 2 }} />}
      {summaryError && <Alert severity="error" sx={{ mb: 2 }}>Could not load saved drift scores for this result.</Alert>}

      {driftSummary && (
        <>
          <Grid container spacing={1.5} sx={{ mb: 2 }}>
            {[
              { label: 'GLOBAL DRIFT SCORE', value: driftSummary.global_drift_score?.toFixed(4) ?? '—', color: '#b14444' },
              { label: 'EDGES GAINED', value: driftSummary.n_gained_edges?.toLocaleString() ?? '—', color: '#25856b' },
              { label: 'EDGES LOST', value: driftSummary.n_lost_edges?.toLocaleString() ?? '—', color: '#be5a32' },
              { label: 'EDGES CONSERVED', value: driftSummary.n_conserved_edges?.toLocaleString() ?? '—', color: '#1677a8' },
            ].map((metric) => (
              <Grid item xs={6} md={3} key={metric.label}>
                <Paper variant="outlined" sx={{ p: 1.75, borderTop: `3px solid ${metric.color}` }}>
                  <Typography variant="caption" fontWeight={700} color="text.secondary" letterSpacing="0.05em">{metric.label}</Typography>
                  <Typography variant="h5" fontWeight={800}>{metric.value}</Typography>
                </Paper>
              </Grid>
            ))}
          </Grid>

          <Paper variant="outlined" sx={{ p: { xs: 1.5, md: 2.5 }, mb: 2.5 }}>
            <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ px: 1, pt: 0.5 }}>
              <Box>
                <Typography variant="h6" fontWeight={800}>DRIFT SCORE DISTRIBUTION</Typography>
                <Typography variant="caption" color="text.secondary">{driftSummary.total_genes.toLocaleString()} genes with valid scores</Typography>
              </Box>
              <Chip size="small" variant="outlined" label={species.toUpperCase()} />
            </Stack>
            {driftSummary.total_genes > 0 ? (
              <Plot
                data={histogramTrace}
                layout={{
                  autosize: true,
                  height: 330,
                  margin: { l: 60, r: 24, t: 16, b: 58 },
                  paper_bgcolor: 'rgba(0,0,0,0)',
                  plot_bgcolor: '#f7f9fb',
                  bargap: 0.08,
                  xaxis: { title: { text: 'Low                         Drift score                         High' }, range: [0, undefined], gridcolor: '#e2e8ed' },
                  yaxis: { title: { text: 'Genes' }, rangemode: 'tozero', gridcolor: '#e2e8ed' },
                  font: { family: 'Inter, sans-serif', color: '#475569' },
                }}
                config={{ responsive: true, displaylogo: false }}
                style={{ width: '100%', height: 330 }}
                useResizeHandler
              />
            ) : <Alert severity="info">No valid node drift scores in this result.</Alert>}
          </Paper>

          <Grid container spacing={2}>
            <Grid item xs={12} md={5}>
              <Paper variant="outlined" sx={{ p: 2 }}>
                <Typography variant="h6" fontWeight={800} gutterBottom>TOP DRIFTED GENES</Typography>
                <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 1 }}>Select a gene to inspect its relationships in both species.</Typography>
                <TableContainer sx={{ maxHeight: 560 }}>
                  <Table size="small" stickyHeader>
                    <TableHead><TableRow><TableCell>Gene</TableCell><TableCell align="right">Drift</TableCell><TableCell>Module</TableCell></TableRow></TableHead>
                    <TableBody>
                      {topGenes.map((gene) => (
                        <TableRow key={gene.gene_id} hover selected={gene.gene_id === selectedGeneId} onClick={() => setSelectedGeneId(gene.gene_id)} sx={{ cursor: 'pointer' }}>
                          <TableCell>
                            <Typography variant="body2" fontWeight={700}>{gene.symbol || gene.gene_id}</Typography>
                            {gene.symbol && <Typography variant="caption" color="text.secondary">{gene.gene_id}</Typography>}
                          </TableCell>
                          <TableCell align="right"><Chip size="small" label={gene.drift_score.toFixed(3)} color={gene.drift_score >= 0.5 ? 'error' : gene.drift_score >= 0.3 ? 'warning' : 'default'} /></TableCell>
                          <TableCell>{gene.module ?? '—'}</TableCell>
                        </TableRow>
                      ))}
                      {!topGenes.length && <TableRow><TableCell colSpan={3}>No gene score results are available.</TableCell></TableRow>}
                    </TableBody>
                  </Table>
                </TableContainer>
              </Paper>
            </Grid>

            <Grid item xs={12} md={7}>
              <Paper variant="outlined" sx={{ p: 2, minHeight: 300 }}>
                <Stack direction="row" justifyContent="space-between" alignItems="flex-start" spacing={1} sx={{ mb: 1.5 }}>
                  <Box>
                    <Typography variant="h6" fontWeight={800}>{selectedGeneId ? 'GENE NETWORK DRIFT' : 'GENE RELATIONSHIPS'}</Typography>
                    {selectedGeneId && <Typography variant="subtitle1" fontWeight={700}>{driftSummary.top_genes.find((gene) => gene.gene_id === selectedGeneId)?.symbol || selectedGeneId}</Typography>}
                  </Box>
                  <Chip size="small" label={selectedComparison ? 'Paired species comparison' : 'Cross-species result required'} color={selectedComparison ? 'success' : 'default'} />
                </Stack>
                {!selectedGeneId && <Typography variant="body2" color="text.secondary">Select a row in Top Drifted Genes to compare its network neighbors.</Typography>}
                {selectedGeneId && !selectedComparison && (
                  <Alert severity="info">A completed cross-species comparison using this drift result is required to show the paired gene relationships.</Alert>
                )}
                {geneDriftLoading && <LinearProgress sx={{ my: 2 }} />}
                {geneDrift && (
                  <>
                    <Grid container spacing={1.5}>
                      {([
                        ['human', geneDrift.human],
                        ['mouse', geneDrift.mouse],
                      ] as const).map(([speciesKey, details]) => (
                        <Grid item xs={12} sm={6} key={speciesKey}>
                          <Paper variant="outlined" sx={{ p: 1.5, height: '100%', borderTop: `3px solid ${SPECIES_COLORS[speciesKey]}` }}>
                            <Typography variant="subtitle1" fontWeight={800} sx={{ color: SPECIES_COLORS[speciesKey] }}>{speciesKey.toUpperCase()}</Typography>
                            {details.gene_id ? (
                              <>
                                <Typography variant="body2" fontWeight={700} sx={{ fontFamily: 'monospace', mb: 1 }}>{details.symbol || details.gene_id}</Typography>
                                <Typography variant="caption" color="text.secondary">Cancer network neighbors</Typography>
                                <Box sx={{ mt: 0.75 }}>{formatRelationships(details.relationships?.cancer_edges, details.symbol || details.gene_id)}</Box>
                              </>
                            ) : <Typography variant="body2" color="text.secondary">{details.message}</Typography>}
                          </Paper>
                        </Grid>
                      ))}
                    </Grid>
                    {geneDrift.human.relationships && geneDrift.mouse.relationships && (
                      <>
                        <Divider sx={{ my: 2 }} />
                        <Typography variant="subtitle2" fontWeight={800} gutterBottom>LOST RELATIONSHIPS</Typography>
                        <Grid container spacing={1.5}>
                          {([
                            ['Human', geneDrift.human],
                            ['Mouse', geneDrift.mouse],
                          ] as const).map(([label, details]) => (
                            <Grid item xs={12} sm={6} key={label}>
                              <Typography variant="caption" color="text.secondary">{label}</Typography>
                              {details.relationships?.lost_relationships.length
                                ? formatRelationships(details.relationships.lost_relationships, details.symbol || details.gene_id || selectedGeneId)
                                : <Typography variant="body2" color="text.secondary">No lost edges.</Typography>}
                            </Grid>
                          ))}
                        </Grid>
                        <Typography variant="subtitle2" fontWeight={800} sx={{ mt: 2, mb: 0.75 }}>DRIFT TYPE</Typography>
                        <Stack direction="row" spacing={0.75} flexWrap="wrap" useFlexGap>
                          {geneDrift.drift_types.map((type) => <Chip key={type} size="small" color={type.includes('loss') ? 'error' : type.includes('gain') ? 'success' : 'warning'} label={type} />)}
                        </Stack>
                      </>
                    )}
                  </>
                )}
              </Paper>
            </Grid>
          </Grid>
        </>
      )}

      {currentProjectId && !driftResultsLoading && !matchingDrifts.length && (
        <Alert severity="info" sx={{ mt: 2 }}>No {species} drift result yet. Select completed normal and disease networks, then run Drift.</Alert>
      )}
    </Box>
  )
}

type RunResultPage<T> = { items: T[]; total: number }

function SavedRunDriftPage({ runId }: { runId: string }) {
  const [genePage, setGenePage] = useState(0)
  const [edgePage, setEdgePage] = useState(0)
  const [modulePage, setModulePage] = useState(0)
  const [edgeStatus, setEdgeStatus] = useState('')
  const { data: summary, isLoading: summaryLoading, isError: summaryError } = useQuery({
    queryKey: ['phase4-drift-summary', runId],
    queryFn: () => phase4Api.driftSummary(runId).then((response) => response.data as Record<string, unknown>),
  })
  const { data: genes, isLoading: genesLoading, isError: genesError } = useQuery({
    queryKey: ['phase4-drift-genes', runId, genePage],
    queryFn: () => phase4Api.driftGenes(runId, 50, genePage * 50).then((response) => response.data as RunResultPage<Record<string, unknown>>),
  })
  const { data: edges, isLoading: edgesLoading, isError: edgesError } = useQuery({
    queryKey: ['phase4-drift-edges', runId, edgeStatus, edgePage],
    queryFn: () => phase4Api.driftEdges(runId, edgeStatus || undefined, 50, edgePage * 50).then((response) => response.data as RunResultPage<Record<string, unknown>>),
  })
  const { data: modules, isLoading: modulesLoading, isError: modulesError } = useQuery({
    queryKey: ['phase4-drift-modules', runId, modulePage],
    queryFn: () => phase4Api.driftModules(runId, 50, modulePage * 50).then((response) => response.data as RunResultPage<Record<string, unknown>>),
  })
  const data = asRecord(summary)
  const edgeCounts = asRecord(data.edge_status_counts)
  const format = (value: unknown) => typeof value === 'number' ? value.toLocaleString(undefined, { maximumFractionDigits: 4 }) : value == null ? '—' : String(value)
  const metricFields: Array<[string, unknown]> = [
    ['Genes compared', data.aligned_gene_count ?? data.total_genes],
    ['Mean gene drift score', data.mean_gene_drift_score],
    ['Conserved edges', edgeCounts.CONSERVED],
    ['Lost edges', edgeCounts.LOST],
    ['Gained edges', edgeCounts.GAINED],
    ['Rewired edges', edgeCounts.REWIRED],
    ['Unmappable edges', edgeCounts.UNMAPPABLE],
  ]
  return (
    <Box>
      <RunHeader runId={runId} view="drift" title="Network Drift Results" subtitle="Saved cross-species gene, edge, and module drift results for this run" />
      {summaryLoading && <LinearProgress sx={{ mb: 2 }} />}
      {summaryError && <Alert severity="error" sx={{ mb: 2 }}>Could not load saved drift summary for this run.</Alert>}
      {!summaryLoading && !summaryError && !summary && <Alert severity="info" sx={{ mb: 2 }}>No completed drift results are saved for this run.</Alert>}
      {summary && <>
        <Grid container spacing={1.5} sx={{ mb: 2 }}>
          {metricFields.map(([label, value]) => (
            <Grid item xs={6} md={3} key={label}>
              <Paper variant="outlined" sx={{ p: 1.5, height: '100%' }}>
                <Typography variant="h5" fontWeight={800}>{format(value)}</Typography>
                <Typography variant="caption" color="text.secondary">{label}</Typography>
              </Paper>
            </Grid>
          ))}
        </Grid>
        <Paper variant="outlined" sx={{ p: 2, mb: 2 }}>
          <Typography variant="h6" fontWeight={700} gutterBottom>Gene drift</Typography>
          {genesLoading && <LinearProgress />}
          {genesError && <Alert severity="error">Could not load gene drift rows.</Alert>}
          <TableContainer><Table size="small"><TableHead><TableRow>
            {['Human gene', 'Human symbol', 'Mouse gene', 'Mouse symbol', 'Drift score', 'Category', 'Neighbor similarity', 'Edge loss rate', 'Module conservation'].map((label) => <TableCell key={label}>{label}</TableCell>)}
          </TableRow></TableHead><TableBody>
            {(genes?.items ?? []).map((gene) => <TableRow key={String(gene.id)}>
              <TableCell sx={{ fontFamily: 'monospace' }}>{format(gene.human_ensembl_id)}</TableCell><TableCell>{format(gene.human_symbol)}</TableCell>
              <TableCell sx={{ fontFamily: 'monospace' }}>{format(gene.mouse_ensembl_id)}</TableCell><TableCell>{format(gene.mouse_symbol)}</TableCell>
              <TableCell>{format(gene.drift_score)}</TableCell><TableCell>{format(gene.drift_category)}</TableCell>
              <TableCell>{format(gene.neighbor_similarity)}</TableCell><TableCell>{format(gene.edge_loss_rate)}</TableCell><TableCell>{format(gene.module_conservation)}</TableCell>
            </TableRow>)}
            {!genesLoading && !genesError && !genes?.total && <TableRow><TableCell colSpan={9}>No gene drift results are available.</TableCell></TableRow>}
          </TableBody></Table></TableContainer>
          <TablePagination component="div" count={genes?.total ?? 0} page={genePage} onPageChange={(_, next) => setGenePage(next)} rowsPerPage={50} onRowsPerPageChange={() => undefined} rowsPerPageOptions={[50]} />
        </Paper>
        <Paper variant="outlined" sx={{ p: 2, mb: 2 }}>
          <Stack direction={{ xs: 'column', sm: 'row' }} justifyContent="space-between" spacing={1} sx={{ mb: 1 }}>
            <Typography variant="h6" fontWeight={700}>Edge drift</Typography>
            <TextField select size="small" label="Edge status" value={edgeStatus} onChange={(event) => { setEdgeStatus(event.target.value); setEdgePage(0) }} sx={{ minWidth: 180 }}>
              <MenuItem value="">All statuses</MenuItem>{['CONSERVED', 'LOST', 'GAINED', 'REWIRED', 'UNMAPPABLE'].map((status) => <MenuItem key={status} value={status}>{status}</MenuItem>)}
            </TextField>
          </Stack>
          {edgesLoading && <LinearProgress />}
          {edgesError && <Alert severity="error">Could not load edge drift rows.</Alert>}
          <TableContainer><Table size="small"><TableHead><TableRow>
            {['Status', 'Human source', 'Human target', 'Mouse source', 'Mouse target', 'Human weight', 'Mouse weight', 'Weight change'].map((label) => <TableCell key={label}>{label}</TableCell>)}
          </TableRow></TableHead><TableBody>
            {(edges?.items ?? []).map((edge) => <TableRow key={String(edge.id)}>
              <TableCell>{format(edge.status)}</TableCell><TableCell>{format(edge.human_source_gene_id)}</TableCell><TableCell>{format(edge.human_target_gene_id)}</TableCell>
              <TableCell>{format(edge.mouse_source_gene_id)}</TableCell><TableCell>{format(edge.mouse_target_gene_id)}</TableCell>
              <TableCell>{format(edge.human_weight)}</TableCell><TableCell>{format(edge.mouse_weight)}</TableCell><TableCell>{format(edge.weight_difference)}</TableCell>
            </TableRow>)}
            {!edgesLoading && !edgesError && !edges?.total && <TableRow><TableCell colSpan={8}>No edge drift results match this status.</TableCell></TableRow>}
          </TableBody></Table></TableContainer>
          <TablePagination component="div" count={edges?.total ?? 0} page={edgePage} onPageChange={(_, next) => setEdgePage(next)} rowsPerPage={50} onRowsPerPageChange={() => undefined} rowsPerPageOptions={[50]} />
        </Paper>
        <Paper variant="outlined" sx={{ p: 2 }}>
          <Typography variant="h6" fontWeight={700} gutterBottom>Module conservation</Typography>
          {modulesLoading && <LinearProgress />}
          {modulesError && <Alert severity="error">Could not load module conservation results.</Alert>}
          <TableContainer><Table size="small"><TableHead><TableRow>
            {['Human module', 'Candidate mouse module', 'Human module size', 'Mapped genes', 'Mouse overlap', 'Overlap fraction', 'Conservation score', 'Classification'].map((label) => <TableCell key={label}>{label}</TableCell>)}
          </TableRow></TableHead><TableBody>
            {(modules?.items ?? []).map((module) => <TableRow key={String(module.id)}>
              <TableCell>{format(module.human_module_id)}</TableCell><TableCell>{format(module.candidate_mouse_module_id)}</TableCell>
              <TableCell>{format(module.human_module_size)}</TableCell><TableCell>{format(module.mapped_gene_count)}</TableCell>
              <TableCell>{format(module.mouse_module_overlap)}</TableCell><TableCell>{format(module.overlap_fraction)}</TableCell>
              <TableCell>{format(module.module_conservation_score)}</TableCell><TableCell>{format(module.classification)}</TableCell>
            </TableRow>)}
            {!modulesLoading && !modulesError && !modules?.total && <TableRow><TableCell colSpan={8}>No module conservation results are available.</TableCell></TableRow>}
          </TableBody></Table></TableContainer>
          <TablePagination component="div" count={modules?.total ?? 0} page={modulePage} onPageChange={(_, next) => setModulePage(next)} rowsPerPage={50} onRowsPerPageChange={() => undefined} rowsPerPageOptions={[50]} />
        </Paper>
      </>}
    </Box>
  )
}

export default function DriftPage() {
  const { runId } = useParams<{ runId: string }>()
  return runId ? <SavedRunDriftPage key={runId} runId={runId} /> : <LegacyDriftPage />
}
