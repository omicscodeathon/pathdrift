import { useEffect, useState } from 'react'
import {
  Alert, Box, Button, Chip, CircularProgress, Grid, LinearProgress,
  MenuItem, Paper, Stack, TextField, Typography,
} from '@mui/material'
import { Refresh } from '@mui/icons-material'
import { useQuery } from '@tanstack/react-query'
import Plot from 'react-plotly.js'
import { dataQualityApi, datasetApi } from '@/api/client'
import type { Dataset } from '@/types'
import { useProjectStore } from '@/store/projectStore'

const GROUP_COLORS = ['#137c8b', '#d46a43', '#526ab2', '#55865d', '#a04f7c']

function SampleBar({ label, count, maxCount, color }: {
  label: string
  count: number | null
  maxCount: number
  color: string
}) {
  const width = count == null ? 0 : Math.max(2, (count / maxCount) * 100)

  return (
    <Stack direction="row" spacing={1.5} alignItems="center">
      <Typography variant="body2" sx={{ width: 140, flexShrink: 0 }}>{label}</Typography>
      <Box sx={{ flex: 1, minWidth: 40, height: 18, bgcolor: 'action.hover', overflow: 'hidden' }}>
        {count != null && <Box sx={{ width: `${width}%`, height: '100%', bgcolor: color, transition: 'width 240ms ease' }} />}
      </Box>
      <Typography variant="body2" fontWeight={700} sx={{ width: 72, textAlign: 'right' }}>
        {count == null ? '—' : count.toLocaleString()}
      </Typography>
    </Stack>
  )
}

export default function DataQualityPage() {
  const { currentProjectId, currentDatasetId, setCurrentDataset } = useProjectStore()
  const [selectedDatasetId, setSelectedDatasetId] = useState(currentDatasetId ?? '')

  const { data: datasets = [], isLoading: datasetsLoading } = useQuery({
    queryKey: ['datasets', currentProjectId],
    queryFn: () => currentProjectId
      ? datasetApi.list(currentProjectId).then((response) => response.data as Dataset[])
      : [],
    enabled: !!currentProjectId,
  })

  useEffect(() => {
    if (!datasets.length) {
      setSelectedDatasetId('')
      if (currentDatasetId) setCurrentDataset(null)
      return
    }

    const currentIsAvailable = datasets.some((dataset) => String(dataset.id) === String(currentDatasetId))
    const nextDatasetId = currentIsAvailable ? String(currentDatasetId) : String(datasets[0].id)
    setSelectedDatasetId(nextDatasetId)
    if (nextDatasetId !== currentDatasetId) setCurrentDataset(nextDatasetId)
  }, [currentDatasetId, datasets, setCurrentDataset])

  const qualityQuery = useQuery({
    queryKey: ['dataset-quality', selectedDatasetId],
    queryFn: () => dataQualityApi.get(selectedDatasetId).then((response) => response.data),
    enabled: !!selectedDatasetId,
  })

  const quality = qualityQuery.data
  const maxSampleCount = Math.max(quality?.before_sample_count ?? 0, quality?.after_sample_count ?? 0, 1)
  const groups = [...new Set((quality?.pca_points ?? []).map((point) => point.group))]
  const plotData = groups.map((group, index) => {
    const groupPoints = quality?.pca_points.filter((point) => point.group === group) ?? []
    return {
      type: 'scatter' as const,
      mode: 'markers' as const,
      name: group,
      x: groupPoints.map((point) => point.pc1),
      y: groupPoints.map((point) => point.pc2),
      text: groupPoints.map((point) => point.sample_id),
      hovertemplate: '%{text}<extra>%{fullData.name}</extra>',
      marker: { size: 8, color: GROUP_COLORS[index % GROUP_COLORS.length], opacity: 0.82 },
    }
  })
  const varianceLabels = quality?.explained_variance_ratio.map((ratio) => `${(ratio * 100).toFixed(1)}%`) ?? []

  return (
    <Box sx={{ maxWidth: 1200, mx: 'auto' }}>
      <Stack direction={{ xs: 'column', sm: 'row' }} justifyContent="space-between" alignItems={{ xs: 'stretch', sm: 'center' }} spacing={2} sx={{ mb: 3 }}>
        <Box>
          <Typography variant="h4" fontWeight={800}>DATA QUALITY</Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
            Sample retention and expression-profile structure for the selected dataset.
          </Typography>
        </Box>
        <Stack direction="row" spacing={1}>
          <TextField
            select
            size="small"
            label="Dataset"
            value={selectedDatasetId}
            onChange={(event) => {
              setSelectedDatasetId(event.target.value)
              setCurrentDataset(event.target.value || null)
            }}
            disabled={datasets.length === 0}
            sx={{ minWidth: { xs: 180, sm: 260 } }}
          >
            {datasets.map((dataset) => (
              <MenuItem key={dataset.id} value={String(dataset.id)}>
                {dataset.name} · {dataset.species}
              </MenuItem>
            ))}
          </TextField>
          <Button
            variant="outlined"
            aria-label="Refresh quality results"
            onClick={() => qualityQuery.refetch()}
            disabled={!selectedDatasetId || qualityQuery.isFetching}
          >
            <Refresh />
          </Button>
        </Stack>
      </Stack>

      {!currentProjectId && <Alert severity="info">Select or create a project before reviewing dataset quality.</Alert>}
      {currentProjectId && !datasetsLoading && datasets.length === 0 && (
        <Alert severity="info">This project has no datasets yet. Upload or acquire a dataset to begin sample QC.</Alert>
      )}
      {qualityQuery.isError && <Alert severity="error" sx={{ mb: 2 }}>Dataset QC could not be calculated. Check that the expression matrix is available and valid.</Alert>}
      {qualityQuery.isLoading && <LinearProgress sx={{ mb: 2 }} />}

      {quality && (
        <>
          <Paper variant="outlined" sx={{ p: { xs: 2, md: 3 }, mb: 3 }}>
            <Stack direction={{ xs: 'column', sm: 'row' }} justifyContent="space-between" alignItems={{ xs: 'flex-start', sm: 'center' }} spacing={1} sx={{ mb: 2.5 }}>
              <Box>
                <Typography variant="h6" fontWeight={700}>Sample QC</Typography>
                <Typography variant="body2" color="text.secondary">
                  {datasets.find((dataset) => String(dataset.id) === selectedDatasetId)?.name ?? quality.dataset_id}
                </Typography>
              </Box>
              <Chip
                size="small"
                color={quality.preprocessing_status === 'completed' ? 'success' : 'default'}
                label={quality.preprocessing_status === 'completed' ? 'Filtered matrix available' : 'Preprocessing not completed'}
              />
            </Stack>
            <Stack spacing={2.25}>
              <SampleBar label="Before filtering" count={quality.before_sample_count} maxCount={maxSampleCount} color="#1677a8" />
              <SampleBar label="After filtering" count={quality.after_sample_count} maxCount={maxSampleCount} color="#25856b" />
            </Stack>
            {quality.outlier_samples.length > 0 && (
              <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 2 }}>
                Removed outliers: {quality.outlier_samples.join(', ')}
              </Typography>
            )}
          </Paper>

          <Paper variant="outlined" sx={{ p: { xs: 1.5, md: 2.5 } }}>
            <Stack direction={{ xs: 'column', sm: 'row' }} justifyContent="space-between" alignItems={{ xs: 'flex-start', sm: 'center' }} spacing={1} sx={{ px: 0.5, mb: 1 }}>
              <Box>
                <Typography variant="h6" fontWeight={700}>PCA</Typography>
                <Typography variant="body2" color="text.secondary">
                  {quality.pca_source === 'preprocessed' ? 'Computed from the filtered expression matrix.' : 'Computed from the raw expression matrix; preprocessing has not completed.'}
                </Typography>
              </Box>
              <Chip size="small" variant="outlined" label={`${quality.pca_gene_count.toLocaleString()} variable genes`} />
            </Stack>
            {quality.pca_message ? (
              <Alert severity="info" sx={{ mt: 2 }}>{quality.pca_message}</Alert>
            ) : (
              <Plot
                data={plotData}
                layout={{
                  autosize: true,
                  height: 430,
                  margin: { l: 64, r: 24, t: 20, b: 60 },
                  paper_bgcolor: 'rgba(0,0,0,0)',
                  plot_bgcolor: 'rgba(0,0,0,0)',
                  hovermode: 'closest',
                  legend: { orientation: 'h', y: -0.2 },
                  xaxis: { title: { text: `PC1${varianceLabels[0] ? ` (${varianceLabels[0]})` : ''}` }, zeroline: false, gridcolor: '#e2e8f0' },
                  yaxis: { title: { text: `PC2${varianceLabels[1] ? ` (${varianceLabels[1]})` : ''}` }, zeroline: false, gridcolor: '#e2e8f0' },
                  font: { family: 'Inter, sans-serif', color: '#475569' },
                }}
                config={{ responsive: true, displaylogo: false, modeBarButtonsToRemove: ['lasso2d', 'select2d'] }}
                style={{ width: '100%', height: 430 }}
                useResizeHandler
              />
            )}
            {quality.pca_points.length > 0 && (
              <Typography variant="caption" color="text.secondary" sx={{ display: 'block', px: 0.5, mt: 1 }}>
                Each point is a sample. Colors use disease-state metadata when available; otherwise samples are shown as unlabeled.
              </Typography>
            )}
          </Paper>
        </>
      )}
    </Box>
  )
}