/**
 * Prediction Page — Train and compare ML models.
 * Shows all three model types: expression-only, drift-only, combined.
 */
import { useState } from 'react'
import {
  Box, Typography, Paper, Grid, Button, TextField, MenuItem,
  Table, TableBody, TableCell, TableHead, TableRow, TableContainer,
  Chip, Alert, CircularProgress, Divider, Tooltip,
} from '@mui/material'
import Plot from 'react-plotly.js'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useSnackbar } from 'notistack'
import { mlApi, validationApi } from '@/api/client'
import type { ModelMetric } from '@/types'
import JobStatusBadge from '@/components/JobStatusBadge'

export default function PredictionPage() {
  const { enqueueSnackbar } = useSnackbar()
  const queryClient = useQueryClient()
  const [config, setConfig] = useState({
    analysis_id: '',
    name: '',
    experiment_type: 'combined',
    model_type: 'random_forest',
    training_dataset_id: '',
    validation_dataset_id: '',
    drift_analysis_id: '',
    cross_species_analysis_id: '',
    random_seed: 42,
    cv_folds: 5,
    class_weight: 'balanced',
  })
  const [comparisonExpId, setComparisonExpId] = useState('')
  const [comparisonData, setComparisonData] = useState<unknown>(null)

  const runMutation = useMutation({
    mutationKey: ['ml', 'experiment'],
    mutationFn: () => mlApi.createExperiment(config),
    onSuccess: () => {
      enqueueSnackbar('ML experiment queued', { variant: 'info' })
      queryClient.invalidateQueries({ queryKey: ['ml'] })
    },
    onError: () => enqueueSnackbar('Failed to start ML experiment', { variant: 'error' }),
  })

  const loadComparison = async () => {
    try {
      const res = await validationApi.compareModels(comparisonExpId)
      setComparisonData(res.data)
    } catch {
      enqueueSnackbar('Failed to load comparison', { variant: 'error' })
    }
  }

  const comparison = comparisonData as {
    analysis_id: string
    research_question: string
    comparison: Array<{
      experiment_id: string
      name: string
      experiment_type: string
      model_type: string
      status: string
      metrics: ModelMetric[]
    }>
  } | null

  // Build comparison plot data
  const plotData = comparison?.comparison?.map(exp => {
    const cvMetric = exp.metrics?.find(m => m.split === 'cv')
    const valMetric = exp.metrics?.find(m => m.split === 'external_val')
    return {
      name: exp.name,
      type: exp.experiment_type,
      cv_auroc: cvMetric?.auroc ?? null,
      val_auroc: valMetric?.auroc ?? null,
      cv_f1: cvMetric?.f1 ?? null,
    }
  }) ?? []

  return (
    <Box>
      <Typography variant="h4" fontWeight={700} gutterBottom>Prediction</Typography>
      <Typography variant="body2" color="text.secondary" mb={3}>
        Train machine learning models to predict breast cancer state.
        Compare three feature sets: expression-only (baseline), network-drift-only, and combined.
      </Typography>

      <Alert severity="info" sx={{ mb: 3 }}>
        <strong>Research Question:</strong> Does network-drift improve early breast cancer state prediction
        beyond conventional gene-expression features alone?
        Train one model of each type with the same dataset to answer this.
      </Alert>

      {/* Configuration */}
      <Paper sx={{ p: 3, mb: 3 }} variant="outlined">
        <Typography variant="h6" fontWeight={600} gutterBottom>Configure Experiment</Typography>
        <Grid container spacing={2}>
          <Grid item xs={12} sm={6}>
            <TextField label="Experiment Name" fullWidth size="small" value={config.name}
              onChange={e => setConfig(c => ({ ...c, name: e.target.value }))} required />
          </Grid>
          <Grid item xs={12} sm={3}>
            <TextField select label="Feature Type" fullWidth size="small" value={config.experiment_type}
              onChange={e => setConfig(c => ({ ...c, experiment_type: e.target.value }))}>
              <MenuItem value="expression_only">Expression Only (Baseline)</MenuItem>
              <MenuItem value="drift_only">Network Drift Only</MenuItem>
              <MenuItem value="combined">Combined</MenuItem>
            </TextField>
          </Grid>
          <Grid item xs={12} sm={3}>
            <TextField select label="Algorithm" fullWidth size="small" value={config.model_type}
              onChange={e => setConfig(c => ({ ...c, model_type: e.target.value }))}>
              <MenuItem value="random_forest">Random Forest</MenuItem>
              <MenuItem value="logistic_regression">Logistic Regression</MenuItem>
              <MenuItem value="svm">SVM</MenuItem>
              <MenuItem value="gradient_boosting">Gradient Boosting</MenuItem>
            </TextField>
          </Grid>
          <Grid item xs={12} sm={6}>
            <TextField label="Training Dataset ID" fullWidth size="small" value={config.training_dataset_id}
              onChange={e => setConfig(c => ({ ...c, training_dataset_id: e.target.value }))} required />
          </Grid>
          <Grid item xs={12} sm={6}>
            <TextField label="Validation Dataset ID (independent)" fullWidth size="small" value={config.validation_dataset_id}
              onChange={e => setConfig(c => ({ ...c, validation_dataset_id: e.target.value }))}
              helperText="Must be completely independent from training data" />
          </Grid>
          <Grid item xs={12} sm={6}>
            <TextField label="Drift Analysis ID (for drift/combined)" fullWidth size="small" value={config.drift_analysis_id}
              onChange={e => setConfig(c => ({ ...c, drift_analysis_id: e.target.value }))} />
          </Grid>
          <Grid item xs={12} sm={6}>
            <TextField label="Cross-Species Analysis ID (optional)" fullWidth size="small" value={config.cross_species_analysis_id}
              onChange={e => setConfig(c => ({ ...c, cross_species_analysis_id: e.target.value }))} />
          </Grid>
          <Grid item xs={6} sm={2}>
            <TextField label="CV Folds" type="number" fullWidth size="small" value={config.cv_folds}
              onChange={e => setConfig(c => ({ ...c, cv_folds: parseInt(e.target.value) }))} />
          </Grid>
          <Grid item xs={6} sm={2}>
            <TextField label="Random Seed" type="number" fullWidth size="small" value={config.random_seed}
              onChange={e => setConfig(c => ({ ...c, random_seed: parseInt(e.target.value) }))} />
          </Grid>
          <Grid item xs={12} sm={8} sx={{ display: 'flex', alignItems: 'flex-end' }}>
            <Button
              variant="contained" size="large"
              disabled={runMutation.isPending || !config.name || !config.training_dataset_id || !config.analysis_id}
              onClick={() => runMutation.mutate()}
              startIcon={runMutation.isPending ? <CircularProgress size={18} color="inherit" /> : undefined}
            >
              Launch Experiment
            </Button>
          </Grid>
        </Grid>
      </Paper>

      {/* Model Comparison */}
      <Paper sx={{ p: 3 }} variant="outlined">
        <Typography variant="h6" fontWeight={600} gutterBottom>Model Comparison</Typography>
        <Box sx={{ display: 'flex', gap: 2, mb: 3 }}>
          <TextField label="Any Experiment ID in Analysis" size="small" value={comparisonExpId}
            onChange={e => setComparisonExpId(e.target.value)} sx={{ flex: 1 }} />
          <Button variant="outlined" onClick={loadComparison} disabled={!comparisonExpId}>Load Comparison</Button>
        </Box>

        {comparison && (
          <>
            <Alert severity="info" sx={{ mb: 2 }}>
              <strong>{comparison.research_question}</strong>
            </Alert>

            <TableContainer>
              <Table size="small">
                <TableHead>
                  <TableRow sx={{ '& th': { fontWeight: 600 } }}>
                    <TableCell>Experiment</TableCell>
                    <TableCell>Feature Type</TableCell>
                    <TableCell>Algorithm</TableCell>
                    <TableCell>Status</TableCell>
                    <TableCell align="right">CV AUROC</TableCell>
                    <TableCell align="right">Ext Val AUROC</TableCell>
                    <TableCell align="right">CV F1</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {plotData.map((row, i) => (
                    <TableRow key={i} hover>
                      <TableCell sx={{ fontWeight: 500 }}>{comparison.comparison[i].name}</TableCell>
                      <TableCell>
                        <Chip size="small"
                          label={row.type.replace('_', ' ')}
                          color={row.type === 'combined' ? 'primary' : row.type === 'drift_only' ? 'secondary' : 'default'}
                        />
                      </TableCell>
                      <TableCell>{comparison.comparison[i].model_type}</TableCell>
                      <TableCell><JobStatusBadge status={comparison.comparison[i].status as 'completed'} /></TableCell>
                      <TableCell align="right" sx={{ fontWeight: 700, color: (row.cv_auroc ?? 0) > 0.7 ? 'success.main' : 'text.primary' }}>
                        {row.cv_auroc ? row.cv_auroc.toFixed(3) : '—'}
                      </TableCell>
                      <TableCell align="right" sx={{ fontWeight: 700 }}>
                        {row.val_auroc ? row.val_auroc.toFixed(3) : '—'}
                      </TableCell>
                      <TableCell align="right">
                        {row.cv_f1 ? row.cv_f1.toFixed(3) : '—'}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </TableContainer>

            {plotData.some(r => r.cv_auroc !== null) && (
              <Box mt={3}>
                <Plot
                  data={[
                    {
                      x: plotData.map(r => r.name),
                      y: plotData.map(r => r.cv_auroc ?? 0),
                      name: 'CV AUROC',
                      type: 'bar',
                      marker: { color: '#1565c0' },
                    },
                    {
                      x: plotData.map(r => r.name),
                      y: plotData.map(r => r.val_auroc ?? 0),
                      name: 'External Validation AUROC',
                      type: 'bar',
                      marker: { color: '#00acc1' },
                    },
                  ]}
                  layout={{
                    barmode: 'group',
                    height: 300,
                    margin: { l: 50, r: 20, t: 20, b: 80 },
                    yaxis: { title: 'AUROC', range: [0, 1] },
                    shapes: [{ type: 'line', x0: -0.5, x1: plotData.length - 0.5, y0: 0.5, y1: 0.5,
                      line: { dash: 'dash', color: '#999', width: 1 } }],
                    paper_bgcolor: 'rgba(0,0,0,0)',
                    plot_bgcolor: 'rgba(0,0,0,0)',
                    legend: { orientation: 'h', y: -0.3 },
                  }}
                  config={{ displayModeBar: false, responsive: true }}
                  style={{ width: '100%' }}
                />
                <Typography variant="caption" color="text.secondary" display="block" textAlign="center">
                  Dashed line at AUROC = 0.5 represents random chance.
                  External validation AUROC is the clinically relevant metric.
                </Typography>
              </Box>
            )}
          </>
        )}
      </Paper>
    </Box>
  )
}
