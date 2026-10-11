import { useEffect, useMemo, useState } from 'react'
import {
  Alert, Box, Button, Card, CardActions, CardContent, Checkbox, Chip, Divider,
  FormControlLabel, Grid, LinearProgress, Paper, Stack, Typography,
} from '@mui/material'
import { Download, Inventory2, Refresh, Search } from '@mui/icons-material'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { dataAcquisitionApi } from '@/api/client'
import { useProjectStore } from '@/store/projectStore'

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
}

interface AcquiredDataset {
  id: string
  name: string
  repository: string
  accession: string
  species: string
  sample_count: number
  gene_count?: number
  status: string
  normalization_method?: string
}

interface AcquisitionJob {
  status: string
  progress: number
  message: string
  error_message?: string
}

export default function DataAcquisitionPage() {
  const queryClient = useQueryClient()
  const { currentProjectId, currentAnalysisId, currentDatasetId, preprocessingJobId, setCurrentDataset } = useProjectStore()
  const [disease, setDisease] = useState('Breast Cancer')
  const [species, setSpecies] = useState('Human,Mouse')
  const [selectedIds, setSelectedIds] = useState<string[]>([])
  const [jobId, setJobId] = useState<string | null>(null)

  const searchQuery = useQuery({
    queryKey: ['data-acquisition', disease, species],
    queryFn: () => dataAcquisitionApi.search({ disease, species }).then((response) => response.data),
    staleTime: 60_000,
  })
  const acquiredQuery = useQuery({
    queryKey: ['data-acquisition-datasets'],
    queryFn: () => dataAcquisitionApi.listDatasets().then((response) => response.data as AcquiredDataset[]),
    refetchInterval: (query) => {
      const status = query.state.data?.find((item: AcquiredDataset) => item.status === 'queued' || item.status === 'running')
      return status ? 2000 : false
    },
  })

  const datasetList = useMemo(() => (searchQuery.data?.datasets ?? []) as DatasetResult[], [searchQuery.data])
  const selectedDatasets = datasetList.filter((dataset) => selectedIds.includes(dataset.id))

  const downloadMutation = useMutation({
    mutationKey: ['data-acquisition', 'download'],
    mutationFn: async () => {
      if (!currentProjectId) throw new Error('Select a project before importing public data.')
      const response = await dataAcquisitionApi.download({
        project_id: currentProjectId,
        selected_ids: selectedDatasets.map((dataset) => dataset.id),
        disease,
      })
      setJobId(response.data.job_id)
      return response
    },
    onSuccess: async () => {
      queryClient.invalidateQueries({ queryKey: ['datasets'] })
      queryClient.invalidateQueries({ queryKey: ['data-acquisition-datasets'] })
      const refreshed = await dataAcquisitionApi.listDatasets().then((response) => response.data as AcquiredDataset[])
      const newestDataset = refreshed[refreshed.length - 1]
      if (newestDataset?.id) {
        setCurrentDataset(String(newestDataset.id))
      }
    },
  })

  const jobQuery = useQuery({
    queryKey: ['data-acquisition', 'job', jobId],
    queryFn: () => dataAcquisitionApi.getJob(jobId!).then((response) => response.data as AcquisitionJob),
    enabled: !!jobId,
    refetchInterval: (query) => {
      const currentStatus = query.state.data?.status
      return currentStatus === 'queued' || currentStatus === 'running' ? 1500 : false
    },
  })

  useEffect(() => {
    if (jobQuery.data?.status === 'completed') {
      queryClient.invalidateQueries({ queryKey: ['data-acquisition-datasets'] })
      queryClient.invalidateQueries({ queryKey: ['datasets'] })
    }
  }, [jobQuery.data?.status, queryClient])

  const toggleDataset = (datasetId: string) => {
    setSelectedIds((current) => current.includes(datasetId)
      ? current.filter((id) => id !== datasetId)
      : [...current, datasetId])
  }

  return (
    <Box>
      <Typography variant="h4" fontWeight={700} gutterBottom>Data Acquisition</Typography>
      <Typography variant="body1" color="text.secondary" sx={{ mb: 3 }}>
        Discover verified public accessions, acquire their expression matrices, and register processed cohorts to the current project.
      </Typography>

      <Paper sx={{ p: 2, mb: 2 }} variant="outlined">
        <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1} flexWrap="wrap" useFlexGap>
          <Chip size="small" label={`Project: ${currentProjectId ?? 'unselected'}`} color={currentProjectId ? 'primary' : 'default'} />
          <Chip size="small" label={`Analysis: ${currentAnalysisId ?? 'unselected'}`} color={currentAnalysisId ? 'secondary' : 'default'} />
          <Chip size="small" label={`Dataset: ${currentDatasetId ?? 'unselected'}`} color={currentDatasetId ? 'success' : 'default'} />
          <Chip size="small" label={`Preprocessing: ${preprocessingJobId ?? 'pending'}`} color={preprocessingJobId ? 'info' : 'default'} />
        </Stack>
      </Paper>

      <Paper sx={{ p: 2, mb: 2 }} variant="outlined">
        <Stack direction={{ xs: 'column', md: 'row' }} spacing={2} alignItems={{ xs: 'stretch', md: 'center' }}>
          <input value={disease} onChange={(event) => setDisease(event.target.value)} aria-label="Disease" />
          <input value={species} onChange={(event) => setSpecies(event.target.value)} aria-label="Species" />
          <Button variant="contained" startIcon={<Search />} onClick={() => searchQuery.refetch()}>Search sources</Button>
          <Button variant="outlined" startIcon={<Refresh />} onClick={() => queryClient.invalidateQueries({ queryKey: ['data-acquisition'] })}>Refresh</Button>
        </Stack>
      </Paper>

      <Alert severity="info" sx={{ mb: 2 }}>
        TCGA-BRCA downloads include primary tumors and adjacent-normal samples. GEO GSE155577 contains mouse mammary tumor samples only; cross-species tumor-versus-normal drift remains unavailable until a real mouse-normal cohort is acquired.
      </Alert>

      {searchQuery.isLoading && <LinearProgress sx={{ mb: 2 }} />}
      {searchQuery.isError && <Alert severity="error" sx={{ mb: 2 }}>Public-source discovery failed. Check backend connectivity and retry.</Alert>}

      <Grid container spacing={3}>
        <Grid item xs={12} md={8}>
          <Stack spacing={2}>
            {datasetList.length === 0 && !searchQuery.isLoading ? (
              <Alert severity="info">No supported public accessions were returned.</Alert>
            ) : datasetList.map((dataset) => (
              <Card key={dataset.id} variant="outlined">
                <CardContent>
                  <Stack direction={{ xs: 'column', sm: 'row' }} justifyContent="space-between" spacing={1}>
                    <Box>
                      <Typography variant="h6" fontWeight={700}>{dataset.name}</Typography>
                      <Typography variant="body2" color="text.secondary">{dataset.repository} · {dataset.species} · {dataset.condition}</Typography>
                    </Box>
                    <Chip label={`${dataset.suitability_score}/100`} color={dataset.suitability_score >= 80 ? 'success' : 'default'} />
                  </Stack>
                  <Stack direction="row" flexWrap="wrap" gap={1} sx={{ mt: 2 }}>
                    <Chip size="small" label={dataset.tissue} />
                    <Chip size="small" label={dataset.data_type} />
                    <Chip size="small" label={`${dataset.sample_count} samples`} />
                    {dataset.accessions?.map((accession) => <Chip size="small" variant="outlined" key={accession} label={accession} />)}
                  </Stack>
                  <Box sx={{ mt: 2 }}>
                    {dataset.suitability_reasons.map((reason) => <Typography key={reason} variant="body2" color="text.secondary">{reason}</Typography>)}
                  </Box>
                </CardContent>
                <CardActions sx={{ px: 2, pb: 2 }}>
                  <FormControlLabel
                    control={<Checkbox checked={selectedIds.includes(dataset.id)} onChange={() => toggleDataset(dataset.id)} />}
                    label="Select accession"
                  />
                  {dataset.source_url && <Button size="small" href={dataset.source_url} target="_blank" rel="noreferrer">Open source record</Button>}
                </CardActions>
              </Card>
            ))}
          </Stack>
        </Grid>

        <Grid item xs={12} md={4}>
          <Paper sx={{ p: 2.5 }} variant="outlined">
            <Stack spacing={2}>
              <Stack direction="row" spacing={1} alignItems="center">
                <Inventory2 color="primary" />
                <Typography variant="h6" fontWeight={700}>Selected sources</Typography>
              </Stack>
              {!currentProjectId && <Alert severity="warning">Select a project before starting acquisition.</Alert>}
              {selectedDatasets.length === 0
                ? <Alert severity="info">Select one or more verified accessions.</Alert>
                : selectedDatasets.map((dataset) => (
                  <Box key={dataset.id} sx={{ p: 1.5, border: '1px solid', borderColor: 'divider', borderRadius: 1 }}>
                    <Typography variant="subtitle2" fontWeight={600}>{dataset.name}</Typography>
                    <Typography variant="caption" color="text.secondary">{dataset.repository} · {dataset.accessions?.join(', ')}</Typography>
                  </Box>
                ))}
              <Divider />
              <Button
                variant="contained"
                startIcon={<Download />}
                onClick={() => downloadMutation.mutate()}
                disabled={!currentProjectId || selectedDatasets.length === 0 || downloadMutation.isPending}
              >
                {downloadMutation.isPending ? 'Acquiring and preprocessing…' : 'Acquire and preprocess'}
              </Button>
              {downloadMutation.isPending && <LinearProgress />}
              {jobQuery.data && <Alert severity={jobQuery.data.status === 'completed' ? 'success' : jobQuery.data.status === 'failed' ? 'error' : 'info'}>
                {jobQuery.data.error_message || jobQuery.data.message} {jobQuery.data.status === 'running' ? `${jobQuery.data.progress}%` : ''}
              </Alert>}
              {downloadMutation.isError && <Alert severity="error">{downloadMutation.error instanceof Error ? downloadMutation.error.message : 'Acquisition failed.'}</Alert>}
            </Stack>
          </Paper>
        </Grid>
      </Grid>

      <Box sx={{ mt: 4 }}>
        <Typography variant="h6" fontWeight={700} gutterBottom>Acquired public matrices</Typography>
        {acquiredQuery.isLoading ? <LinearProgress /> : acquiredQuery.data?.length ? (
          <Paper variant="outlined">
            {acquiredQuery.data.map((dataset, index) => (
              <Box key={dataset.id} sx={{ p: 2, borderBottom: index < acquiredQuery.data!.length - 1 ? '1px solid' : 0, borderColor: 'divider' }}>
                <Stack direction={{ xs: 'column', sm: 'row' }} justifyContent="space-between" spacing={1}>
                  <Box>
                    <Typography variant="subtitle2" fontWeight={700}>{dataset.name}</Typography>
                    <Typography variant="body2" color="text.secondary">{dataset.repository} · {dataset.accession} · {dataset.species}</Typography>
                  </Box>
                  <Stack direction="row" spacing={1}>
                    <Chip size="small" label={`${dataset.gene_count ?? 0} genes`} />
                    <Chip size="small" label={`${dataset.sample_count} samples`} />
                    <Chip size="small" label={dataset.status} color={dataset.status === 'ready' ? 'success' : 'default'} />
                  </Stack>
                </Stack>
                {dataset.normalization_method && <Typography variant="caption" color="text.secondary">Preprocessing: {dataset.normalization_method}</Typography>}
              </Box>
            ))}
          </Paper>
        ) : <Alert severity="info">No public matrices have been registered yet.</Alert>}
      </Box>
    </Box>
  )
}