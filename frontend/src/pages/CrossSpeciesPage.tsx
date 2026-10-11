/**
 * Cross-Species Page — Compare human and mouse network drift.
 */
import { useEffect, useState } from 'react'
import {
  Box, Typography, Paper, Grid, Button, TextField, MenuItem, Stack,
  Chip, Alert, CircularProgress, Table, TableBody, TableCell,
  TableHead, TableRow, TableContainer, LinearProgress, TablePagination,
} from '@mui/material'
import Plot from 'react-plotly.js'
import CytoscapeComponent from 'react-cytoscapejs'
import { useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useSnackbar } from 'notistack'
import { crossSpeciesApi, phase4Api } from '@/api/client'
import type { CrossSpeciesResult, CrossSpeciesGene } from '@/types'
import { useProjectStore } from '@/store/projectStore'
import { asRecord, RunHeader } from '@/pages/analysis/shared'

interface NetworkPreview {
  nodes: Array<{ gene_id: string }>
  edges: Array<{ gene1: string; gene2: string; weight: number }>
}

interface NetworkAlignment {
  comparison_id: string
  human_network_id: string
  mouse_network_id: string
  human_network_name: string
  mouse_network_name: string
  mapped_ortholog_pairs: number
  human_total_edges: number
  mouse_total_edges: number
  alignment: {
    conserved_edges: number
    rewired_edges: number
    human_only_edges: number
    mouse_only_edges: number
    human_ortholog_mapped_edges: number
    mouse_ortholog_mapped_edges: number
    aligned_union_edges: number
    network_preservation: number | null
    network_drift: number | null
  }
  human_graph: NetworkPreview
  mouse_graph: NetworkPreview
}

function NetworkPreviewCard({ title, graph, color, totalEdges }: { title: string; graph: NetworkPreview; color: string; totalEdges: number }) {
  const elements = [
    ...graph.nodes.map((node) => ({ data: { id: node.gene_id, label: node.gene_id.split('.')[0].slice(-8) } })),
    ...graph.edges.map((edge) => ({ data: { id: `${edge.gene1}-${edge.gene2}`, source: edge.gene1, target: edge.gene2, weight: edge.weight } })),
  ]
  return (
    <Paper variant="outlined" sx={{ overflow: 'hidden' }}>
      <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ px: 2, py: 1.25, borderBottom: '1px solid', borderColor: 'divider' }}>
        <Typography variant="subtitle1" fontWeight={800}>{title}</Typography>
        <Typography variant="caption" color="text.secondary">{totalEdges.toLocaleString()} total edges · strongest {graph.edges.length} shown</Typography>
      </Stack>
      {elements.length ? (
        <CytoscapeComponent
          elements={elements}
          style={{ width: '100%', height: 300, background: '#f5f8fa' }}
          stylesheet={[
            { selector: 'node', style: { 'background-color': color, label: 'data(label)', color: '#fff', 'font-size': 7, 'text-valign': 'center', 'text-halign': 'center', width: 19, height: 19, 'border-width': 1, 'border-color': '#fff' } },
            { selector: 'edge', style: { width: 'mapData(weight, 0.4, 1, 0.5, 2)', 'line-color': '#8aa0b1', opacity: 0.5, 'curve-style': 'bezier' } },
          ]}
          layout={{ name: 'cose', animate: false, randomize: false, nodeRepulsion: 5000, idealEdgeLength: 45 }}
        />
      ) : (
        <Box sx={{ height: 300, display: 'grid', placeItems: 'center' }}><Typography variant="body2" color="text.secondary">No mapped network edges to preview.</Typography></Box>
      )}
    </Paper>
  )
}

const CLASSIFICATION_COLORS: Record<string, string> = {
  conserved: '#2e7d32',
  human_specific: '#1565c0',
  mouse_specific: '#e65100',
  divergent: '#c62828',
  not_drifting: '#94a3b8',
}

function LegacyCrossSpeciesPage() {
  const queryClient = useQueryClient()
  const { currentProjectId, currentAnalysisId, humanDriftId, mouseDriftId, crossSpeciesId, setWorkflowIds } = useProjectStore()
  const { enqueueSnackbar } = useSnackbar()
  const [config, setConfig] = useState({
    analysis_id: currentAnalysisId || '', human_drift_id: humanDriftId || '', mouse_drift_id: mouseDriftId || '',
  })
  const [csId, setCsId] = useState('')
  const [selectedCsId, setSelectedCsId] = useState(crossSpeciesId || '')
  const [classFilter, setClassFilter] = useState('all')

  const { data: savedComparisons = [] } = useQuery({
    queryKey: ['cross-species-results', currentProjectId],
    queryFn: () => currentProjectId
      ? crossSpeciesApi.listForProject(currentProjectId).then((response) => response.data as CrossSpeciesResult[])
      : [],
    enabled: !!currentProjectId,
  })

  useEffect(() => {
    setConfig((current) => ({
      ...current,
      analysis_id: currentAnalysisId || current.analysis_id,
      human_drift_id: humanDriftId || current.human_drift_id,
      mouse_drift_id: mouseDriftId || current.mouse_drift_id,
    }))
    if (crossSpeciesId) setSelectedCsId(crossSpeciesId)
  }, [crossSpeciesId, currentAnalysisId, humanDriftId, mouseDriftId])

  useEffect(() => {
    if (!savedComparisons.length) return
    if (savedComparisons.some((comparison) => comparison.id === selectedCsId)) return
    const preferred = savedComparisons.find((comparison) => comparison.id === crossSpeciesId)
    setSelectedCsId(preferred?.id ?? savedComparisons[0].id)
  }, [crossSpeciesId, savedComparisons, selectedCsId])

  const runMutation = useMutation({
    mutationKey: ['cross-species', 'run'],
    mutationFn: () => crossSpeciesApi.run(config),
    onSuccess: (response) => {
      const job = response.data as { id: string; result_ref?: string }
      const resultId = job.result_ref ?? job.id
      setSelectedCsId(resultId)
      setWorkflowIds({ crossSpeciesId: resultId })
      queryClient.invalidateQueries({ queryKey: ['cross-species-results', currentProjectId] })
      enqueueSnackbar('Cross-species analysis queued', { variant: 'info' })
    },
    onError: () => enqueueSnackbar('Failed to start analysis', { variant: 'error' }),
  })

  const { data: csResult } = useQuery({
    queryKey: ['cs-result', selectedCsId],
    queryFn: () => crossSpeciesApi.get(selectedCsId).then(r => r.data as CrossSpeciesResult),
    enabled: !!selectedCsId,
    refetchInterval: (query) => {
      const status = query.state.data?.status
      return status === 'running' || status === 'queued' ? 5000 : false
    },
  })

  const { data: networkAlignment, isLoading: alignmentLoading, isError: alignmentError } = useQuery({
    queryKey: ['cross-species-network-alignment', selectedCsId],
    queryFn: () => crossSpeciesApi.getNetworkAlignment(selectedCsId).then((response) => response.data as NetworkAlignment),
    enabled: !!selectedCsId && csResult?.status === 'completed',
  })

  const { data: genes, isLoading: genesLoading } = useQuery({
    queryKey: ['cs-genes', selectedCsId, classFilter],
    queryFn: () => crossSpeciesApi.getGenes(selectedCsId, classFilter === 'all' ? undefined : classFilter).then(r => r.data as CrossSpeciesGene[]),
    enabled: !!selectedCsId && csResult?.status === 'completed',
  })

  const pieData = csResult ? {
    labels: ['Conserved', 'Human Specific', 'Mouse Specific', 'Divergent', 'Not Drifting'],
    values: [
      csResult.n_conserved_drift ?? 0,
      csResult.n_human_specific ?? 0,
      csResult.n_mouse_specific ?? 0,
      csResult.n_divergent ?? 0,
      (csResult.n_orthologous_genes ?? 0) - (csResult.n_conserved_drift ?? 0) -
        (csResult.n_human_specific ?? 0) - (csResult.n_mouse_specific ?? 0) - (csResult.n_divergent ?? 0),
    ],
    marker: { colors: ['#2e7d32', '#1565c0', '#e65100', '#c62828', '#94a3b8'] },
  } : null

  const alignment = networkAlignment?.alignment

  return (
    <Box>
      <Typography variant="h4" fontWeight={800} gutterBottom>CROSS-SPECIES NETWORK COMPARISON</Typography>
      <Typography variant="body2" color="text.secondary" mb={3}>
        Align completed human and mouse disease networks through one-to-one orthology, then inspect conserved and rewired edges.
      </Typography>

      {/* Run configuration */}
      <Paper sx={{ p: 3, mb: 3 }} variant="outlined">
        <Typography variant="h6" fontWeight={600} gutterBottom>Run Cross-Species Comparison</Typography>
        <Grid container spacing={2} alignItems="flex-end">
          <Grid item xs={12} sm={4}>
            <TextField label="Human Drift Analysis ID" fullWidth size="small" value={config.human_drift_id}
              onChange={e => setConfig(c => ({ ...c, human_drift_id: e.target.value }))} />
          </Grid>
          <Grid item xs={12} sm={4}>
            <TextField label="Mouse Drift Analysis ID" fullWidth size="small" value={config.mouse_drift_id}
              onChange={e => setConfig(c => ({ ...c, mouse_drift_id: e.target.value }))} />
          </Grid>
          <Grid item xs={12} sm={4}>
            <Button variant="contained" fullWidth
              disabled={runMutation.isPending || !config.human_drift_id || !config.mouse_drift_id}
              onClick={() => runMutation.mutate()}>
              {runMutation.isPending ? <CircularProgress size={20} color="inherit" /> : 'Compare Species'}
            </Button>
          </Grid>
        </Grid>
      </Paper>

      <Paper sx={{ p: 2, mb: 3 }} variant="outlined">
        <Grid container spacing={1.5} alignItems="center">
          {savedComparisons.length > 0 && (
            <Grid item xs={12} md={7}>
              <TextField select fullWidth size="small" label="Saved comparison" value={selectedCsId}
                onChange={(event) => { setSelectedCsId(event.target.value); setWorkflowIds({ crossSpeciesId: event.target.value }) }}>
                {savedComparisons.map((comparison) => (
                  <MenuItem key={comparison.id} value={comparison.id}>{comparison.id} · {comparison.status}</MenuItem>
                ))}
              </TextField>
            </Grid>
          )}
          <Grid item xs={12} md={savedComparisons.length ? 5 : 12}>
            <Stack direction="row" spacing={1}>
              <TextField label="Comparison ID" size="small" value={csId} onChange={(event) => setCsId(event.target.value)} fullWidth />
              <Button variant="outlined" onClick={() => { setSelectedCsId(csId); setWorkflowIds({ crossSpeciesId: csId }) }} disabled={!csId}>Load</Button>
            </Stack>
          </Grid>
        </Grid>
      </Paper>

      {alignmentLoading && <LinearProgress sx={{ mb: 2 }} />}
      {alignmentError && <Alert severity="warning" sx={{ mb: 2 }}>Edge alignment is unavailable. Confirm both saved disease networks and one-to-one orthology mappings are present.</Alert>}
      {alignment && networkAlignment && (
        <>
          <Grid container spacing={2} sx={{ mb: 2 }}>
            <Grid item xs={12} md={6}><NetworkPreviewCard title={networkAlignment.human_network_name || 'HUMAN NETWORK'} graph={networkAlignment.human_graph} color="#1677a8" totalEdges={networkAlignment.human_total_edges} /></Grid>
            <Grid item xs={12} md={6}><NetworkPreviewCard title={networkAlignment.mouse_network_name || 'MOUSE NETWORK'} graph={networkAlignment.mouse_graph} color="#be5a32" totalEdges={networkAlignment.mouse_total_edges} /></Grid>
          </Grid>

          <Paper variant="outlined" sx={{ p: { xs: 2, md: 3 }, mb: 3 }}>
            <Typography variant="h6" fontWeight={800} align="center" gutterBottom>NETWORK ALIGNMENT</Typography>
            <Typography variant="caption" color="text.secondary" align="center" display="block" sx={{ mb: 2 }}>
              {networkAlignment.mapped_ortholog_pairs.toLocaleString()} one-to-one ortholog pairs · edge comparison uses disease-state networks
            </Typography>
            <Grid container spacing={1.5}>
              {[
                { label: 'Conserved edges', value: alignment.conserved_edges, color: '#25856b' },
                { label: 'Rewired edges', value: alignment.rewired_edges, color: '#a04f7c' },
                { label: 'Human-only edges', value: alignment.human_only_edges, color: '#1677a8' },
                { label: 'Mouse-only edges', value: alignment.mouse_only_edges, color: '#be5a32' },
              ].map((stat) => (
                <Grid item xs={6} md={3} key={stat.label}>
                  <Paper variant="outlined" sx={{ p: 1.75, borderTop: `3px solid ${stat.color}`, height: '100%' }}>
                    <Typography variant="h5" fontWeight={800}>{stat.value.toLocaleString()}</Typography>
                    <Typography variant="caption" color="text.secondary">{stat.label}</Typography>
                  </Paper>
                </Grid>
              ))}
            </Grid>
            <Box sx={{ mt: 3 }}>
              <Stack direction="row" justifyContent="space-between" sx={{ mb: 0.75 }}>
                <Typography variant="body2" fontWeight={700}>Network Preservation</Typography>
                <Typography variant="body2" fontWeight={800}>
                  {alignment.network_preservation == null ? '—' : `${(alignment.network_preservation * 100).toFixed(1)}%`}
                </Typography>
              </Stack>
              <Box sx={{ height: 14, bgcolor: '#e6ecef', overflow: 'hidden' }}>
                {alignment.network_preservation != null && <Box sx={{ height: '100%', width: `${alignment.network_preservation * 100}%`, bgcolor: '#25856b', transition: 'width 250ms ease' }} />}
              </Box>
              <Stack direction="row" justifyContent="space-between" sx={{ mt: 2, mb: 0.75 }}>
                <Typography variant="body2" fontWeight={700}>Network Drift</Typography>
                <Typography variant="body2" fontWeight={800}>
                  {alignment.network_drift == null ? '—' : `${(alignment.network_drift * 100).toFixed(1)}%`}
                </Typography>
              </Stack>
              <Box sx={{ height: 14, bgcolor: '#e6ecef', overflow: 'hidden' }}>
                {alignment.network_drift != null && <Box sx={{ height: '100%', width: `${alignment.network_drift * 100}%`, bgcolor: '#a04f7c', transition: 'width 250ms ease' }} />}
              </Box>
              <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 1.25 }}>
                Preservation is the fraction of conserved edges in the one-to-one ortholog-mapped edge union. Rewiring is a weight change of at least 0.05; drift is the complement of preservation. Mapped human edges: {alignment.human_ortholog_mapped_edges.toLocaleString()} · mapped mouse edges: {alignment.mouse_ortholog_mapped_edges.toLocaleString()}.
              </Typography>
            </Box>
          </Paper>
        </>
      )}

      {/* Summary stats */}
      {csResult?.status === 'completed' && (
        <>
          <Grid container spacing={2} mb={3}>
            {[
              { label: 'Orthologous Genes', value: csResult.n_orthologous_genes ?? '—' },
              { label: 'Conserved Drift', value: csResult.n_conserved_drift ?? '—', color: 'success.main' },
              { label: 'Human Specific', value: csResult.n_human_specific ?? '—', color: 'info.main' },
              { label: 'Mouse Specific', value: csResult.n_mouse_specific ?? '—', color: 'warning.main' },
              { label: 'Divergent', value: csResult.n_divergent ?? '—', color: 'error.main' },
              { label: 'Conservation Score', value: csResult.conservation_score?.toFixed(3) ?? '—', color: 'primary.main' },
            ].map(({ label, value, color }) => (
              <Grid item xs={6} sm={2} key={label}>
                <Paper sx={{ p: 1.5, textAlign: 'center' }} variant="outlined">
                  <Typography variant="h6" fontWeight={700} sx={{ color: color || 'text.primary' }}>{value}</Typography>
                  <Typography variant="caption" color="text.secondary">{label}</Typography>
                </Paper>
              </Grid>
            ))}
          </Grid>

          <Grid container spacing={3}>
            <Grid item xs={12} md={5}>
              {pieData && (
                <Paper sx={{ p: 2 }} variant="outlined">
                  <Typography variant="subtitle1" fontWeight={600} gutterBottom>Drift Classification</Typography>
                  <Plot
                    data={[{ type: 'pie', labels: pieData.labels, values: pieData.values, marker: pieData.marker,
                      textinfo: 'percent', hovertemplate: '%{label}: %{value} genes (%{percent})<extra></extra>' }]}
                    layout={{ height: 320, margin: { l: 10, r: 10, t: 10, b: 10 },
                      paper_bgcolor: 'rgba(0,0,0,0)' }}
                    config={{ displayModeBar: false, responsive: true }}
                    style={{ width: '100%' }}
                  />
                </Paper>
              )}
            </Grid>

            <Grid item xs={12} md={7}>
              <Paper sx={{ p: 2 }} variant="outlined">
                <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
                  <Typography variant="subtitle1" fontWeight={600}>Gene Classification Table</Typography>
                  <TextField select size="small" value={classFilter}
                    onChange={e => setClassFilter(e.target.value)} sx={{ minWidth: 160 }}>
                    {['all', 'conserved', 'human_specific', 'mouse_specific', 'divergent'].map(v => (
                      <MenuItem key={v} value={v}>{v.replace('_', ' ')}</MenuItem>
                    ))}
                  </TextField>
                </Box>
                {genesLoading ? <LinearProgress /> : (
                  <TableContainer sx={{ maxHeight: 340 }}>
                    <Table size="small" stickyHeader>
                      <TableHead>
                        <TableRow>
                          <TableCell>Human Gene</TableCell>
                          <TableCell>Mouse Gene</TableCell>
                          <TableCell>Human Drift</TableCell>
                          <TableCell>Mouse Drift</TableCell>
                          <TableCell>Classification</TableCell>
                        </TableRow>
                      </TableHead>
                      <TableBody>
                        {(genes ?? []).slice(0, 100).map(g => (
                          <TableRow key={g.human_ensembl_id} hover>
                            <TableCell sx={{ fontFamily: 'monospace', fontSize: 11 }}>{g.human_symbol || g.human_ensembl_id}</TableCell>
                            <TableCell sx={{ fontFamily: 'monospace', fontSize: 11 }}>{g.mouse_symbol || g.mouse_ensembl_id}</TableCell>
                            <TableCell>{g.human_drift_score?.toFixed(3)}</TableCell>
                            <TableCell>{g.mouse_drift_score?.toFixed(3)}</TableCell>
                            <TableCell>
                              <Chip size="small" label={g.drift_classification.replace('_', ' ')}
                                sx={{ bgcolor: CLASSIFICATION_COLORS[g.drift_classification] + '20',
                                  color: CLASSIFICATION_COLORS[g.drift_classification], fontWeight: 600, fontSize: 10 }} />
                            </TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </TableContainer>
                )}
              </Paper>
            </Grid>
          </Grid>
        </>
      )}

      {csResult?.status === 'running' && <Alert severity="info">Analysis in progress…</Alert>}
      {csResult?.status === 'failed' && <Alert severity="error">Analysis failed. Check job logs.</Alert>}
      {!selectedCsId && <Alert severity="info" sx={{ mt: 2 }}>No analysis loaded. Run or load a cross-species comparison above.</Alert>}
    </Box>
  )
}

type RunResultPage<T> = { items: T[]; total: number }

function SavedRunCrossSpeciesPage({ runId }: { runId: string }) {
  const [nodePage, setNodePage] = useState(0)
  const [edgePage, setEdgePage] = useState(0)
  const [edgeStatus, setEdgeStatus] = useState('')
  const { data: summary, isLoading: summaryLoading, isError: summaryError } = useQuery({
    queryKey: ['phase4-cross-species-summary', runId],
    queryFn: () => phase4Api.crossSpeciesSummary(runId).then((response) => response.data as Record<string, unknown>),
  })
  const { data: nodes, isLoading: nodesLoading, isError: nodesError } = useQuery({
    queryKey: ['phase4-cross-species-nodes', runId, nodePage],
    queryFn: () => phase4Api.crossSpeciesNodes(runId, 50, nodePage * 50).then((response) => response.data as RunResultPage<Record<string, unknown>>),
  })
  const { data: edges, isLoading: edgesLoading, isError: edgesError } = useQuery({
    queryKey: ['phase4-cross-species-edges', runId, edgeStatus, edgePage],
    queryFn: () => phase4Api.crossSpeciesEdges(runId, edgeStatus || undefined, 50, edgePage * 50).then((response) => response.data as RunResultPage<Record<string, unknown>>),
  })
  const data = asRecord(summary)
  const edgeCounts = asRecord(data.edge_status_counts)
  const format = (value: unknown) => typeof value === 'number' ? value.toLocaleString() : value == null ? '—' : String(value)
  const metricFields: Array<[string, string]> = [
    ['Aligned genes', 'aligned_gene_count'],
    ['Mean gene drift score', 'mean_gene_drift_score'],
    ['Conserved edges', 'conserved_edges'],
    ['Lost edges', 'lost_edges'],
    ['Gained edges', 'gained_edges'],
    ['Rewired edges', 'rewired_edges'],
    ['Unmappable edges', 'unmappable_edges'],
  ]
  return (
    <Box>
      <RunHeader runId={runId} view="cross-species" title="Cross-Species Results" subtitle="Saved human–mouse ortholog and network alignment results for this analysis run" />
      {summaryLoading && <LinearProgress sx={{ mb: 2 }} />}
      {summaryError && <Alert severity="error" sx={{ mb: 2 }}>Could not load saved cross-species results for this run.</Alert>}
      {!summaryLoading && !summaryError && !summary && <Alert severity="info" sx={{ mb: 2 }}>No completed cross-species results are saved for this run.</Alert>}
      {summary && <>
        <Grid container spacing={1.5} sx={{ mb: 2 }}>
          {metricFields.map(([label, key]) => (
            <Grid item xs={6} md={3} key={key}>
              <Paper variant="outlined" sx={{ p: 1.5, height: '100%' }}>
                <Typography variant="h5" fontWeight={800}>{format(data[key] ?? edgeCounts[key.replace('_edges', '').toUpperCase()])}</Typography>
                <Typography variant="caption" color="text.secondary">{label}</Typography>
              </Paper>
            </Grid>
          ))}
        </Grid>
        <Paper variant="outlined" sx={{ p: 2, mb: 2 }}>
          <Typography variant="h6" fontWeight={700} gutterBottom>Node ortholog alignment</Typography>
          {nodesLoading && <LinearProgress />}
          {nodesError && <Alert severity="error">Could not load aligned gene pairs.</Alert>}
          <TableContainer>
            <Table size="small"><TableHead><TableRow>
              {['Human gene', 'Human symbol', 'Mouse gene', 'Mouse symbol', 'Orthology type', 'Human network', 'Mouse network', 'Primary'].map((label) => <TableCell key={label}>{label}</TableCell>)}
            </TableRow></TableHead><TableBody>
              {(nodes?.items ?? []).map((node) => <TableRow key={`${node.human_ensembl_id}-${node.mouse_ensembl_id}`}>
                <TableCell sx={{ fontFamily: 'monospace' }}>{format(node.human_ensembl_id)}</TableCell><TableCell>{format(node.human_symbol)}</TableCell>
                <TableCell sx={{ fontFamily: 'monospace' }}>{format(node.mouse_ensembl_id)}</TableCell><TableCell>{format(node.mouse_symbol)}</TableCell>
                <TableCell>{format(node.orthology_type)}</TableCell><TableCell>{node.human_network_present ? 'Yes' : 'No'}</TableCell><TableCell>{node.mouse_network_present ? 'Yes' : 'No'}</TableCell><TableCell>{node.is_primary ? 'Yes' : 'No'}</TableCell>
              </TableRow>)}
              {!nodesLoading && !nodesError && !nodes?.total && <TableRow><TableCell colSpan={8}>No aligned ortholog pairs are available.</TableCell></TableRow>}
            </TableBody></Table>
          </TableContainer>
          <TablePagination component="div" count={nodes?.total ?? 0} page={nodePage} onPageChange={(_, next) => setNodePage(next)} rowsPerPage={50} onRowsPerPageChange={() => undefined} rowsPerPageOptions={[50]} />
        </Paper>
        <Paper variant="outlined" sx={{ p: 2 }}>
          <Stack direction={{ xs: 'column', sm: 'row' }} justifyContent="space-between" spacing={1} sx={{ mb: 1 }}>
            <Typography variant="h6" fontWeight={700}>Cross-species edge results</Typography>
            <TextField select size="small" label="Edge status" value={edgeStatus} onChange={(event) => { setEdgeStatus(event.target.value); setEdgePage(0) }} sx={{ minWidth: 180 }}>
              <MenuItem value="">All statuses</MenuItem>{['CONSERVED', 'LOST', 'GAINED', 'REWIRED', 'UNMAPPABLE'].map((status) => <MenuItem key={status} value={status}>{status}</MenuItem>)}
            </TextField>
          </Stack>
          {edgesLoading && <LinearProgress />}
          {edgesError && <Alert severity="error">Could not load cross-species edge results.</Alert>}
          <TableContainer>
            <Table size="small"><TableHead><TableRow>
              {['Status', 'Human source', 'Human target', 'Mouse source', 'Mouse target', 'Human weight', 'Mouse weight', 'Weight change'].map((label) => <TableCell key={label}>{label}</TableCell>)}
            </TableRow></TableHead><TableBody>
              {(edges?.items ?? []).map((edge) => <TableRow key={String(edge.id)}>
                <TableCell>{format(edge.status)}</TableCell><TableCell>{format(edge.human_source_gene_id)}</TableCell><TableCell>{format(edge.human_target_gene_id)}</TableCell>
                <TableCell>{format(edge.mouse_source_gene_id)}</TableCell><TableCell>{format(edge.mouse_target_gene_id)}</TableCell>
                <TableCell>{format(edge.human_weight)}</TableCell><TableCell>{format(edge.mouse_weight)}</TableCell><TableCell>{format(edge.weight_difference)}</TableCell>
              </TableRow>)}
              {!edgesLoading && !edgesError && !edges?.total && <TableRow><TableCell colSpan={8}>No edge results match this status.</TableCell></TableRow>}
            </TableBody></Table>
          </TableContainer>
          <TablePagination component="div" count={edges?.total ?? 0} page={edgePage} onPageChange={(_, next) => setEdgePage(next)} rowsPerPage={50} onRowsPerPageChange={() => undefined} rowsPerPageOptions={[50]} />
        </Paper>
      </>}
    </Box>
  )
}

export default function CrossSpeciesPage() {
  const { runId } = useParams<{ runId: string }>()
  return runId ? <SavedRunCrossSpeciesPage key={runId} runId={runId} /> : <LegacyCrossSpeciesPage />
}
