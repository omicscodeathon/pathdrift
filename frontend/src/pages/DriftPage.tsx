/**
 * Network Drift Page — Visualizes network-level changes between healthy and disease states.
 * Shows per-node drift scores, edge gain/loss, and module disruption.
 */
import { useEffect, useState } from 'react'
import {
  Box, Typography, Paper, Grid, Alert, Button, TextField, MenuItem,
  Chip, Table, TableBody, TableCell, TableHead, TableRow, TableContainer,
  CircularProgress, LinearProgress, Divider,
} from '@mui/material'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import Plot from 'react-plotly.js'
import { useSnackbar } from 'notistack'
import { driftApi, networkApi } from '@/api/client'
import type { DriftResult, NodeDrift } from '@/types'
import { useProjectStore } from '@/store/projectStore'
import JobStatusBadge from '@/components/JobStatusBadge'

export default function DriftPage() {
  const { enqueueSnackbar } = useSnackbar()
  const queryClient = useQueryClient()
  const { currentAnalysisId, healthyNetworkId, diseaseNetworkId, humanDriftId, mouseDriftId } = useProjectStore()
  const [driftId, setDriftId] = useState('')
  const [selectedDriftId, setSelectedDriftId] = useState('')
  const [config, setConfig] = useState({
    analysis_id: currentAnalysisId || '',
    healthy_network_id: healthyNetworkId || '',
    disease_network_id: diseaseNetworkId || '',
    species: 'human',
  })

  const effectiveDriftId = driftId || (config.species === 'human' ? humanDriftId : mouseDriftId) || ''

  useEffect(() => {
    const storedDriftId = config.species === 'human' ? humanDriftId : mouseDriftId
    if (storedDriftId && !selectedDriftId) setSelectedDriftId(storedDriftId)
  }, [config.species, humanDriftId, mouseDriftId, selectedDriftId])

  const { data: nodeDrift, isLoading: nodesLoading } = useQuery({
    queryKey: ['node-drift', selectedDriftId],
    queryFn: () => driftApi.getNodes(selectedDriftId).then(r => r.data as NodeDrift[]),
    enabled: !!selectedDriftId,
  })

  const { data: driftResult } = useQuery({
    queryKey: ['drift-result', selectedDriftId],
    queryFn: () => driftApi.get(selectedDriftId).then(r => r.data as DriftResult),
    enabled: !!selectedDriftId,
  })

  const runMutation = useMutation({
    mutationKey: ['drift', 'run'],
    mutationFn: () => driftApi.run(config),
    onSuccess: (res) => {
      enqueueSnackbar('Drift analysis queued', { variant: 'info' })
    },
    onError: () => enqueueSnackbar('Failed to start drift analysis', { variant: 'error' }),
  })

  const topNodes = nodeDrift ? [...nodeDrift].sort((a, b) => b.node_drift_score - a.node_drift_score).slice(0, 50) : []

  return (
    <Box>
      <Typography variant="h4" fontWeight={700} gutterBottom>Network Drift</Typography>
      <Typography variant="body2" color="text.secondary" mb={3}>
        Detect and quantify gene network changes between healthy and breast cancer states.
        Higher Node Drift Scores indicate genes whose network connectivity has changed most dramatically.
      </Typography>

      {/* Configuration */}
      <Paper sx={{ p: 3, mb: 3 }} variant="outlined">
        <Typography variant="h6" fontWeight={600} gutterBottom>Run Drift Analysis</Typography>
        <Grid container spacing={2} alignItems="flex-end">
          <Grid item xs={12} sm={4}>
            <TextField label="Healthy Network ID" fullWidth size="small" value={config.healthy_network_id}
              onChange={e => setConfig(c => ({ ...c, healthy_network_id: e.target.value }))} />
          </Grid>
          <Grid item xs={12} sm={4}>
            <TextField label="Disease Network ID" fullWidth size="small" value={config.disease_network_id}
              onChange={e => setConfig(c => ({ ...c, disease_network_id: e.target.value }))} />
          </Grid>
          <Grid item xs={12} sm={2}>
            <TextField select label="Species" fullWidth size="small" value={config.species}
              onChange={e => setConfig(c => ({ ...c, species: e.target.value }))}>
              <MenuItem value="human">Human</MenuItem>
              <MenuItem value="mouse">Mouse</MenuItem>
            </TextField>
          </Grid>
          <Grid item xs={12} sm={2}>
            <Button variant="contained" fullWidth disabled={runMutation.isPending || !config.healthy_network_id || !config.disease_network_id}
              onClick={() => runMutation.mutate()}>
              {runMutation.isPending ? <CircularProgress size={20} color="inherit" /> : 'Run Drift'}
            </Button>
          </Grid>
        </Grid>
      </Paper>

      {/* View results */}
      <Paper sx={{ p: 3, mb: 3 }} variant="outlined">
        <Typography variant="h6" fontWeight={600} gutterBottom>View Results</Typography>
        <Box sx={{ display: 'flex', gap: 2, alignItems: 'center' }}>
          <TextField label="Drift Analysis ID" size="small" value={driftId || effectiveDriftId}
            onChange={e => setDriftId(e.target.value)} sx={{ flex: 1 }} />
          <Button variant="outlined" onClick={() => setSelectedDriftId(driftId)} disabled={!driftId}>
            Load
          </Button>
        </Box>
      </Paper>

      {/* Results */}
      {driftResult && (
        <>
          <Grid container spacing={2} mb={3}>
            {[
              { label: 'Global Drift Score', value: driftResult.global_drift_score?.toFixed(4) ?? '—', color: 'error.main' },
              { label: 'Edges Gained', value: driftResult.n_gained_edges ?? '—', color: 'success.main' },
              { label: 'Edges Lost', value: driftResult.n_lost_edges ?? '—', color: 'warning.main' },
              { label: 'Edges Conserved', value: driftResult.n_conserved_edges ?? '—', color: 'info.main' },
            ].map(({ label, value, color }) => (
              <Grid item xs={6} sm={3} key={label}>
                <Paper sx={{ p: 2, textAlign: 'center' }} variant="outlined">
                  <Typography variant="h5" fontWeight={700} sx={{ color }}>{value}</Typography>
                  <Typography variant="caption" color="text.secondary">{label}</Typography>
                </Paper>
              </Grid>
            ))}
          </Grid>

          <Alert severity="info" sx={{ mb: 3 }}>
            <strong>Drift Score Formula:</strong> GNDS = mean(topology_drift, weight_drift);
            where topology_drift = (edges_gained + edges_lost) / (edges_healthy + edges_disease)
            and weight_drift = mean |Δweight| over rewired edges. Range [0, 1+]; higher = more drift.
          </Alert>
        </>
      )}

      {nodesLoading && <LinearProgress sx={{ mb: 2 }} />}

      {topNodes.length > 0 && (
        <Grid container spacing={3}>
          <Grid item xs={12} md={7}>
            <Paper sx={{ p: 2 }} variant="outlined">
              <Typography variant="subtitle1" fontWeight={600} gutterBottom>
                Top 50 Drifting Genes by Node Drift Score
              </Typography>
              <Plot
                data={[{
                  x: topNodes.map(n => n.node_drift_score),
                  y: topNodes.map(n => n.gene_id),
                  type: 'bar',
                  orientation: 'h',
                  marker: { color: topNodes.map(n => n.degree_change > 0 ? '#2e7d32' : '#c62828') },
                }]}
                layout={{
                  height: 600,
                  margin: { l: 120, r: 20, t: 10, b: 40 },
                  xaxis: { title: 'Node Drift Score' },
                  yaxis: { automargin: true },
                  paper_bgcolor: 'rgba(0,0,0,0)',
                  plot_bgcolor: 'rgba(0,0,0,0)',
                }}
                config={{ displayModeBar: false, responsive: true }}
                style={{ width: '100%' }}
              />
            </Paper>
          </Grid>

          <Grid item xs={12} md={5}>
            <Paper sx={{ p: 2 }} variant="outlined">
              <Typography variant="subtitle1" fontWeight={600} gutterBottom>Degree Change Scatter</Typography>
              <Plot
                data={[{
                  x: topNodes.map(n => n.degree_healthy),
                  y: topNodes.map(n => n.degree_disease),
                  mode: 'markers',
                  type: 'scatter',
                  text: topNodes.map(n => n.gene_id),
                  hovertemplate: '%{text}<br>Healthy: %{x}<br>Disease: %{y}<extra></extra>',
                  marker: {
                    color: topNodes.map(n => n.node_drift_score),
                    colorscale: 'Viridis',
                    showscale: true,
                    colorbar: { title: 'Drift Score', thickness: 12 },
                    size: 8,
                  },
                }]}
                layout={{
                  height: 350,
                  margin: { l: 50, r: 80, t: 10, b: 50 },
                  xaxis: { title: 'Degree (Healthy)' },
                  yaxis: { title: 'Degree (Disease)' },
                  paper_bgcolor: 'rgba(0,0,0,0)',
                  plot_bgcolor: 'rgba(0,0,0,0)',
                  shapes: [{
                    type: 'line', x0: 0, y0: 0,
                    x1: Math.max(...topNodes.map(n => n.degree_healthy)),
                    y1: Math.max(...topNodes.map(n => n.degree_healthy)),
                    line: { dash: 'dash', color: '#999', width: 1 },
                  }],
                }}
                config={{ displayModeBar: false, responsive: true }}
                style={{ width: '100%' }}
              />
            </Paper>

            <Paper sx={{ p: 2, mt: 2 }} variant="outlined">
              <Typography variant="subtitle1" fontWeight={600} gutterBottom>Top 20 Genes</Typography>
              <TableContainer sx={{ maxHeight: 240 }}>
                <Table size="small" stickyHeader>
                  <TableHead>
                    <TableRow>
                      <TableCell>Gene</TableCell>
                      <TableCell align="right">Drift Score</TableCell>
                      <TableCell align="right">ΔDegree</TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {topNodes.slice(0, 20).map(n => (
                      <TableRow key={n.gene_id} hover>
                        <TableCell sx={{ fontFamily: 'monospace', fontSize: 12 }}>{n.gene_id}</TableCell>
                        <TableCell align="right">
                          <Chip size="small" label={n.node_drift_score.toFixed(3)}
                            color={n.node_drift_score > 0.5 ? 'error' : n.node_drift_score > 0.3 ? 'warning' : 'default'} />
                        </TableCell>
                        <TableCell align="right" sx={{ color: n.degree_change > 0 ? 'success.main' : 'error.main', fontWeight: 600 }}>
                          {n.degree_change > 0 ? '+' : ''}{n.degree_change}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </TableContainer>
            </Paper>
          </Grid>
        </Grid>
      )}

      {selectedDriftId && !nodesLoading && topNodes.length === 0 && (
        <Alert severity="info">No analysis has been performed yet for this ID, or results are still processing.</Alert>
      )}
    </Box>
  )
}
