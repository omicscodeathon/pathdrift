/**
 * Cross-Species Page — Compare human and mouse network drift.
 */
import { useEffect, useState } from 'react'
import {
  Box, Typography, Paper, Grid, Button, TextField, MenuItem,
  Chip, Alert, CircularProgress, Table, TableBody, TableCell,
  TableHead, TableRow, TableContainer, LinearProgress,
} from '@mui/material'
import Plot from 'react-plotly.js'
import { useMutation, useQuery } from '@tanstack/react-query'
import { useSnackbar } from 'notistack'
import { crossSpeciesApi } from '@/api/client'
import type { CrossSpeciesResult, CrossSpeciesGene } from '@/types'
import { useProjectStore } from '@/store/projectStore'

const CLASSIFICATION_COLORS: Record<string, string> = {
  conserved: '#2e7d32',
  human_specific: '#1565c0',
  mouse_specific: '#e65100',
  divergent: '#c62828',
  not_drifting: '#94a3b8',
}

export default function CrossSpeciesPage() {
  const { currentAnalysisId, humanDriftId, mouseDriftId, crossSpeciesId } = useProjectStore()
  const { enqueueSnackbar } = useSnackbar()
  const [config, setConfig] = useState({
    analysis_id: currentAnalysisId || '', human_drift_id: humanDriftId || '', mouse_drift_id: mouseDriftId || '',
  })
  const [csId, setCsId] = useState('')
  const [selectedCsId, setSelectedCsId] = useState(crossSpeciesId || '')
  const [classFilter, setClassFilter] = useState('all')

  useEffect(() => {
    setConfig((current) => ({
      ...current,
      analysis_id: currentAnalysisId || current.analysis_id,
      human_drift_id: humanDriftId || current.human_drift_id,
      mouse_drift_id: mouseDriftId || current.mouse_drift_id,
    }))
    if (crossSpeciesId) setSelectedCsId(crossSpeciesId)
  }, [crossSpeciesId, currentAnalysisId, humanDriftId, mouseDriftId])

  const runMutation = useMutation({
    mutationKey: ['cross-species', 'run'],
    mutationFn: () => crossSpeciesApi.run(config),
    onSuccess: () => enqueueSnackbar('Cross-species analysis queued', { variant: 'info' }),
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

  return (
    <Box>
      <Typography variant="h4" fontWeight={700} gutterBottom>Cross-Species Analysis</Typography>
      <Typography variant="body2" color="text.secondary" mb={3}>
        Compare human and mouse network drift using orthology mapping.
        Identifies conserved, species-specific, and divergent network changes.
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

      {/* Load results */}
      <Paper sx={{ p: 2, mb: 3 }} variant="outlined">
        <Box sx={{ display: 'flex', gap: 2 }}>
          <TextField label="Cross-Species Analysis ID" size="small" value={csId}
            onChange={e => setCsId(e.target.value)} sx={{ flex: 1 }} />
          <Button variant="outlined" onClick={() => setSelectedCsId(csId)} disabled={!csId}>Load</Button>
        </Box>
      </Paper>

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
