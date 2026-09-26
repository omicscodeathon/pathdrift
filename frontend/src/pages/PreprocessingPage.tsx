import { Box, Typography, Alert, Paper, Grid, Button, TextField, MenuItem, CircularProgress } from '@mui/material'
import { useState, useEffect } from 'react'
import { useMutation } from '@tanstack/react-query'
import { useSnackbar } from 'notistack'
import { preprocessingApi } from '@/api/client'
import { useProjectStore } from '@/store/projectStore'

const NORM_METHODS = [
  { value: 'log2cpm', label: 'log2(CPM+1) — for raw RNA-seq counts' },
  { value: 'deseq2_vst', label: 'DESeq2 VST — for raw counts (requires integer data)' },
  { value: 'tpm', label: 'TPM — data already in TPM' },
  { value: 'quantile', label: 'Quantile normalization — microarray' },
  { value: 'none', label: 'None — data is already processed' },
]

export default function PreprocessingPage() {
  const { enqueueSnackbar } = useSnackbar()
  const { currentAnalysisId, currentDatasetId, preprocessingJobId, setWorkflowIds } = useProjectStore()
  const [config, setConfig] = useState({
    analysis_id: '', dataset_id: currentDatasetId || '',
    normalization_method: 'log2cpm',
    low_expr_threshold: 1.0,
    low_expr_min_samples: 3,
    min_gene_variance: 0.1,
    remove_duplicates: true,
    impute_missing: false,
    batch_correct: false,
    outlier_detection: true,
  })

  useEffect(() => {
    if (currentAnalysisId) {
      setConfig((prev) => ({ ...prev, analysis_id: currentAnalysisId, dataset_id: currentDatasetId || prev.dataset_id }))
    }
  }, [currentAnalysisId, currentDatasetId])

  const runMutation = useMutation({
    mutationKey: ['preprocessing', 'start'],
    mutationFn: (requestConfig: typeof config) => preprocessingApi.start(requestConfig),
    onSuccess: (res) => {
      const job = res.data as { id: string; result_ref?: string }
      setWorkflowIds({ preprocessingJobId: job.result_ref ?? job.id })
      enqueueSnackbar(`Preprocessing job queued (ID: ${job.result_ref ?? job.id})`, { variant: 'info' })
    },
    onError: (error: unknown) => {
      const detail = (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      enqueueSnackbar(detail || 'Failed to start preprocessing', { variant: 'error' })
    },
  })

  return (
    <Box>
      <Typography variant="h4" fontWeight={700} gutterBottom>Preprocessing</Typography>
      <Typography variant="body2" color="text.secondary" mb={3}>
        Configure and run the preprocessing pipeline. Every parameter is logged for reproducibility.
      </Typography>

      <Alert severity="warning" sx={{ mb: 3 }}>
        Select the normalization method appropriate for your data type.
        Applying log2CPM to already-normalized data is inappropriate and will produce incorrect results.
        If unsure, consult your dataset documentation.
      </Alert>

      <Paper sx={{ p: 3 }} variant="outlined">
        <Typography variant="h6" fontWeight={600} gutterBottom>Pipeline Configuration</Typography>
        <Grid container spacing={2}>
          <Grid item xs={12} sm={6}>
            <TextField label="Analysis ID" fullWidth size="small" value={config.analysis_id}
              onChange={e => setConfig(c => ({ ...c, analysis_id: e.target.value }))} required />
          </Grid>
          <Grid item xs={12} sm={6}>
            <TextField label="Dataset ID" fullWidth size="small" value={config.dataset_id}
              onChange={e => setConfig(c => ({ ...c, dataset_id: e.target.value }))} required />
          </Grid>
          <Grid item xs={12}>
            <TextField select label="Normalization Method" fullWidth size="small" value={config.normalization_method}
              onChange={e => setConfig(c => ({ ...c, normalization_method: e.target.value }))}>
              {NORM_METHODS.map(m => <MenuItem key={m.value} value={m.value}>{m.label}</MenuItem>)}
            </TextField>
          </Grid>
          <Grid item xs={6} sm={3}>
            <TextField label="Low Expr Threshold" type="number" fullWidth size="small"
              value={config.low_expr_threshold} onChange={e => setConfig(c => ({ ...c, low_expr_threshold: parseFloat(e.target.value) }))}
              helperText="Min expression count/value" />
          </Grid>
          <Grid item xs={6} sm={3}>
            <TextField label="Min Samples" type="number" fullWidth size="small"
              value={config.low_expr_min_samples} onChange={e => setConfig(c => ({ ...c, low_expr_min_samples: parseInt(e.target.value) }))}
              helperText="Min samples above threshold" />
          </Grid>
          <Grid item xs={6} sm={3}>
            <TextField label="Min Gene Variance" type="number" fullWidth size="small"
              value={config.min_gene_variance} onChange={e => setConfig(c => ({ ...c, min_gene_variance: parseFloat(e.target.value) }))} />
          </Grid>
          <Grid item xs={12} sm={12}>
            <Box sx={{ display: 'flex', gap: 2, flexWrap: 'wrap' }}>
              {[
                { key: 'remove_duplicates', label: 'Remove Duplicates' },
                { key: 'outlier_detection', label: 'Outlier Detection (PCA)' },
                { key: 'impute_missing', label: 'Impute Missing Values' },
                { key: 'batch_correct', label: 'Batch Correction' },
              ].map(({ key, label }) => (
                <Button key={key} size="small" variant={config[key as keyof typeof config] ? 'contained' : 'outlined'}
                  onClick={() => setConfig(c => ({ ...c, [key]: !c[key as keyof typeof c] }))}>
                  {label}
                </Button>
              ))}
            </Box>
          </Grid>
          <Grid item xs={12}>
            <Button variant="contained" size="large" disabled={runMutation.isPending || !config.analysis_id || !config.dataset_id}
              onClick={() => runMutation.mutate(config)}
              startIcon={runMutation.isPending ? <CircularProgress size={18} color="inherit" /> : undefined}>
              Start Preprocessing
            </Button>
          </Grid>
        </Grid>
      </Paper>
      {runMutation.isError && (
        <Alert severity="error" sx={{ mt: 2 }}>
          {(runMutation.error as { response?: { data?: { detail?: string } } })?.response?.data?.detail || 'Preprocessing request failed.'}
        </Alert>
      )}
      {preprocessingJobId && <Alert severity="info" sx={{ mt: 2 }}>Current preprocessing result: {preprocessingJobId}</Alert>}
    </Box>
  )
}
