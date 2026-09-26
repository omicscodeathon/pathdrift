import { useEffect, useMemo, useState } from 'react'
import {
  Box, Typography, Paper, Grid, Button, Chip, Stack, Alert,
  Card, CardContent, CardActions, Divider, Checkbox, FormControlLabel, LinearProgress,
  Dialog, DialogTitle, DialogContent, DialogActions, Table, TableBody, TableCell, TableHead, TableRow,
} from '@mui/material'
import { Search, Download, Inventory2, Refresh, Visibility } from '@mui/icons-material'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { dataAcquisitionApi } from '@/api/client'
import { useProjectStore } from '@/store/projectStore'

interface SamplePreview {
  sample_id: string
  disease_state: string
  label: string
}

interface DatasetResult {
  id: string
  name: string
  repository: string
  species: string
  condition: string
  tissue: string
  sample_count: number
  data_type: string
  suitability_score: number
  suitability_reasons: string[]
  source_url?: string
  accessions?: string[]
  sample_preview?: SamplePreview[]
}

export default function DataAcquisitionPage() {
  const queryClient = useQueryClient()
  const { currentProjectId } = useProjectStore()
  const [disease, setDisease] = useState('Breast Cancer')
  const [species, setSpecies] = useState('Human,Mouse')
  const [selectedIds, setSelectedIds] = useState<string[]>([])
  const [previewDataset, setPreviewDataset] = useState<DatasetResult | null>(null)
  const [jobId, setJobId] = useState<string | null>(null)

  const searchQuery = useQuery({
    queryKey: ['data-acquisition', disease, species],
    queryFn: () => dataAcquisitionApi.search({ disease, species }).then((r) => r.data),
    enabled: true,
    staleTime: 60_000,
  })

  const downloadMutation = useMutation({
    mutationKey: ['data-acquisition', 'download'],
    mutationFn: async () => {
      if (!currentProjectId) throw new Error('Select a project before importing public data.')
      return dataAcquisitionApi.download({
        project_id: currentProjectId,
        selected_ids: selectedDatasets.map((dataset) => dataset.id),
        disease,
      }).then((response) => {
        setJobId(response.data.job_id)
        return response
      })
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['data-acquisition'] })
      queryClient.invalidateQueries({ queryKey: ['datasets'] })
    },
    onError: (error: any) => {
      const detail = error?.response?.data?.detail || 'The selected dataset download could not start.'
      console.error('download failed', detail)
      return Promise.reject(new Error(detail))
    },
  })

  const jobQuery = useQuery({
    queryKey: ['data-acquisition', 'job', jobId],
    queryFn: () => dataAcquisitionApi.getJob(jobId!).then((r) => r.data),
    enabled: !!jobId,
    refetchInterval: (query) => {
      const status = query.state.data?.status
      if (!jobId) return false
      return status === 'queued' || status === 'running' ? 1500 : false
    },
    refetchIntervalInBackground: false,
  })

  useEffect(() => {
    if (jobQuery.data?.status === 'completed') {
      queryClient.invalidateQueries({ queryKey: ['data-acquisition-datasets'] })
      queryClient.invalidateQueries({ queryKey: ['datasets'] })
    }
  }, [jobQuery.data?.status, queryClient])

  const datasetList = useMemo(() => {
    return (searchQuery.data?.datasets ?? []) as DatasetResult[]
  }, [searchQuery.data])

  const toggleDataset = (datasetId: string) => {
    setSelectedIds((current) =>
      current.includes(datasetId)
        ? current.filter((id) => id !== datasetId)
        : [...current, datasetId]
    )
  }

  const selectedDatasets = datasetList.filter((dataset) => selectedIds.includes(dataset.id))

  return (
    <Box>
      <Typography variant="h4" fontWeight={700} gutterBottom>Data Acquisition</Typography>
      <Typography variant="body1" color="text.secondary" sx={{ mb: 3 }}>
        Discover public breast-cancer and cross-species datasets, rank them by fit, and prepare the selected cohort for PathDrift analysis.
      </Typography>

      <Paper sx={{ p: 3, mb: 3 }} elevation={0} variant="outlined">
        <Stack direction={{ xs: 'column', md: 'row' }} spacing={2} alignItems={{ xs: 'stretch', md: 'center' }}>
          <input
            value={disease}
            onChange={(event) => setDisease(event.target.value)}
            placeholder="Disease"
            style={{ padding: '10px 12px', borderRadius: 8, border: '1px solid #cbd5e1', minWidth: 220 }}
          />
          <input
            value={species}
            onChange={(event) => setSpecies(event.target.value)}
            placeholder="Species"
            style={{ padding: '10px 12px', borderRadius: 8, border: '1px solid #cbd5e1', minWidth: 220 }}
          />
          <Button variant="contained" startIcon={<Search />} onClick={() => searchQuery.refetch()}>
            Search datasets
          </Button>
          <Button
            variant="outlined"
            startIcon={<Refresh />}
            onClick={() => queryClient.invalidateQueries({ queryKey: ['data-acquisition'] })}
          >
            Refresh
          </Button>
        </Stack>
      </Paper>

      {searchQuery.isLoading && (
        <Box sx={{ mb: 2 }}>
          <LinearProgress />
        </Box>
      )}

      {searchQuery.isError && (
        <Alert severity="error" sx={{ mb: 2 }}>
          Dataset search failed. Ensure the backend is running and the data acquisition service is mounted.
        </Alert>
      )}

      <Dialog open={!!previewDataset} onClose={() => setPreviewDataset(null)} maxWidth="md" fullWidth>
        <DialogTitle>{previewDataset?.name ?? 'Sample browser'}</DialogTitle>
        <DialogContent dividers>
          {previewDataset?.sample_preview && previewDataset.sample_preview.length > 0 ? (
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>Sample ID</TableCell>
                  <TableCell>Disease state</TableCell>
                  <TableCell>Label</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {previewDataset.sample_preview.map((sample) => (
                  <TableRow key={sample.sample_id} hover>
                    <TableCell>{sample.sample_id}</TableCell>
                    <TableCell>{sample.disease_state}</TableCell>
                    <TableCell>{sample.label}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          ) : (
            <Alert severity="info">No sample preview is available for this dataset yet.</Alert>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setPreviewDataset(null)}>Close</Button>
        </DialogActions>
      </Dialog>

      <Grid container spacing={3}>
        <Grid item xs={12} md={8}>
          <Stack spacing={2}>
            {datasetList.length === 0 && !searchQuery.isLoading ? (
              <Alert severity="info">No public datasets were returned for the current search.</Alert>
            ) : (
              datasetList.map((dataset) => (
                <Card key={dataset.id} variant="outlined">
                  <CardContent>
                    <Stack direction={{ xs: 'column', sm: 'row' }} justifyContent="space-between" spacing={1}>
                      <Box>
                        <Typography variant="h6" fontWeight={700}>{dataset.name}</Typography>
                        <Typography variant="caption" color="text.secondary">
                          {dataset.repository} • {dataset.species} • {dataset.condition}
                        </Typography>
                      </Box>
                      <Chip
                        label={`${dataset.suitability_score}/100`}
                        color={dataset.suitability_score >= 80 ? 'success' : dataset.suitability_score >= 60 ? 'warning' : 'default'}
                      />
                    </Stack>

                    <Box sx={{ mt: 2, display: 'flex', flexWrap: 'wrap', gap: 1 }}>
                      <Chip label={dataset.tissue} size="small" />
                      <Chip label={dataset.data_type} size="small" />
                      <Chip label={`${dataset.sample_count} samples`} size="small" />
                      {dataset.accessions?.map((accession) => (
                        <Chip key={accession} label={accession} size="small" variant="outlined" color={/^(GSE\d+|TCGA-[A-Z0-9-]+)$/i.test(accession) ? 'success' : 'default'} />
                      ))}
                    </Box>

                    <Box sx={{ mt: 2 }}>
                      {dataset.suitability_reasons.map((reason) => (
                        <Typography key={reason} variant="body2" color="text.secondary">
                          {reason}
                        </Typography>
                      ))}
                    </Box>
                  </CardContent>
                  <CardActions sx={{ px: 2, pb: 2 }}>
                    <FormControlLabel
                      control={
                        <Checkbox
                          checked={selectedIds.includes(dataset.id)}
                          onChange={() => toggleDataset(dataset.id)}
                        />
                      }
                      label="Select for download"
                    />
                    <Button size="small" startIcon={<Visibility />} onClick={() => setPreviewDataset(dataset)}>
                      Preview samples
                    </Button>
                    {dataset.source_url && (
                      <Button size="small" href={dataset.source_url} target="_blank" rel="noreferrer">
                        Source
                      </Button>
                    )}
                  </CardActions>
                </Card>
              ))
            )}
          </Stack>
        </Grid>

        <Grid item xs={12} md={4}>
          <Paper sx={{ p: 3 }} elevation={0} variant="outlined">
            <Stack spacing={2}>
              <Box display="flex" alignItems="center" gap={1}>
                <Inventory2 color="primary" />
                <Typography variant="h6" fontWeight={700}>Selected cohort</Typography>
              </Box>

              {selectedDatasets.length === 0 ? (
                <Alert severity="info">No datasets selected yet.</Alert>
              ) : (
                <>
                  {selectedDatasets.map((dataset) => (
                    <Box key={dataset.id} sx={{ p: 1.5, border: '1px solid', borderColor: 'divider', borderRadius: 1 }}>
                      <Typography variant="subtitle2" fontWeight={600}>{dataset.name}</Typography>
                      <Typography variant="caption" color="text.secondary">{dataset.repository}</Typography>
                    </Box>
                  ))}
                </>
              )}

              <Divider />

              <Button
                variant="contained"
                color="primary"
                startIcon={<Download />}
                onClick={() => downloadMutation.mutate()}
                disabled={selectedDatasets.length === 0 || downloadMutation.isPending}
              >
                {downloadMutation.isPending ? 'Downloading...' : 'Download selected datasets'}
              </Button>

              {downloadMutation.isSuccess && (
                <Alert severity={jobQuery.data?.status === 'completed' ? 'success' : 'info'}>
                  {jobQuery.data?.status === 'completed'
                    ? 'Download completed and the dataset is now available in the Datasets table.'
                    : jobQuery.data?.status === 'running'
                      ? `Download in progress: ${jobQuery.data.progress}% - ${jobQuery.data.message}`
                      : 'Download job started successfully. Use the backend job status endpoint to monitor completion.'}
                </Alert>
              )}

              {downloadMutation.isError && (
                <Alert severity="error">
                  {downloadMutation.error instanceof Error
                    ? downloadMutation.error.message
                    : 'The selected dataset download could not start.'}
                </Alert>
              )}

              <Box>
                <Typography variant="subtitle2" color="text.secondary" gutterBottom>Search details</Typography>
                <Typography variant="body2">Disease: {disease}</Typography>
                <Typography variant="body2">Species: {species}</Typography>
              </Box>
            </Stack>
          </Paper>
        </Grid>
      </Grid>
    </Box>
  )
}
