import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Alert, Box, Button, Chip, CircularProgress, FormControl, Grid, InputLabel, LinearProgress, MenuItem, Paper, Select, Stack, Table, TableBody, TableCell, TableContainer, TableHead, TablePagination, TableRow, TextField, Typography } from '@mui/material'
import Plot from 'react-plotly.js'
import { useQuery } from '@tanstack/react-query'
import { phase3Api } from '@/api/client'
import { asRecord, display, fetchAllDeg, PAGE_SIZE, RunHeader, ResultState, StatCard, useNetworks, useObjectUrl, useRunId, useSpeciesComparisons, type DEG, type Species } from './analysis/shared'

export function DifferentialExpressionPage({ savedRunId }: { savedRunId?: string } = {}) {
  const routeRunId = useRunId()
  const runId = savedRunId ?? routeRunId
  const navigate = useNavigate()
  const { data: runNetworks = [] } = useNetworks(runId)
  const { comparisons, summary: runSummary, isLoading: summaryLoading, isError: summaryError } = useSpeciesComparisons(runId)
  const [species, setSpecies] = useState<Species>('human')
  const available = comparisons.filter((item) => item.species === species)
  const [comparison, setComparison] = useState('')
  useEffect(() => {
    if (!available.some((item) => item.comparison === comparison)) setComparison(available[0]?.comparison ?? '')
  }, [available, comparison])
  const { data: genes = [], isLoading, isError } = useQuery({
    queryKey: ['phase3-deg-all', runId, species, comparison],
    queryFn: () => fetchAllDeg(runId!, species, comparison),
    enabled: !!runId && !!comparison,
  })
  const {
    data: artifactNames = [],
    isLoading: artifactsLoading,
    isError: artifactsError,
  } = useQuery({
    queryKey: ['phase3-deg-artifacts', runId, species, comparison],
    queryFn: () => phase3Api.degArtifacts(runId!, species, comparison)
      .then((response) => (response.data as { items: string[] }).items),
    enabled: !!runId && !!comparison,
  })
  const {
    data: volcanoBlob,
    isError: volcanoArtifactError,
  } = useQuery({
    queryKey: ['phase3-deg-artifact', runId, species, comparison, 'volcano.png'],
    queryFn: () => phase3Api.degArtifact(runId!, species, 'volcano.png', comparison)
      .then((response) => response.data as Blob),
    enabled: !!runId && !!comparison && artifactNames.includes('volcano.png'),
  })
  const {
    data: maBlob,
    isError: maArtifactError,
  } = useQuery({
    queryKey: ['phase3-deg-artifact', runId, species, comparison, 'ma_plot.png'],
    queryFn: () => phase3Api.degArtifact(runId!, species, 'ma_plot.png', comparison)
      .then((response) => response.data as Blob),
    enabled: !!runId && !!comparison && artifactNames.includes('ma_plot.png'),
  })
  const volcanoUrl = useObjectUrl(volcanoBlob)
  const maUrl = useObjectUrl(maBlob)
  const [artifactDownloadError, setArtifactDownloadError] = useState('')
  const [downloadingArtifact, setDownloadingArtifact] = useState('')
  const downloadArtifact = async (artifactName: string) => {
    setArtifactDownloadError('')
    setDownloadingArtifact(artifactName)
    try {
      const response = await phase3Api.degArtifact(runId!, species, artifactName, comparison)
      const url = URL.createObjectURL(response.data as Blob)
      const anchor = document.createElement('a')
      anchor.href = url
      anchor.download = artifactName
      anchor.click()
      window.setTimeout(() => URL.revokeObjectURL(url), 1000)
    } catch {
      setArtifactDownloadError(`Could not download ${artifactName}. Please try again.`)
    } finally {
      setDownloadingArtifact('')
    }
  }
  const [search, setSearch] = useState('')
  const [filter, setFilter] = useState('all')
  const [sort, setSort] = useState('fdr')
  const [page, setPage] = useState(0)
  const rows = useMemo(() => genes.filter((gene) => {
    const text = `${gene.ensembl_id} ${gene.gene_symbol ?? ''}`.toLowerCase()
    if (search && !text.includes(search.toLowerCase())) return false
    if (filter === 'significant') return gene.significant
    if (filter === 'up') return gene.significant && gene.direction === 'up'
    if (filter === 'down') return gene.significant && gene.direction === 'down'
    return true
  }).sort((a, b) => {
    if (sort === 'lfc') return Math.abs(b.log2fc ?? 0) - Math.abs(a.log2fc ?? 0)
    if (sort === 'symbol') return (a.gene_symbol ?? a.ensembl_id).localeCompare(b.gene_symbol ?? b.ensembl_id)
    if (sort === 'statistic') return Math.abs(b.statistic ?? -Infinity) - Math.abs(a.statistic ?? -Infinity)
    if (sort === 'base_mean') return (b.base_mean ?? b.average_expression ?? -Infinity) - (a.base_mean ?? a.average_expression ?? -Infinity)
    return (a.adjusted_p_value ?? Infinity) - (b.adjusted_p_value ?? Infinity)
  }), [filter, genes, search, sort])
  const selectedComparison = available.find((item) => item.comparison === comparison)
  const degSummary = asRecord(asRecord(runSummary?.phase3).deg)
  const methodSummary = asRecord(degSummary[species === 'mouse' ? 'mouse_cross_study_exploratory' : species])
  const conditionSummary = methodSummary
  const fdrMethod = methodSummary.fdr_method
  const alpha = methodSummary.alpha
  const lfcThreshold = methodSummary.lfc_threshold
  const caseSamples = methodSummary.case_sample_count ?? methodSummary.case_samples
  const controlSamples = methodSummary.control_sample_count ?? methodSummary.control_samples
  const up = methodSummary.upregulated_genes ?? genes.filter((gene) => gene.significant && gene.direction === 'up').length
  const down = methodSummary.downregulated_genes ?? genes.filter((gene) => gene.significant && gene.direction === 'down').length
  const volcanoGroups = ['up', 'down', 'other'].map((direction) => {
    const selected = genes.filter((gene) => {
      const group = gene.significant ? gene.direction : 'other'
      return group === direction && gene.log2fc != null && gene.adjusted_p_value != null
    })
    return {
      type: 'scatter' as const, mode: 'markers' as const,
      name: direction === 'other' ? 'Not significant' : direction === 'up' ? 'Significant up' : 'Significant down',
      x: selected.map((gene) => gene.log2fc as number),
      y: selected.map((gene) => -Math.log10(Math.max(gene.adjusted_p_value as number, 1e-300))),
      text: selected.map((gene) => gene.gene_symbol || gene.ensembl_id),
      hovertemplate: '%{text}<br>log2FC %{x:.3f}<br>-log10(FDR) %{y:.3f}<extra>%{fullData.name}</extra>',
      marker: { size: 6, opacity: direction === 'other' ? 0.45 : 0.8, color: direction === 'up' ? '#c64a3b' : direction === 'down' ? '#2675a8' : '#a8b2bc' },
    }
  })
  const maGenes = genes.filter((gene) => (gene.base_mean ?? gene.average_expression) != null && gene.log2fc != null)
  return (
    <Box>
      <RunHeader runId={runId ?? ''} view="differential-expression" title="Differential Expression" subtitle="Species-specific differential expression analysis" />
      {runId && <>
        {summaryError && <Alert severity="error" sx={{ mb: 2 }}>Could not load the run analysis summary.</Alert>}
        {summaryLoading && <LinearProgress sx={{ mb: 2 }} />}
        <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1.5} sx={{ mb: 2 }}>
          <FormControl size="small" sx={{ minWidth: 160 }}>
            <InputLabel>Species</InputLabel>
            <Select label="Species" value={species} onChange={(event) => { setSpecies(event.target.value as Species); setPage(0) }}>
              <MenuItem value="human">Human</MenuItem>
              <MenuItem value="mouse">Mouse</MenuItem>
            </Select>
          </FormControl>
          <TextField select size="small" label="Comparison" value={comparison} onChange={(event) => { setComparison(event.target.value); setPage(0) }} sx={{ minWidth: 320 }}>
            {available.map((item) => <MenuItem key={item.comparison} value={item.comparison}>{item.comparison}</MenuItem>)}
          </TextField>
        </Stack>
        {!summaryLoading && !summaryError && !available.length && species === 'mouse' && (
          <Alert severity="info" sx={{ mb: 2 }}>
            Mouse differential-expression results are not available for this run because no valid cancer-versus-control comparison was detected.
          </Alert>
        )}
        {!summaryLoading && !summaryError && !available.length && species === 'human' && (
          <Alert severity="info" sx={{ mb: 2 }}>No differential-expression results are available for this run.</Alert>
        )}
        {(summaryLoading || summaryError || !!available.length) && <ResultState loading={summaryLoading || isLoading} error={summaryError || isError} empty={false}>
          {!!selectedComparison && <>
            <Grid container spacing={1.5} sx={{ mb: 2 }}>
              <Grid item xs={6} md={3}><StatCard label="Genes tested" value={selectedComparison.tested_genes} /></Grid>
              <Grid item xs={6} md={3}><StatCard label="Significant DEGs" value={selectedComparison.significant_genes} /></Grid>
              <Grid item xs={6} md={3}><StatCard label="Upregulated" value={up} /></Grid>
              <Grid item xs={6} md={3}><StatCard label="Downregulated" value={down} /></Grid>
            </Grid>
            <Paper variant="outlined" sx={{ p: 2, mb: 2 }}>
              <Typography variant="subtitle1" fontWeight={700} sx={{ mb: 1 }}>Comparison details</Typography>
              <Grid container spacing={1}>
                {[
                  ['Case condition', conditionSummary.case_condition],
                  ['Control condition', conditionSummary.control_condition],
                  ['Method', conditionSummary.method ?? genes[0]?.method],
                  ['Multiple-testing method', fdrMethod],
                  ['FDR threshold', alpha],
                  ['Log2FC threshold', lfcThreshold],
                  ['Case samples', caseSamples],
                  ['Control samples', controlSamples],
                  ['Sample count', typeof caseSamples === 'number' && typeof controlSamples === 'number' ? caseSamples + controlSamples : null],
                ].map(([label, value]) => <Grid item xs={6} md={3} key={String(label)}>
                  <Typography variant="caption" color="text.secondary">{String(label)}</Typography>
                  <Typography variant="body2" fontWeight={700}>{display(value)}</Typography>
                </Grid>)}
              </Grid>
            </Paper>
            <Paper variant="outlined" sx={{ p: 2, mb: 2 }}>
              <Stack direction={{ xs: 'column', sm: 'row' }} justifyContent="space-between" spacing={1}>
                <Box>
                  <Typography variant="subtitle1" fontWeight={700}>Saved run artifacts</Typography>
                  <Typography variant="body2" color="text.secondary">
                    Original figures, complete gene tables, and analysis metadata from this run.
                  </Typography>
                </Box>
                {artifactsLoading && <CircularProgress size={22} />}
              </Stack>
              {artifactsError && <Alert severity="error" sx={{ mt: 1 }}>Could not load the saved DEG artifacts for this comparison.</Alert>}
              {(volcanoArtifactError || maArtifactError) && <Alert severity="error" sx={{ mt: 1 }}>A saved DEG figure could not be loaded. Use the interactive plot below or try again.</Alert>}
              {artifactDownloadError && <Alert severity="error" sx={{ mt: 1 }}>{artifactDownloadError}</Alert>}
              {!!artifactNames.length && (
                <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap" sx={{ mt: 1.5 }}>
                  {artifactNames.map((artifactName) => (
                    <Button
                      key={artifactName}
                      size="small"
                      variant="outlined"
                      disabled={!!downloadingArtifact}
                      onClick={() => void downloadArtifact(artifactName)}
                    >
                      {downloadingArtifact === artifactName ? 'Downloading…' : `Download ${artifactName}`}
                    </Button>
                  ))}
                </Stack>
              )}
              {!artifactsLoading && !artifactsError && !artifactNames.length && (
                <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
                  This run has no separately saved artifact files; results below are loaded from the run API.
                </Typography>
              )}
            </Paper>
            {comparison.includes('cross_study_exploratory') && <Alert severity="warning" sx={{ mb: 2 }}>Exploratory cross-study mouse analysis: assay, processing, study, and condition are confounded. Do not interpret as confirmatory cancer-versus-healthy evidence.</Alert>}
            {!genes.length && !isLoading && <Alert severity="info" sx={{ mb: 2 }}>No differential-expression results are available for this run.</Alert>}
            <Grid container spacing={2} sx={{ mb: 2 }}>
              <Grid item xs={12} lg={6}>
                <Paper variant="outlined" sx={{ p: 1 }}>
                  <Typography variant="subtitle1" fontWeight={700} sx={{ px: 1 }}>Volcano plot</Typography>
                  {volcanoUrl
                    ? <Box component="img" src={volcanoUrl} alt={`${species} ${comparison} volcano plot`} sx={{ display: 'block', width: '100%', height: 390, objectFit: 'contain' }} />
                    : <Plot data={volcanoGroups} layout={{ autosize: true, height: 390, margin: { l: 55, r: 20, t: 15, b: 50 }, xaxis: { title: 'log2 fold change' }, yaxis: { title: '-log10 adjusted p-value' }, legend: { orientation: 'h' } }} useResizeHandler style={{ width: '100%' }} />}
                </Paper>
              </Grid>
              <Grid item xs={12} lg={6}>
                <Paper variant="outlined" sx={{ p: 1 }}>
                  <Typography variant="subtitle1" fontWeight={700} sx={{ px: 1 }}>MA plot</Typography>
                  {maUrl
                    ? <Box component="img" src={maUrl} alt={`${species} ${comparison} MA plot`} sx={{ display: 'block', width: '100%', height: 390, objectFit: 'contain' }} />
                    : maGenes.length
                      ? <Plot data={[{ type: 'scatter', mode: 'markers', x: maGenes.map((gene) => gene.base_mean ?? gene.average_expression as number), y: maGenes.map((gene) => gene.log2fc as number), text: maGenes.map((gene) => gene.gene_symbol || gene.ensembl_id), hovertemplate: '%{text}<br>mean expression %{x:.3f}<br>log2FC %{y:.3f}<extra></extra>', marker: { color: maGenes.map((gene) => gene.significant ? (gene.direction === 'up' ? '#c64a3b' : '#2675a8') : '#a8b2bc'), size: 5, opacity: 0.65 } }]} layout={{ autosize: true, height: 390, margin: { l: 55, r: 20, t: 15, b: 50 }, xaxis: { title: 'Mean/base expression' }, yaxis: { title: 'log2 fold change' }, showlegend: false }} useResizeHandler style={{ width: '100%' }} />
                      : <Alert severity="info">No mean/base expression values or saved MA plot are available for this comparison.</Alert>}
                </Paper>
              </Grid>
            </Grid>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
              Comparison {comparison} · {genes[0]?.method ?? 'Method not returned'} · {genes.length.toLocaleString()} gene rows loaded from the run API
            </Typography>
            <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1} sx={{ mb: 1 }}>
              <TextField size="small" label="Search gene" value={search} onChange={(event) => { setSearch(event.target.value); setPage(0) }} />
              <TextField select size="small" label="Filter" value={filter} onChange={(event) => { setFilter(event.target.value); setPage(0) }} sx={{ minWidth: 180 }}>
                <MenuItem value="all">All genes</MenuItem><MenuItem value="significant">Significant</MenuItem><MenuItem value="up">Significant up</MenuItem><MenuItem value="down">Significant down</MenuItem>
              </TextField>
              <TextField select size="small" label="Sort by" value={sort} onChange={(event) => { setSort(event.target.value); setPage(0) }} sx={{ minWidth: 190 }}>
                <MenuItem value="fdr">Adjusted p-value</MenuItem><MenuItem value="lfc">Absolute log2FC</MenuItem><MenuItem value="symbol">Gene symbol / ID</MenuItem><MenuItem value="statistic">Statistic</MenuItem><MenuItem value="base_mean">Base mean / expression</MenuItem>
              </TextField>
            </Stack>
            <TableContainer component={Paper} variant="outlined"><Table size="small"><TableHead><TableRow>{['Gene ID', 'Gene symbol', 'log2FC', 'p-value', 'adjusted p-value', 'Statistic', 'Base mean / expression', 'Direction', 'Significant', 'Method', 'Explore'].map((label) => <TableCell key={label} title={label === 'log2FC' ? 'Magnitude and direction of expression change between the case and control groups.' : label === 'adjusted p-value' ? 'False-discovery-rate corrected significance value.' : undefined}>{label}</TableCell>)}</TableRow></TableHead><TableBody>
              {rows.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE).map((gene) => {
                const network = runNetworks.find((item) => item.species === species)
                const testable = gene.testable ?? (
                  gene.pvalue != null && gene.adjusted_p_value != null && gene.statistic != null
                )
                const statisticValue = !testable ? 'Not testable' : display(gene.statistic)
                const pvalueValue = !testable ? 'Not testable' : display(gene.pvalue)
                const adjustedPValue = !testable ? 'Not testable' : display(gene.adjusted_p_value)
                const normalizedDirection = gene.direction?.toLowerCase()
                const direction = !testable
                  ? 'Not testable'
                  : normalizedDirection === 'up'
                  ? 'Upregulated'
                  : normalizedDirection === 'down'
                    ? 'Downregulated'
                    : normalizedDirection === 'not_significant'
                      ? 'Not significant'
                      : normalizedDirection === 'not_testable'
                        ? 'Not testable'
                        : gene.significant && gene.log2fc != null
                          ? gene.log2fc > 0 ? 'Upregulated' : gene.log2fc < 0 ? 'Downregulated' : 'Not significant'
                          : 'Not significant'
                const significance = !testable ? 'Not testable' : gene.significant ? 'Yes' : 'No'
                const untestableTitle = !testable
                  ? 'The saved result has no test statistic and p-values for this gene; it cannot be called significant or not significant.'
                  : undefined
                return <TableRow key={gene.gene_id} hover><TableCell>{gene.ensembl_id}</TableCell><TableCell>{gene.gene_symbol ?? 'Not provided'}</TableCell><TableCell>{display(gene.log2fc)}</TableCell><TableCell title={untestableTitle}>{pvalueValue}</TableCell><TableCell title={untestableTitle}>{adjustedPValue}</TableCell><TableCell title={untestableTitle}>{statisticValue}</TableCell><TableCell>{display(gene.base_mean ?? gene.average_expression)}</TableCell><TableCell>{direction}</TableCell><TableCell>{significance}</TableCell><TableCell>{gene.method}</TableCell><TableCell>{network && <Button size="small" onClick={() => navigate(`/runs/${runId}/network-explorer?network=${network.network_id}&gene=${encodeURIComponent(gene.ensembl_id)}`)}>Network</Button>}</TableCell></TableRow>
              })}
              {!rows.length && <TableRow><TableCell colSpan={11}>No genes match these filters.</TableCell></TableRow>}
            </TableBody></Table></TableContainer>
            <TablePagination component="div" count={rows.length} page={page} onPageChange={(_, next) => setPage(next)} rowsPerPage={PAGE_SIZE} onRowsPerPageChange={() => undefined} rowsPerPageOptions={[PAGE_SIZE]} />
          </>}
        </ResultState>}
      </>}
    </Box>
  )
}

export default DifferentialExpressionPage
