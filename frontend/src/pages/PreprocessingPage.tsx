import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  CircularProgress,
  Divider,
  Grid,
  MenuItem,
  Paper,
  Stack,
  TextField,
  Typography,
} from '@mui/material'
import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useSnackbar } from 'notistack'
import { preprocessingApi } from '@/api/client'
import { useProjectStore } from '@/store/projectStore'

const NORM_METHODS = [
  { value: 'log2cpm', label: 'log2(CPM+1) — RNA-seq raw counts' },
  { value: 'deseq2_vst', label: 'DESeq2 VST — raw counts, variance stabilized' },
  { value: 'tpm', label: 'TPM — data already normalized' },
  { value: 'quantile', label: 'Quantile normalization — microarray' },
  { value: 'none', label: 'None — data is already processed' },
]

const toggleStyle = {
  borderRadius: 2,
  px: 1.5,
  py: 0.75,
  fontWeight: 600,
  textTransform: 'none',
} as const

export default function PreprocessingPage() {
  const { enqueueSnackbar } = useSnackbar()
  const queryClient = useQueryClient()
  const { currentAnalysisId, currentDatasetId, preprocessingJobId, setWorkflowIds } = useProjectStore()

  const [config, setConfig] = useState({
    analysis_id: '',
    dataset_id: currentDatasetId || '',
    normalization_method: 'log2cpm',
    low_expr_threshold: 1.0,
    low_expr_min_samples: 3,
    min_gene_variance: 0.1,
    remove_duplicates: true,
    impute_missing: false,
    batch_correct: false,
    outlier_detection: false,
  })

  useEffect(() => {
    if (currentAnalysisId) {
      setConfig((prev) => ({
        ...prev,
        analysis_id: currentAnalysisId,
        dataset_id: currentDatasetId || prev.dataset_id,
      }))
    }
  }, [currentAnalysisId, currentDatasetId])

  const runMutation = useMutation({
    mutationKey: ['preprocessing', 'start'],
    mutationFn: (requestConfig: typeof config) => preprocessingApi.start(requestConfig),
    onSuccess: (res) => {
      const job = res.data as { id: string; result_ref?: string }
      const jobId = job.result_ref ?? job.id
      setWorkflowIds({ preprocessingJobId: jobId })
      queryClient.invalidateQueries({ queryKey: ['preprocessing', 'latest'] })
      queryClient.invalidateQueries({ queryKey: ['datasets'] })
      enqueueSnackbar(`Preprocessing job queued (ID: ${jobId})`, { variant: 'info' })
    },
    onError: (error: unknown) => {
      const detail = (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      enqueueSnackbar(detail || 'Failed to start preprocessing', { variant: 'error' })
    },
  })

  const latestJobQuery = useQuery({
    queryKey: ['preprocessing', 'latest', currentAnalysisId],
    queryFn: () => (currentAnalysisId ? preprocessingApi.getLatestForAnalysis(currentAnalysisId).then((r) => r.data) : null),
    enabled: !!currentAnalysisId,
    refetchInterval: (query) => {
      const status = query.state.data?.status
      return status === 'queued' || status === 'running' ? 2000 : false
    },
  })

  const latestJob = latestJobQuery.data as {
    id?: string
    status?: string
    output_file_path?: string
    processing_log?: string
    n_genes_after?: number
    n_samples_after?: number
  } | null

  const hasActiveContext = !!currentAnalysisId && !!currentDatasetId

  return (
    <Box sx={{ maxWidth: 1200, mx: 'auto', py: 2 }}>
      <Stack spacing={3}>
        <Box>
          <Typography variant="h4" fontWeight={800} gutterBottom>
            Preprocessing
          </Typography>
          <Typography variant="body1" color="text.secondary">
            Configure and run the preprocessing pipeline. Every parameter is logged for reproducibility.
          </Typography>
        </Box>

        <Paper variant="outlined" sx={{ p: 2, borderRadius: 3, background: 'linear-gradient(135deg, rgba(25,118,210,0.04), rgba(0,171,85,0.03))' }}>
          <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1.5} flexWrap="wrap" useFlexGap>
            <Chip
              size="small"
              label={`Analysis: ${currentAnalysisId ?? 'unselected'}`}
              color={currentAnalysisId ? 'secondary' : 'default'}
              sx={{ fontWeight: 600 }}
            />
            <Chip
              size="small"
              label={`Dataset: ${currentDatasetId ?? 'unselected'}`}
              color={currentDatasetId ? 'success' : 'default'}
              sx={{ fontWeight: 600 }}
            />
            <Chip
              size="small"
              label={`Preprocessing job: ${preprocessingJobId ?? 'pending'}`}
              color={preprocessingJobId ? 'info' : 'default'}
              sx={{ fontWeight: 600 }}
            />
          </Stack>
        </Paper>

        <Alert severity="warning" sx={{ borderRadius: 2 }}>
          Select the normalization method appropriate for your data type. Applying log2CPM to already-normalized data is inappropriate and will produce incorrect results.
        </Alert>

        <Grid container spacing={3}>
          <Grid item xs={12} lg={8}>
            <Card variant="outlined" sx={{ height: '100%', borderRadius: 3 }}>
              <CardContent sx={{ p: 3 }}>
                <Typography variant="h6" fontWeight={700} gutterBottom>
                  Pipeline configuration
                </Typography>

                {!hasActiveContext && (
                  <Alert severity="info" sx={{ mb: 2.5, borderRadius: 2 }}>
                    No active analysis or dataset is selected. Create or select one from the project dashboard and dataset list before running preprocessing.
                  </Alert>
                )}

                {hasActiveContext && (
                  <Alert severity="success" sx={{ mb: 2.5, borderRadius: 2 }}>
                    Auto-linked IDs: Analysis {currentAnalysisId} · Dataset {currentDatasetId}
                  </Alert>
                )}

                <Grid container spacing={2}>
                  <Grid item xs={12}>
                    <TextField
                      label="Dataset ID"
                      fullWidth
                      value={currentDatasetId || config.dataset_id || ''}
                      InputProps={{ readOnly: true }}
                      helperText="Selected dataset for preprocessing"
                    />
                  </Grid>

                  <Grid item xs={12}>
                    <TextField
                      select
                      label="Normalization Method"
                      fullWidth
                      value={config.normalization_method}
                      onChange={(e) => setConfig((c) => ({ ...c, normalization_method: e.target.value }))}
                    >
                      {NORM_METHODS.map((method) => (
                        <MenuItem key={method.value} value={method.value}>
                          {method.label}
                        </MenuItem>
                      ))}
                    </TextField>
                  </Grid>

                  <Grid item xs={12} sm={4}>
                    <TextField
                      label="Low expr threshold"
                      type="number"
                      fullWidth
                      value={config.low_expr_threshold}
                      onChange={(e) => setConfig((c) => ({ ...c, low_expr_threshold: Number(e.target.value) }))}
                      helperText="Min expression count/value"
                    />
                  </Grid>

                  <Grid item xs={12} sm={4}>
                    <TextField
                      label="Min samples"
                      type="number"
                      fullWidth
                      value={config.low_expr_min_samples}
                      onChange={(e) => setConfig((c) => ({ ...c, low_expr_min_samples: Number(e.target.value) }))}
                      helperText="Min samples above threshold"
                    />
                  </Grid>

                  <Grid item xs={12} sm={4}>
                    <TextField
                      label="Min gene variance"
                      type="number"
                      fullWidth
                      value={config.min_gene_variance}
                      onChange={(e) => setConfig((c) => ({ ...c, min_gene_variance: Number(e.target.value) }))}
                      helperText="Keep only informative genes"
                    />
                  </Grid>

                  <Grid item xs={12}>
                    <Typography variant="subtitle2" fontWeight={700} gutterBottom>
                      Quality filters
                    </Typography>
                    <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1.5} flexWrap="wrap" useFlexGap>
                      {[
                        { key: 'remove_duplicates', label: 'Remove duplicates' },
                        { key: 'outlier_detection', label: 'Outlier detection' },
                        { key: 'impute_missing', label: 'Impute missing values' },
                        { key: 'batch_correct', label: 'Batch correction' },
                      ].map(({ key, label }) => {
                        const active = Boolean(config[key as keyof typeof config])
                        return (
                          <Button
                            key={key}
                            size="small"
                            variant={active ? 'contained' : 'outlined'}
                            sx={toggleStyle}
                            onClick={() => setConfig((c) => ({ ...c, [key]: !c[key as keyof typeof c] }))}
                          >
                            {label}
                          </Button>
                        )
                      })}
                    </Stack>
                  </Grid>

                  <Grid item xs={12}>
                    <Button
                      variant="contained"
                      size="large"
                      fullWidth
                      disabled={runMutation.isPending || !hasActiveContext}
                      onClick={() => {
                        const requestConfig = {
                          ...config,
                          analysis_id: currentAnalysisId || config.analysis_id || '',
                          dataset_id: currentDatasetId || config.dataset_id || '',
                        }
                        runMutation.mutate(requestConfig)
                      }}
                      startIcon={runMutation.isPending ? <CircularProgress size={18} color="inherit" /> : undefined}
                      sx={{ borderRadius: 2, fontWeight: 700 }}
                    >
                      Start preprocessing
                    </Button>
                  </Grid>
                </Grid>
              </CardContent>
            </Card>
          </Grid>

          <Grid item xs={12} lg={4}>
            <Card variant="outlined" sx={{ height: '100%', borderRadius: 3, background: 'linear-gradient(180deg, rgba(0,0,0,0.01), rgba(22,163,74,0.03))' }}>
              <CardContent sx={{ p: 3 }}>
                <Typography variant="h6" fontWeight={700} gutterBottom>
                  Recommended workflow
                </Typography>
                <Stack spacing={2}>
                  <Paper variant="outlined" sx={{ p: 2, borderRadius: 2 }}>
                    <Typography variant="subtitle2" fontWeight={700} color="primary.main">
                      1. Select dataset
                    </Typography>
                    <Typography variant="body2" color="text.secondary">
                      Choose the dataset from the project workspace so the preprocessing job has a valid target.
                    </Typography>
                  </Paper>
                  <Paper variant="outlined" sx={{ p: 2, borderRadius: 2 }}>
                    <Typography variant="subtitle2" fontWeight={700} color="primary.main">
                      2. Match normalization
                    </Typography>
                    <Typography variant="body2" color="text.secondary">
                      Use log2CPM or DESeq2 VST for raw counts. Use TPM or none for already-normalized matrices.
                    </Typography>
                  </Paper>
                  <Paper variant="outlined" sx={{ p: 2, borderRadius: 2 }}>
                    <Typography variant="subtitle2" fontWeight={700} color="primary.main">
                      3. Run and monitor
                    </Typography>
                    <Typography variant="body2" color="text.secondary">
                      The job status updates as the pipeline processes genes, filters low expression, and saves outputs.
                    </Typography>
                  </Paper>
                </Stack>
              </CardContent>
            </Card>
          </Grid>
        </Grid>

        {runMutation.isError && (
          <Alert severity="error" sx={{ borderRadius: 2 }}>
            {(runMutation.error as { response?: { data?: { detail?: string } } })?.response?.data?.detail || 'Preprocessing request failed.'}
          </Alert>
        )}

        {(preprocessingJobId || latestJob) && (
          <Paper variant="outlined" sx={{ p: 3, borderRadius: 3 }}>
            <Typography variant="h6" fontWeight={700} gutterBottom>
              Preprocessing output
            </Typography>
            <Divider sx={{ mb: 2 }} />

            <Stack spacing={1.5}>
              <Alert severity={latestJob?.status === 'completed' ? 'success' : latestJob?.status === 'failed' ? 'error' : 'info'} sx={{ borderRadius: 2 }}>
                Job: {latestJob?.id ?? preprocessingJobId ?? 'n/a'} · Status: {latestJob?.status ?? 'queued'}
              </Alert>

              {(latestJob?.output_file_path || preprocessingJobId) && (
                <Typography variant="body2" color="text.secondary">
                  Output file: {latestJob?.output_file_path ?? preprocessingJobId ?? 'not available yet'}
                </Typography>
              )}

              {typeof latestJob?.n_genes_after === 'number' && typeof latestJob?.n_samples_after === 'number' && (
                <Typography variant="body2" color="text.secondary">
                  Final matrix: {latestJob.n_genes_after} genes × {latestJob.n_samples_after} samples
                </Typography>
              )}

              {latestJob?.processing_log && (
                <Paper variant="outlined" sx={{ p: 2, bgcolor: 'grey.50', maxHeight: 240, overflow: 'auto', borderRadius: 2 }}>
                  <Typography variant="caption" component="pre" sx={{ whiteSpace: 'pre-wrap', fontFamily: 'monospace' }}>
                    {latestJob.processing_log}
                  </Typography>
                </Paper>
              )}
            </Stack>
          </Paper>
        )}
      </Stack>
    </Box>
  )
}
