import { useState, useEffect } from 'react'
import {
  Box, Typography, Paper, Grid, Button, TextField, MenuItem,
  Alert, CircularProgress, Table, TableBody, TableCell, TableHead, TableRow, TableContainer,
  Chip, LinearProgress,
} from '@mui/material'
import Plot from 'react-plotly.js'
import { useMutation, useQuery } from '@tanstack/react-query'
import { useSnackbar } from 'notistack'
import { degApi } from '@/api/client'
import { useProjectStore } from '@/store/projectStore'

export default function DEGPage() {
  const { enqueueSnackbar } = useSnackbar()
  const { currentAnalysisId, currentDatasetId, preprocessingJobId, degResultId, setWorkflowIds } = useProjectStore()
  const [config, setConfig] = useState({
    analysis_id: '', dataset_id: currentDatasetId || '', preprocessing_job_id: preprocessingJobId || '', method: 'ttest', fdr_threshold: 0.05, lfc_threshold: 1.0,
  })
  const [degId, setDegId] = useState('')
  const [loadedId, setLoadedId] = useState('')

  const { data: degResult } = useQuery({
    queryKey: ['deg-result', loadedId || currentAnalysisId],
    queryFn: () => (loadedId
      ? degApi.get(loadedId).then(r => r.data)
      : degApi.getLatestForAnalysis(currentAnalysisId!).then(r => r.data)),
    enabled: !!(loadedId || currentAnalysisId),
    refetchInterval: (query) => {
      const status = (query.state.data as { status?: string } | undefined)?.status
      return status === 'queued' || status === 'running' ? 5000 : false
    },
  })

  const { data: genes, isLoading: genesLoading } = useQuery({
    queryKey: ['deg-genes', loadedId || (degResult as { id?: string } | undefined)?.id],
    queryFn: () => {
      const resultId = loadedId || (degResult as { id?: string } | undefined)?.id
      return resultId
        ? degApi.getGenes(resultId).then(r => r.data as Array<{ gene_id: string; log2fc: number; padj: number; direction: string }>)
        : degApi.getLatestGenesForAnalysis(currentAnalysisId!).then(r => r.data as Array<{ gene_id: string; log2fc: number; padj: number; direction: string }>)
    },
    enabled: !!(loadedId || currentAnalysisId),
  })

  useEffect(() => {
    if (degResultId && loadedId !== degResultId) {
      setLoadedId(degResultId)
      setDegId(degResultId)
    }
  }, [degResultId, loadedId])

  useEffect(() => {
    if (currentAnalysisId) {
      setConfig((prev) => ({ ...prev, analysis_id: currentAnalysisId, dataset_id: currentDatasetId || prev.dataset_id, preprocessing_job_id: preprocessingJobId || prev.preprocessing_job_id }))
    }
  }, [currentAnalysisId, currentDatasetId, preprocessingJobId])

  const runMutation = useMutation({
    mutationKey: ['deg', 'run'],
    mutationFn: () => degApi.run(config),
    onSuccess: (response) => {
      const job = response.data as { id: string; result_ref?: string }
      const resultId = job.result_ref ?? job.id
      setWorkflowIds({ degResultId: resultId })
      setLoadedId(resultId)
      setDegId(resultId)
      enqueueSnackbar('DEG analysis queued', { variant: 'info' })
    },
    onError: () => enqueueSnackbar('Failed to start DEG analysis', { variant: 'error' }),
  })

  const volcanoData = genes ? {
    x: genes.map(g => g.log2fc),
    y: genes.map(g => -Math.log10(Math.max(g.padj, 1e-300))),
    text: genes.map(g => g.gene_id),
    color: genes.map(g => g.direction === 'up' ? '#c62828' : g.direction === 'down' ? '#1565c0' : '#94a3b8'),
  } : null

  return (
    <Box>
      <Typography variant="h4" fontWeight={700} gutterBottom>DEG Analysis</Typography>
      <Typography variant="body2" color="text.secondary" mb={3}>
        Differential expression analysis between healthy and disease samples.
        This provides the baseline for comparison with network-drift features.
      </Typography>

      <Paper sx={{ p: 3, mb: 3 }} variant="outlined">
        <Typography variant="h6" fontWeight={600} gutterBottom>Configure</Typography>
        <Grid container spacing={2} alignItems="flex-end">
          <Grid item xs={12} sm={3}>
            <TextField label="Dataset ID" fullWidth size="small" value={config.dataset_id}
              onChange={e => setConfig(c => ({ ...c, dataset_id: e.target.value }))} />
          </Grid>
          <Grid item xs={12} sm={2}>
            <TextField select label="Method" fullWidth size="small" value={config.method}
              onChange={e => setConfig(c => ({ ...c, method: e.target.value }))}>
              <MenuItem value="ttest">Welch t-test</MenuItem>
              <MenuItem value="pydeseq2">DESeq2 (raw counts)</MenuItem>
            </TextField>
          </Grid>
          <Grid item xs={6} sm={2}>
            <TextField label="FDR Threshold" type="number" fullWidth size="small" value={config.fdr_threshold}
              onChange={e => setConfig(c => ({ ...c, fdr_threshold: parseFloat(e.target.value) }))} />
          </Grid>
          <Grid item xs={6} sm={2}>
            <TextField label="|log2FC| Threshold" type="number" fullWidth size="small" value={config.lfc_threshold}
              onChange={e => setConfig(c => ({ ...c, lfc_threshold: parseFloat(e.target.value) }))} />
          </Grid>
          <Grid item xs={12} sm={3}>
            <Button variant="contained" fullWidth disabled={runMutation.isPending || !config.dataset_id}
              onClick={() => runMutation.mutate()}>
              {runMutation.isPending ? <CircularProgress size={20} color="inherit" /> : 'Run DEG'}
            </Button>
          </Grid>
        </Grid>
      </Paper>

      <Box sx={{ display: 'flex', gap: 2, mb: 3 }}>
        <TextField label="DEG Result ID" size="small" value={degId} onChange={e => setDegId(e.target.value)} sx={{ flex: 1 }} />
        <Button variant="outlined" onClick={() => setLoadedId(degId)} disabled={!degId}>Load</Button>
      </Box>
      {degResultId && <Alert severity="info" sx={{ mb: 2 }}>Current DEG result: {degResultId}</Alert>}

      {degResult && (
        <Grid container spacing={2} mb={3}>
          {[
            { label: 'Total DEGs', value: (degResult as { n_deg_total?: number }).n_deg_total ?? '—' },
            { label: 'Upregulated', value: (degResult as { n_deg_up?: number }).n_deg_up ?? '—', color: 'error.main' },
            { label: 'Downregulated', value: (degResult as { n_deg_down?: number }).n_deg_down ?? '—', color: 'info.main' },
            { label: 'Method', value: (degResult as { method?: string }).method ?? '—' },
          ].map(({ label, value, color }) => (
            <Grid item xs={6} sm={3} key={label}>
              <Paper sx={{ p: 2, textAlign: 'center' }} variant="outlined">
                <Typography variant="h5" fontWeight={700} sx={{ color: color || 'text.primary' }}>{value}</Typography>
                <Typography variant="caption" color="text.secondary">{label}</Typography>
              </Paper>
            </Grid>
          ))}
        </Grid>
      )}

      {genesLoading && <LinearProgress sx={{ mb: 2 }} />}

      {volcanoData && (
        <Grid container spacing={3}>
          <Grid item xs={12} md={7}>
            <Paper sx={{ p: 2 }} variant="outlined">
              <Typography variant="subtitle1" fontWeight={600} gutterBottom>Volcano Plot</Typography>
              <Plot
                data={[{
                  x: volcanoData.x,
                  y: volcanoData.y,
                  mode: 'markers',
                  type: 'scatter',
                  text: volcanoData.text,
                  hovertemplate: '%{text}<br>log2FC: %{x:.2f}<br>-log10(adj.p): %{y:.2f}<extra></extra>',
                  marker: { color: volcanoData.color, size: 4, opacity: 0.7 },
                }]}
                layout={{
                  height: 420,
                  margin: { l: 60, r: 20, t: 20, b: 50 },
                  xaxis: { title: 'log₂ Fold Change' },
                  yaxis: { title: '-log₁₀(adj. p-value)' },
                  shapes: [
                    { type: 'line', x0: -config.lfc_threshold, x1: -config.lfc_threshold, y0: 0, y1: Math.max(...volcanoData.y) + 1, line: { dash: 'dash', color: '#999', width: 1 } },
                    { type: 'line', x0: config.lfc_threshold, x1: config.lfc_threshold, y0: 0, y1: Math.max(...volcanoData.y) + 1, line: { dash: 'dash', color: '#999', width: 1 } },
                    { type: 'line', x0: Math.min(...volcanoData.x), x1: Math.max(...volcanoData.x), y0: -Math.log10(config.fdr_threshold), y1: -Math.log10(config.fdr_threshold), line: { dash: 'dash', color: '#999', width: 1 } },
                  ],
                  paper_bgcolor: 'rgba(0,0,0,0)',
                  plot_bgcolor: '#f8fafc',
                }}
                config={{ displayModeBar: false, responsive: true }}
                style={{ width: '100%' }}
              />
            </Paper>
          </Grid>
          <Grid item xs={12} md={5}>
            <Paper sx={{ p: 2 }} variant="outlined">
              <Typography variant="subtitle1" fontWeight={600} gutterBottom>Top Significant Genes</Typography>
              <TableContainer sx={{ maxHeight: 380 }}>
                <Table size="small" stickyHeader>
                  <TableHead>
                    <TableRow>
                      <TableCell>Gene</TableCell>
                      <TableCell align="right">log2FC</TableCell>
                      <TableCell align="right">adj.p</TableCell>
                      <TableCell>Dir.</TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {genes?.slice(0, 30).map(g => (
                      <TableRow key={g.gene_id} hover>
                        <TableCell sx={{ fontFamily: 'monospace', fontSize: 11 }}>{g.gene_id}</TableCell>
                        <TableCell align="right" sx={{ color: g.log2fc > 0 ? 'error.main' : 'info.main', fontWeight: 600 }}>
                          {g.log2fc.toFixed(2)}
                        </TableCell>
                        <TableCell align="right">{g.padj.toExponential(2)}</TableCell>
                        <TableCell>
                          <Chip size="small" label={g.direction} color={g.direction === 'up' ? 'error' : 'info'} />
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

      {loadedId && !genes && !genesLoading && (
        <Alert severity="info">No analysis results available yet. The job may still be running.</Alert>
      )}
    </Box>
  )
}
