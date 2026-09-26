 /**
 * Datasets Page — Upload, validate, and manage transcriptomic datasets.
 */
import { useState, useCallback, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Box, Typography, Button, Paper, Grid, Chip, Dialog, DialogTitle,
  DialogContent, DialogActions, TextField, MenuItem, Alert, CircularProgress,
  Table, TableBody, TableCell, TableHead, TableRow, TableContainer,
  LinearProgress, IconButton, Tooltip,
} from '@mui/material'
import { useDropzone } from 'react-dropzone'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { CloudUpload, CheckCircle, ErrorOutline, Warning, Delete, Visibility } from '@mui/icons-material'
import { useSnackbar } from 'notistack'
import { analysisApi, datasetApi, preprocessingApi, degApi } from '@/api/client'
import type { Dataset } from '@/types'
import { useProjectStore } from '@/store/projectStore'

const SPECIES_OPTIONS = [
  { value: 'human', label: 'Human (Homo sapiens)' },
  { value: 'mouse', label: 'Mouse (Mus musculus)' },
]

const DATA_TYPE_OPTIONS = [
  { value: 'raw_counts', label: 'Raw Counts (RNA-seq)' },
  { value: 'normalized', label: 'Already Normalized' },
  { value: 'microarray', label: 'Microarray' },
  { value: 'unknown', label: 'Unknown / Other' },
]

const displayDataType = (value?: string) => {
  const v = (value ?? 'unknown').toString().toLowerCase()
  if (v === 'raw_counts') return 'Raw Counts (RNA-seq)'
  if (v === 'normalized') return 'Already Normalized'
  if (v === 'microarray') return 'Microarray'
  return 'Unknown / Other'
}

const normalizeDatasetId = (dataset: unknown) => {
  const record = dataset as Record<string, unknown> | null
  const candidate =
    record?.id ??
    record?.dataset_id ??
    record?.datasetId ??
    record?.accession ??
    record?.name ??
    'downloaded-dataset'

  const normalized = String(candidate).trim()
  return normalized || 'downloaded-dataset'
}

function StatusChip({ status }: { status: string }) {
  const map: Record<string, { color: 'success' | 'error' | 'warning' | 'default'; icon: JSX.Element }> = {
    true:  { color: 'success', icon: <CheckCircle fontSize="small" /> },
    false: { color: 'error',   icon: <ErrorOutline fontSize="small" /> },
  }
  const s = map[String(status)] ?? { color: 'default', icon: <Warning fontSize="small" /> }
  return <Chip size="small" color={s.color} icon={s.icon} label={status ? 'Validated' : 'Not validated'} />
}

export default function DatasetsPage() {
  const { enqueueSnackbar } = useSnackbar()
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const { currentProjectId, currentAnalysisId, currentDatasetId, setCurrentAnalysis, setCurrentDataset, setWorkflowIds } = useProjectStore()
  const [uploadOpen, setUploadOpen] = useState(false)
  const [form, setForm] = useState({
    name: '', species: 'human', data_type: 'raw_counts',
    tissue: '', source: '', accession: '', platform: '', description: '',
  })
  const [exprFile, setExprFile] = useState<File | null>(null)
  const [metaFile, setMetaFile] = useState<File | null>(null)
  const [validationResult, setValidationResult] = useState<Record<string, unknown> | null>(null)
  const [previewDatasetId, setPreviewDatasetId] = useState<string | null>(null)
  const [previewRows, setPreviewRows] = useState<string[][]>([])
  const [previewLoading, setPreviewLoading] = useState(false)
  const [workflowState, setWorkflowState] = useState<{ datasetId: string; preprocessingJobId: string | null; degJobId: string | null } | null>(null)

  const { data: datasets = [], isLoading } = useQuery({
    queryKey: ['datasets', currentProjectId],
    queryFn: () => currentProjectId ? datasetApi.list(currentProjectId).then(r => r.data as Dataset[]) : [],
    enabled: !!currentProjectId,
  })

  const { data: projectAnalyses = [] } = useQuery({
    queryKey: ['analyses', currentProjectId],
    queryFn: () => currentProjectId ? analysisApi.listForProject(currentProjectId).then(r => r.data) : [],
    enabled: !!currentProjectId,
  })

  const mergedDatasets: Dataset[] = datasets
  const actualDatasetIds = new Set((datasets as Dataset[]).map((dataset) => String(dataset.id)))
  const isWorkflowEligibleDataset = (datasetId: string) => actualDatasetIds.has(String(datasetId))

  useEffect(() => {
    if (!currentProjectId) return
    queryClient.invalidateQueries({ queryKey: ['datasets', currentProjectId] })
  }, [currentProjectId, queryClient])

  useEffect(() => {
    if (currentDatasetId && !datasets.some((dataset) => String(dataset.id) === String(currentDatasetId))) {
      setCurrentDataset(null)
    }
  }, [currentDatasetId, datasets, setCurrentDataset])

  useEffect(() => {
    if (currentAnalysisId && !projectAnalyses.some((analysis) => analysis.id === currentAnalysisId)) {
      setCurrentAnalysis(null)
    }
  }, [currentAnalysisId, projectAnalyses, setCurrentAnalysis])

  const uploadMutation = useMutation({
    mutationKey: ['datasets', 'upload'],
    mutationFn: async () => {
      if (!exprFile || !currentProjectId) throw new Error('Expression file and project required')
      const fd = new FormData()
      fd.append('project_id', currentProjectId)
      Object.entries(form).forEach(([k, v]) => { if (v) fd.append(k, v) })
      fd.append('expression_file', exprFile)
      if (metaFile) fd.append('metadata_file', metaFile)
      return datasetApi.upload(fd)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['datasets'] })
      setUploadOpen(false)
      setExprFile(null)
      setMetaFile(null)
      enqueueSnackbar('Dataset uploaded successfully', { variant: 'success' })
    },
    onError: (err: unknown) => {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail || 'Upload failed'
      enqueueSnackbar(msg, { variant: 'error' })
    },
  })

  const validateMutation = useMutation({
    mutationKey: ['datasets', 'validate'],
    mutationFn: (id: string) => datasetApi.validate(id).then(r => r.data),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['datasets'] })
      setValidationResult(data as Record<string, unknown>)
    },
    onError: () => enqueueSnackbar('Validation failed', { variant: 'error' }),
  })

  const deleteMutation = useMutation({
    mutationKey: ['datasets', 'delete'],
    mutationFn: (id: string) => datasetApi.delete(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['datasets'] })
      enqueueSnackbar('Dataset deleted', { variant: 'info' })
    },
  })

  const workflowMutation = useMutation({
    mutationKey: ['datasets', 'workflow'],
    mutationFn: async (datasetId: string) => {
      if (!currentAnalysisId) {
        throw new Error('Create or select an analysis before running preprocessing and DEG.')
      }

      const canonicalDatasetId = normalizeDatasetId({ id: datasetId })
      if (!isWorkflowEligibleDataset(canonicalDatasetId)) {
        throw new Error('This dataset is not imported into the current project yet. Upload or import it first, then run preprocessing.')
      }
      setCurrentDataset(canonicalDatasetId)

      const preprocessingResponse = await preprocessingApi.start({
        analysis_id: currentAnalysisId,
        dataset_id: canonicalDatasetId,
        normalization_method: 'log2cpm',
        low_expr_threshold: 1.0,
        low_expr_min_samples: 3,
        min_gene_variance: 0.1,
        remove_duplicates: true,
        impute_missing: false,
        batch_correct: false,
        batch_correction_method: null,
        outlier_detection: true,
      })

      const degResponse = await degApi.run({
        analysis_id: currentAnalysisId,
        dataset_id: canonicalDatasetId,
        preprocessing_job_id: preprocessingResponse.data.id,
        method: 'ttest',
        fdr_threshold: 0.05,
        lfc_threshold: 1.0,
      })

      return {
        datasetId: canonicalDatasetId,
        preprocessingJobId: preprocessingResponse.data.result_ref ?? preprocessingResponse.data.id,
        degJobId: degResponse.data.result_ref ?? degResponse.data.id,
      }
    },
    onSuccess: (data) => {
      setWorkflowState(data)
      setWorkflowIds({
        currentDatasetId: data.datasetId,
        preprocessingJobId: data.preprocessingJobId,
        degResultId: data.degJobId,
      })
      enqueueSnackbar(
        `Workflow started: preprocessing ${data.preprocessingJobId} and DEG ${data.degJobId}`,
        { variant: 'success' }
      )
      queryClient.invalidateQueries({ queryKey: ['datasets'] })
    },
    onError: (error: unknown) => {
      const message = (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail || (error as Error)?.message || 'Workflow failed to start.'
      enqueueSnackbar(message, { variant: 'error' })
    },
  })

  const preprocessingStatusQuery = useQuery({
    queryKey: ['preprocessing-status', workflowState?.preprocessingJobId ?? currentAnalysisId],
    queryFn: () => workflowState?.preprocessingJobId
      ? preprocessingApi.get(workflowState.preprocessingJobId).then((r) => r.data)
      : preprocessingApi.getLatestForAnalysis(currentAnalysisId!).then((r) => r.data),
    enabled: !!(workflowState?.preprocessingJobId || currentAnalysisId),
    refetchInterval: (query) => {
      const status = (query.state.data as { status?: string } | undefined)?.status
      return status === 'queued' || status === 'running' ? 2000 : false
    },
  })

  const degStatusQuery = useQuery({
    queryKey: ['deg-status', workflowState?.degJobId ?? currentAnalysisId],
    queryFn: () => workflowState?.degJobId
      ? degApi.get(workflowState.degJobId).then((r) => r.data)
      : degApi.getLatestForAnalysis(currentAnalysisId!).then((r) => r.data),
    enabled: !!(workflowState?.degJobId || currentAnalysisId),
    refetchInterval: (query) => {
      const status = (query.state.data as { status?: string } | undefined)?.status
      return status === 'queued' || status === 'running' ? 2000 : false
    },
  })

  const handlePreviewDataset = async (datasetId: string) => {
    setPreviewDatasetId(datasetId)
    setPreviewLoading(true)
    try {
      const response = await fetch(`/data/pathdrift/raw/${datasetId}.csv`)
      if (!response.ok) {
        setPreviewRows([])
        return
      }
      const text = await response.text()
      const rows = text
        .split(/\r?\n/)
        .map((line) => line.split(',').slice(0, 8))
        .filter((row) => row.some((cell) => cell.trim().length > 0))
        .slice(0, 8)
      setPreviewRows(rows)
    } catch {
      setPreviewRows([])
    } finally {
      setPreviewLoading(false)
    }
  }

  const onExprDrop = useCallback((accepted: File[]) => setExprFile(accepted[0] ?? null), [])
  const { getRootProps: getExprProps, getInputProps: getExprInput, isDragActive: exprDrag } = useDropzone({
    onDrop: onExprDrop, multiple: false,
    accept: { 'text/csv': ['.csv'], 'text/tab-separated-values': ['.tsv', '.txt'], 'application/gzip': ['.gz'] },
  })

  return (
    <Box>
      <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 3 }}>
        <Typography variant="h4" fontWeight={700}>Datasets</Typography>
        <Button variant="contained" startIcon={<CloudUpload />} onClick={() => setUploadOpen(true)}>
          Upload Dataset
        </Button>
      </Box>

      {!currentProjectId && (
        <Alert severity="info" sx={{ mb: 2 }}>
          No project is selected yet, but downloaded public datasets are still visible here for review.
        </Alert>
      )}

      {isLoading && <LinearProgress />}

      {workflowState && (
        <Paper sx={{ p: 2.5, mb: 3 }} variant="outlined">
          <Typography variant="h6" fontWeight={700} gutterBottom>Workflow status</Typography>
          <Typography variant="body2" color="text.secondary" gutterBottom>
            Dataset: <strong>{workflowState.datasetId}</strong>
          </Typography>
          <Grid container spacing={2}>
            <Grid item xs={12} md={6}>
              <Paper variant="outlined" sx={{ p: 2 }}>
                <Typography variant="subtitle2" gutterBottom>Preprocessing job</Typography>
                <Typography variant="body2">Job ID: {workflowState.preprocessingJobId ?? '—'}</Typography>
                <Typography variant="body2">Status: {preprocessingStatusQuery.data?.status ?? 'pending'}</Typography>
              </Paper>
            </Grid>
            <Grid item xs={12} md={6}>
              <Paper variant="outlined" sx={{ p: 2 }}>
                <Typography variant="subtitle2" gutterBottom>DEG result</Typography>
                <Typography variant="body2">Result ID: {workflowState.degJobId ?? '—'}</Typography>
                <Typography variant="body2">Status: {degStatusQuery.data?.status ?? 'pending'}</Typography>
              </Paper>
            </Grid>
          </Grid>
        </Paper>
      )}

      {mergedDatasets.length === 0 && !isLoading ? (
        <Paper sx={{ p: 4, textAlign: 'center' }} variant="outlined">
          <Typography color="text.secondary">
            No datasets yet. Upload your first expression matrix or download a public cohort from Data Acquisition.
          </Typography>
        </Paper>
      ) : (
        <TableContainer component={Paper} variant="outlined">
          <Table size="small">
            <TableHead>
              <TableRow sx={{ '& th': { fontWeight: 600 } }}>
                <TableCell>Name</TableCell>
                <TableCell>Dataset ID</TableCell>
                <TableCell>Species</TableCell>
                <TableCell>Type</TableCell>
                <TableCell>Tissue</TableCell>
                <TableCell>Accession</TableCell>
                <TableCell>Genes</TableCell>
                <TableCell>Samples</TableCell>
                <TableCell>Healthy</TableCell>
                <TableCell>Cancer</TableCell>
                <TableCell>Status</TableCell>
                <TableCell>Actions</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {mergedDatasets.map((ds) => (
                <TableRow key={ds.id} hover>
                  <TableCell>
                    <Typography variant="body2" fontWeight={500}>{ds.name}</Typography>
                    <Typography variant="caption" color="text.secondary" display="block">{ds.source || 'Data acquisition'}</Typography>
                  </TableCell>
                  <TableCell>
                    <Typography variant="body2" fontWeight={500}>{ds.id}</Typography>
                  </TableCell>
                  <TableCell>
                    <Chip size="small" label={String(ds.species).toLowerCase() === 'human' ? '🧬 Human' : String(ds.species).toLowerCase() === 'mouse' ? '🐭 Mouse' : String(ds.species || 'Unknown')} />
                  </TableCell>
                  <TableCell>{displayDataType(ds.data_type)}</TableCell>
                  <TableCell>{ds.tissue || '—'}</TableCell>
                  <TableCell>{ds.accession || '—'}</TableCell>
                  <TableCell>{ds.n_genes?.toLocaleString() ?? '—'}</TableCell>
                  <TableCell>{ds.n_samples?.toLocaleString() ?? '—'}</TableCell>
                  <TableCell>{ds.n_healthy ?? '—'}</TableCell>
                  <TableCell>{ds.n_cancer ?? '—'}</TableCell>
                  <TableCell><StatusChip status={String(ds.is_validated)} /></TableCell>
                  <TableCell>
                    <Tooltip title="Preview rows">
                      <IconButton size="small" onClick={() => handlePreviewDataset(ds.id)}>
                        <Visibility fontSize="small" />
                      </IconButton>
                    </Tooltip>
                    <Tooltip title="Run preprocessing + DEG">
                      <span>
                        <Button
                          size="small"
                          variant="contained"
                          color="secondary"
                          disabled={workflowMutation.isPending || !currentAnalysisId || !isWorkflowEligibleDataset(ds.id)}
                          onClick={() => workflowMutation.mutate(normalizeDatasetId(ds))}
                          sx={{ ml: 0.5, minWidth: 0, px: 1.5 }}
                        >
                          Run workflow
                        </Button>
                      </span>
                    </Tooltip>
                    <Tooltip title="Validate">
                      <IconButton size="small" onClick={() => validateMutation.mutate(ds.id)}>
                        <CheckCircle fontSize="small" />
                      </IconButton>
                    </Tooltip>
                    <Tooltip title="Delete">
                      <IconButton size="small" color="error" onClick={() => deleteMutation.mutate(ds.id)}>
                        <Delete fontSize="small" />
                      </IconButton>
                    </Tooltip>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      )}

      {/* Dataset preview dialog */}
      {previewDatasetId && (
        <Dialog open onClose={() => setPreviewDatasetId(null)} maxWidth="md" fullWidth>
          <DialogTitle>Dataset preview: {previewDatasetId}</DialogTitle>
          <DialogContent dividers>
            {previewLoading ? (
              <Box sx={{ display: 'flex', justifyContent: 'center', py: 3 }}>
                <CircularProgress size={24} />
              </Box>
            ) : previewRows.length > 0 ? (
              <Table size="small">
                <TableBody>
                  {previewRows.map((row, rowIndex) => (
                    <TableRow key={`${previewDatasetId}-${rowIndex}`}>
                      {row.map((cell, cellIndex) => (
                        <TableCell key={`${previewDatasetId}-${rowIndex}-${cellIndex}`} sx={{ fontSize: 12 }}>
                          {cell}
                        </TableCell>
                      ))}
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            ) : (
              <Alert severity="info">No preview rows were available for this dataset yet.</Alert>
            )}
          </DialogContent>
          <DialogActions>
            <Button onClick={() => setPreviewDatasetId(null)}>Close</Button>
          </DialogActions>
        </Dialog>
      )}

      {/* Validation result dialog */}
      {validationResult && (
        <Dialog open onClose={() => setValidationResult(null)} maxWidth="sm" fullWidth>
          <DialogTitle>Validation Result</DialogTitle>
          <DialogContent>
            <Alert severity={(validationResult.is_valid as boolean) ? 'success' : 'error'} sx={{ mb: 2 }}>
              {(validationResult.is_valid as boolean) ? 'Dataset passed validation' : 'Dataset has validation errors'}
            </Alert>
            {(validationResult.errors as string[])?.length > 0 && (
              <Box mb={2}>
                <Typography variant="subtitle2" gutterBottom>Errors:</Typography>
                {(validationResult.errors as string[]).map((e, i) => (
                  <Alert key={i} severity="error" sx={{ mb: 0.5 }}>{e}</Alert>
                ))}
              </Box>
            )}
            {(validationResult.warnings as string[])?.length > 0 && (
              <Box>
                <Typography variant="subtitle2" gutterBottom>Warnings:</Typography>
                {(validationResult.warnings as string[]).map((w, i) => (
                  <Alert key={i} severity="warning" sx={{ mb: 0.5 }}>{w}</Alert>
                ))}
              </Box>
            )}
          </DialogContent>
          <DialogActions>
            <Button onClick={() => setValidationResult(null)}>Close</Button>
          </DialogActions>
        </Dialog>
      )}

      {/* Upload dialog */}
      <Dialog open={uploadOpen} onClose={() => setUploadOpen(false)} maxWidth="md" fullWidth>
        <DialogTitle>Upload Expression Dataset</DialogTitle>
        <DialogContent>
          <Grid container spacing={2} sx={{ mt: 0.5 }}>
            <Grid item xs={12} sm={6}>
              <TextField
                label="Dataset Name" fullWidth required
                value={form.name} onChange={e => setForm(f => ({ ...f, name: e.target.value }))}
              />
            </Grid>
            <Grid item xs={12} sm={6}>
              <TextField
                select label="Species" fullWidth required
                value={form.species} onChange={e => setForm(f => ({ ...f, species: e.target.value }))}
              >
                {SPECIES_OPTIONS.map(o => <MenuItem key={o.value} value={o.value}>{o.label}</MenuItem>)}
              </TextField>
            </Grid>
            <Grid item xs={12} sm={6}>
              <TextField
                select label="Data Type" fullWidth required
                value={form.data_type} onChange={e => setForm(f => ({ ...f, data_type: e.target.value }))}
              >
                {DATA_TYPE_OPTIONS.map(o => <MenuItem key={o.value} value={o.value}>{o.label}</MenuItem>)}
              </TextField>
            </Grid>
            <Grid item xs={12} sm={6}>
              <TextField label="Tissue" fullWidth value={form.tissue}
                onChange={e => setForm(f => ({ ...f, tissue: e.target.value }))} />
            </Grid>
            <Grid item xs={12} sm={6}>
              <TextField label="Source (TCGA, GEO, GTEx...)" fullWidth value={form.source}
                onChange={e => setForm(f => ({ ...f, source: e.target.value }))} />
            </Grid>
            <Grid item xs={12} sm={6}>
              <TextField label="Accession (e.g. GSE12345)" fullWidth value={form.accession}
                onChange={e => setForm(f => ({ ...f, accession: e.target.value }))} />
            </Grid>
            <Grid item xs={12}>
              <Typography variant="subtitle2" gutterBottom>Expression Matrix *</Typography>
              <Box
                {...getExprProps()}
                sx={{
                  border: '2px dashed', borderColor: exprDrag ? 'primary.main' : 'divider',
                  borderRadius: 2, p: 3, textAlign: 'center', cursor: 'pointer',
                  bgcolor: exprDrag ? 'action.hover' : 'background.default',
                }}
              >
                <input {...getExprInput()} />
                {exprFile ? (
                  <Typography variant="body2" color="success.main" fontWeight={500}>
                    ✓ {exprFile.name} ({(exprFile.size / 1024 / 1024).toFixed(1)} MB)
                  </Typography>
                ) : (
                  <Typography variant="body2" color="text.secondary">
                    Drop expression matrix (CSV/TSV/TXT/GZ) or click to browse.<br />
                    Rows = genes, columns = samples.
                  </Typography>
                )}
              </Box>
            </Grid>
            <Grid item xs={12}>
              <Typography variant="subtitle2" gutterBottom>Sample Metadata (optional but strongly recommended)</Typography>
              <input
                type="file"
                accept=".csv,.tsv,.txt"
                onChange={e => setMetaFile(e.target.files?.[0] ?? null)}
              />
              <Typography variant="caption" color="text.secondary" display="block" mt={0.5}>
                Must include columns: sample_id, disease_state (healthy/cancer/normal/tumor).
                Optional: stage, batch, age, sex.
              </Typography>
            </Grid>
          </Grid>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setUploadOpen(false)}>Cancel</Button>
          <Button
            variant="contained"
            onClick={() => uploadMutation.mutate()}
            disabled={uploadMutation.isPending || !exprFile || !form.name}
            startIcon={uploadMutation.isPending ? <CircularProgress size={16} /> : undefined}
          >
            Upload
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  )
}
