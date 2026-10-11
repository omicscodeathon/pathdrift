import { useEffect, useState } from 'react'
import {
  Alert, Box, CircularProgress, Grid, LinearProgress, Paper,
  Table, TableBody, TableCell, TableContainer, TableHead, TableRow, Typography,
} from '@mui/material'
import { useQuery } from '@tanstack/react-query'
import Plot from 'react-plotly.js'
import {
  AcquisitionQCDataset, AcquisitionQCDatasetReport, AcquisitionQCSampleRow, runQcApi,
} from '@/api/client'

const QC_IMAGES = [
  { name: 'pca.png', title: 'Saved PCA plot' },
  { name: 'sample_correlation.png', title: 'Saved sample correlation plot' },
  { name: 'sample_clustering.png', title: 'Saved sample clustering plot' },
]

function QcArtifactImage({ accession, artifactName, title }: { accession: string; artifactName: string; title: string }) {
  const imageQuery = useQuery({
    queryKey: ['acquisition-qc-image', accession, artifactName],
    queryFn: () => runQcApi.acquisitionArtifact(accession, artifactName).then((response) => response.data),
  })
  const [imageUrl, setImageUrl] = useState('')

  useEffect(() => {
    if (!imageQuery.data) {
      setImageUrl('')
      return
    }
    const url = URL.createObjectURL(imageQuery.data)
    setImageUrl(url)
    return () => URL.revokeObjectURL(url)
  }, [imageQuery.data])

  return (
    <Paper variant="outlined" sx={{ p: 1.5, height: '100%' }}>
      <Typography variant="subtitle1" fontWeight={700} sx={{ mb: 1 }}>{title}</Typography>
      {imageQuery.isLoading && <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}><CircularProgress size={24} /></Box>}
      {imageQuery.isError && <Alert severity="error">QC image could not be loaded: {(imageQuery.error as Error).message}</Alert>}
      {imageUrl && <Box component="img" src={imageUrl} alt={`${accession} ${title}`} sx={{ display: 'block', width: '100%', height: 'auto', objectFit: 'contain' }} />}
    </Paper>
  )
}

function formatValue(value: string | number | boolean | null | undefined): string {
  if (value === null || value === undefined || value === '') return '—'
  if (typeof value === 'number') return Number.isInteger(value) ? value.toLocaleString() : value.toFixed(3)
  if (typeof value === 'boolean') return value ? 'Yes' : 'No'
  return value
}

function formatSampleValue(column: string, value: string | number | boolean | null): string {
  if (typeof value === 'number' && (column === 'missing_fraction' || column === 'zero_fraction')) {
    return `${(value * 100).toFixed(2)}%`
  }
  return formatValue(value)
}

function AcquisitionDatasetQC({ dataset }: { dataset: AcquisitionQCDataset }) {
  const reportQuery = useQuery({
    queryKey: ['acquisition-qc-dataset', dataset.accession],
    queryFn: () => runQcApi.acquisitionDataset(dataset.accession).then((response) => response.data),
    enabled: dataset.status === 'QC complete',
  })
  const report = reportQuery.data as AcquisitionQCDatasetReport | undefined
  const samples = report?.sample_qc ?? []
  const coordinates = report?.pca_coordinates ?? []
  const pcaSampleIds = new Set(coordinates.map((point) => point.sample_id))
  const missingPcaSampleIds = samples
    .map((sample) => String(sample.sample_id))
    .filter((sampleId) => !pcaSampleIds.has(sampleId))
  const coordinateColumns = coordinates.length
    ? Object.keys(coordinates[0]).filter((column) => /^PC\d+$/.test(column))
    : []
  const correlation = report?.correlation
  const sampleColumns = [
    'sample_id', 'disease_state', 'cluster', 'library_size', 'detected_genes',
    'missing_fraction', 'zero_fraction', 'mean_expression', 'median_expression',
    'outlier_score', 'is_outlier', 'excluded', 'exclusion_reason',
  ]
  const images = QC_IMAGES.filter((image) => dataset.artifacts.includes(image.name))

  return (
    <Paper component="section" variant="outlined" sx={{ p: 2.25, mb: 2.5 }}>
      <Typography variant="h5" fontWeight={800}>{dataset.accession} · {dataset.species}</Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
        {dataset.name} · {dataset.tissue} · {dataset.condition}
        {dataset.source_data_type ? ` · ${dataset.source_data_type}` : ''}
      </Typography>

      {dataset.status !== 'QC complete' && (
        <Alert severity="error">Quality control is not complete for this acquired dataset.</Alert>
      )}
      {reportQuery.isLoading && <LinearProgress sx={{ my: 2 }} />}
      {reportQuery.isError && <Alert severity="error" sx={{ mb: 2 }}>
        QC results for {dataset.accession} could not be loaded: {(reportQuery.error as Error).message}
      </Alert>}
      {report && (
        <>
          <Grid container spacing={1.5} sx={{ mb: 2 }}>
            {[
              ['Samples retained', `${report.summary.retained_samples} / ${report.summary.initial_samples}`],
              ['Genes retained', `${report.summary.retained_genes.toLocaleString()} / ${report.summary.initial_genes.toLocaleString()}`],
              ['QC normalization', report.summary.normalization_method],
              ['Outliers flagged', String(report.summary.outliers?.length ?? 0)],
            ].map(([label, value]) => (
              <Grid item xs={6} md={3} key={label}>
                <Paper variant="outlined" sx={{ p: 1.5, height: '100%' }}>
                  <Typography variant="caption" fontWeight={700} color="text.secondary">{label}</Typography>
                  <Typography variant="h6" fontWeight={800}>{value}</Typography>
                </Paper>
              </Grid>
            ))}
          </Grid>

          <Box sx={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr)', gap: 2, mb: 2 }}>
            <Paper variant="outlined" sx={{ p: { xs: 1.5, md: 2 } }}>
              <Typography variant="h6" fontWeight={700}>PCA by sample</Typography>
              <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
                Each point is one sample. Hover over a point to see its sample ID and PC coordinates.
              </Typography>
              {coordinates.length ? <Box sx={{ width: '100%', maxWidth: 1100, mx: 'auto' }}><Plot
                  data={[{
                    type: 'scatter', mode: 'markers', name: dataset.accession,
                    x: coordinates.map((point) => Number(point.PC1 ?? 0)),
                    y: coordinates.map((point) => Number(point.PC2 ?? 0)),
                    text: coordinates.map((point) => String(point.sample_id)),
                    marker: {
                      size: 9,
                      color: coordinates.map((point) => Number(point.cluster ?? 0)),
                      colorscale: 'Viridis',
                      showscale: true,
                      symbol: coordinates.map((point) => point.is_outlier ? 'diamond' : 'circle'),
                    },
                    hovertemplate: '%{text}<br>PC1 %{x:.3f}<br>PC2 %{y:.3f}<extra></extra>',
                  }]}
                  layout={{ autosize: true, height: 480, margin: { l: 70, r: 35, t: 20, b: 70 }, xaxis: { title: { text: 'PC1' }, zeroline: true }, yaxis: { title: { text: 'PC2' }, zeroline: true }, showlegend: false }}
                  config={{ responsive: true, displaylogo: false }} style={{ width: '100%' }} useResizeHandler
                /></Box> : <Typography color="text.secondary" sx={{ py: 4 }}>PCA coordinates are not available.</Typography>}
            </Paper>

            <Paper variant="outlined" sx={{ p: 1.5 }}>
              <Typography variant="h6" fontWeight={700}>PCA coordinates by sample</Typography>
              <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
                Showing {coordinates.length} of {samples.length} QC samples.
              </Typography>
              {!!missingPcaSampleIds.length && (
                <Alert severity="warning" sx={{ mb: 1 }}>
                  PCA coordinates are missing for: {missingPcaSampleIds.join(', ')}
                </Alert>
              )}
              <TableContainer sx={{ width: '100%', overflowX: 'auto' }}>
                <Table size="small" sx={{ minWidth: 560 }}>
                  <TableHead><TableRow>
                    {['sample_id', ...coordinateColumns].map((column) => <TableCell key={column}>{column.replace(/_/g, ' ')}</TableCell>)}
                  </TableRow></TableHead>
                  <TableBody>{coordinates.map((row) => (
                    <TableRow key={row.sample_id}>
                      {['sample_id', ...coordinateColumns].map((column) => (
                        <TableCell key={column}>{formatValue(row[column])}</TableCell>
                      ))}
                    </TableRow>
                  ))}</TableBody>
                </Table>
              </TableContainer>
            </Paper>

            <Paper variant="outlined" sx={{ p: { xs: 1.5, md: 2 } }}>
              <Typography variant="h6" fontWeight={700}>Sample correlation</Typography>
              <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
                Correlation matrix across {correlation?.samples.length ?? 0} samples.
              </Typography>
              {correlation?.samples.length ? <Plot
                data={[{
                  type: 'heatmap',
                  z: correlation.values,
                  x: correlation.samples,
                  y: correlation.samples,
                  zmin: -1,
                  zmax: 1,
                  colorscale: 'RdBu',
                  reversescale: true,
                  colorbar: { title: { text: 'Pearson r' } },
                  hovertemplate: '%{y} vs %{x}<br>r=%{z:.3f}<extra></extra>',
                }]}
                layout={{ autosize: true, height: 560, margin: { l: 120, r: 55, t: 25, b: 130 }, xaxis: { tickangle: -45, automargin: true }, yaxis: { autorange: 'reversed', automargin: true } }}
                config={{ responsive: true, displaylogo: false }} style={{ width: '100%' }} useResizeHandler
              /> : <Typography color="text.secondary" sx={{ py: 4 }}>Sample correlations are not available.</Typography>}
            </Paper>
          </Box>

          {!!images.length && (
            <Grid container spacing={2} sx={{ mb: 2 }}>
              {images.map((image) => (
                <Grid item xs={12} lg={6} key={image.name}>
                  <QcArtifactImage accession={dataset.accession} artifactName={image.name} title={image.title} />
                </Grid>
              ))}
            </Grid>
          )}

          <Paper variant="outlined" sx={{ p: 1.5 }}>
            <Typography variant="h6" fontWeight={700} sx={{ mb: 1 }}>
              Sample-level QC · {dataset.species} · {samples.length} samples
            </Typography>
            <TableContainer sx={{ maxHeight: 470 }}>
              <Table size="small" stickyHeader sx={{ minWidth: 1200 }}>
                <TableHead><TableRow>
                  {sampleColumns.map((column) => <TableCell key={column}>{column.replace(/_/g, ' ')}</TableCell>)}
                </TableRow></TableHead>
                <TableBody>{samples.map((row: AcquisitionQCSampleRow, index) => (
                  <TableRow key={`${row.sample_id}-${index}`}>
                    {sampleColumns.map((column) => (
                      <TableCell key={column}>{formatSampleValue(column, row[column] ?? null)}</TableCell>
                    ))}
                  </TableRow>
                ))}</TableBody>
              </Table>
            </TableContainer>
            <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 1.25 }}>
              Outliers are flagged in PCA space; samples are retained unless the run configuration explicitly excludes them.
              {dataset.gene_identifier_type.toLowerCase().includes('symbol')
                ? ' QC uses the GEO-provided gene symbols as source identifiers; these are not reported as Ensembl-validated IDs.'
                : ''}
            </Typography>
            <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 0.5 }}>
              QC result: {report.run_id} · {new Date(report.created_at).toLocaleString()}
            </Typography>
          </Paper>
        </>
      )}
    </Paper>
  )
}

export default function RunQCPage() {
  const datasetsQuery = useQuery({
    queryKey: ['acquisition-qc-datasets'],
    queryFn: () => runQcApi.acquisitionDatasets().then((response) => response.data),
  })
  const datasets = datasetsQuery.data ?? []
  const humanDatasets = datasets.filter((dataset) => dataset.species.toLowerCase() === 'human')
  const mouseDatasets = datasets.filter((dataset) => dataset.species.toLowerCase() === 'mouse')
  const otherDatasets = datasets.filter((dataset) => !['human', 'mouse'].includes(dataset.species.toLowerCase()))

  return (
    <Box sx={{ maxWidth: 1440, mx: 'auto' }}>
      <Typography variant="h4" fontWeight={800} gutterBottom>ACQUISITION QC</Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2.5 }}>
        One current quality-control result per acquired dataset. Repeated analysis-run copies are consolidated by accession.
      </Typography>

      {datasetsQuery.isLoading && <LinearProgress sx={{ mb: 2 }} />}
      {datasetsQuery.isError && <Alert severity="error" sx={{ mb: 2 }}>
        Acquired dataset QC status could not be loaded: {(datasetsQuery.error as Error).message}
      </Alert>}
      {!datasetsQuery.isLoading && !datasetsQuery.isError && datasets.length === 0 && (
        <Alert severity="info" sx={{ mb: 2 }}>No acquired datasets are registered in the acquisition manifest.</Alert>
      )}

      {!!humanDatasets.length && (
        <>
          <Typography variant="h5" fontWeight={800} sx={{ mb: 1.5 }}>Human datasets</Typography>
          {humanDatasets.map((dataset) => <AcquisitionDatasetQC key={dataset.accession} dataset={dataset} />)}
        </>
      )}
      {!!mouseDatasets.length && (
        <>
          <Typography variant="h5" fontWeight={800} sx={{ mb: 1.5, mt: 3 }}>Mouse datasets</Typography>
          {mouseDatasets.map((dataset) => <AcquisitionDatasetQC key={dataset.accession} dataset={dataset} />)}
        </>
      )}
      {!!otherDatasets.length && (
        <>
          <Typography variant="h5" fontWeight={800} sx={{ mb: 1.5, mt: 3 }}>Other datasets</Typography>
          {otherDatasets.map((dataset) => <AcquisitionDatasetQC key={dataset.accession} dataset={dataset} />)}
        </>
      )}
    </Box>
  )
}
