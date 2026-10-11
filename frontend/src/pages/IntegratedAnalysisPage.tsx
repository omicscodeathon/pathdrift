import { useState } from 'react'
import { Alert, Box, Grid, LinearProgress, MenuItem, Paper, Table, TableBody, TableCell, TableContainer, TableHead, TablePagination, TableRow, TextField, Typography } from '@mui/material'
import { useQuery } from '@tanstack/react-query'
import { phase3Api } from '@/api/client'
import { display, PAGE_SIZE, RunHeader, useRunId, type DEG, type IntegratedGene, type Page, type Species } from './analysis/shared'

export function IntegratedAnalysisPage() {
  const runId = useRunId()
  const [resultsType, setResultsType] = useState<'deg' | 'integrated'>('deg')
  const [species, setSpecies] = useState<Species>('human')
  const [degSet, setDegSet] = useState<'all' | 'significant'>('all')
  const [degPage, setDegPage] = useState(0)
  const [integratedPage, setIntegratedPage] = useState(0)
  const degQuery = useQuery({
    queryKey: ['integrated-analysis-deg-table', runId, species, degSet, degPage],
    queryFn: async () => {
      const response = await phase3Api.deg(runId!, {
        species,
        significant: species === 'human' && degSet === 'significant',
        limit: PAGE_SIZE,
        offset: degPage * PAGE_SIZE,
      })
      return response.data as Page<DEG>
    },
    enabled: !!runId && resultsType === 'deg' && species === 'human',
  })
  const [mouseTable, setMouseTable] = useState('all_genes.csv')
  const mouseTableQuery = useQuery({
    queryKey: ['integrated-analysis-mouse-deg-table', runId, mouseTable, degPage],
    queryFn: async () => {
      const response = await phase3Api.degTable(runId!, 'mouse', mouseTable, {
        comparison: 'cancer_vs_healthy_cross_study_exploratory',
        limit: PAGE_SIZE,
        offset: degPage * PAGE_SIZE,
      })
      return response.data as Page<Record<string, string | null>>
    },
    enabled: !!runId && resultsType === 'deg' && species === 'mouse',
  })
  const integratedQuery = useQuery({
    queryKey: ['integrated-analysis-results-table', runId, species, integratedPage],
    queryFn: async () => {
      const response = await phase3Api.integrated(runId!, {
        species,
        limit: PAGE_SIZE,
        offset: integratedPage * PAGE_SIZE,
      })
      return response.data as Page<IntegratedGene>
    },
    enabled: !!runId && resultsType === 'integrated',
  })
  return <Box>
    <RunHeader runId={runId ?? ''} view="integrated-analysis" title="Integrated Analysis" subtitle="View saved DEG and integrated gene results for this run" />
    {runId && <>
      <Paper variant="outlined" sx={{ p: 2, mb: 2 }}>
        <Typography variant="h6" fontWeight={700} sx={{ mb: 1.5 }}>Saved analysis results</Typography>
        <Grid container spacing={1.5} sx={{ mb: 1.5 }}>
          <Grid item xs={12} sm={6} md={3}>
            <TextField select fullWidth size="small" label="Results type" value={resultsType} onChange={(event) => { setResultsType(event.target.value as 'deg' | 'integrated'); setDegPage(0); setIntegratedPage(0) }}>
              <MenuItem value="deg">DEG results</MenuItem>
              <MenuItem value="integrated">Integrated analysis</MenuItem>
            </TextField>
          </Grid>
          <Grid item xs={12} sm={6} md={3}>
            <TextField select fullWidth size="small" label="Species" value={species} onChange={(event) => { setSpecies(event.target.value as Species); setDegSet('all'); setDegPage(0); setIntegratedPage(0) }}>
              <MenuItem value="human">Human</MenuItem>
              <MenuItem value="mouse">Mouse</MenuItem>
            </TextField>
          </Grid>
          {resultsType === 'deg' && <Grid item xs={12} sm={6} md={3}>
            {species === 'human'
              ? <TextField select fullWidth size="small" label="DEG result set" value={degSet} onChange={(event) => { setDegSet(event.target.value as 'all' | 'significant'); setDegPage(0) }}>
                  <MenuItem value="all">All genes</MenuItem>
                  <MenuItem value="significant">Significant genes</MenuItem>
                </TextField>
              : <TextField select fullWidth size="small" label="Mouse result table" value={mouseTable} onChange={(event) => { setMouseTable(event.target.value); setDegPage(0) }}>
                  <MenuItem value="all_genes.csv">All genes</MenuItem>
                  <MenuItem value="significant_genes.csv">Significant genes</MenuItem>
                  <MenuItem value="gene_mapping.csv">Gene mapping</MenuItem>
                  <MenuItem value="sample_metadata.csv">Sample metadata</MenuItem>
                </TextField>}
          </Grid>}
        </Grid>
        {resultsType === 'deg' && species === 'mouse' && <Alert severity="warning" sx={{ mb: 1.5 }}>
          No primary mouse DEG table was generated for this run because GSE155577 has no control samples. The available table is deg/mouse/cross_study_exploratory/all_genes.csv (GSE155577 tumors versus GSE116385 normal mammary samples); it is exploratory, not confirmatory.
        </Alert>}
        {resultsType === 'deg' && species === 'human' && degQuery.isLoading && <LinearProgress sx={{ mb: 1.5 }} />}
        {resultsType === 'deg' && species === 'human' && degQuery.isError && <Alert severity="error" sx={{ mb: 1.5 }}>Could not load the saved {species} DEG table for this run.</Alert>}
        {resultsType === 'deg' && species === 'mouse' && mouseTableQuery.isLoading && <LinearProgress sx={{ mb: 1.5 }} />}
        {resultsType === 'deg' && species === 'mouse' && mouseTableQuery.isError && <Alert severity="error" sx={{ mb: 1.5 }}>Could not load the saved mouse {mouseTable} table for this run.</Alert>}
        {resultsType === 'deg' && species === 'human' && degQuery.data && <>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
            {`deg/human/${degSet === 'significant' ? 'significant_genes.csv' : 'all_genes.csv'}`}
            {' · '}{degQuery.data.total.toLocaleString()} genes
          </Typography>
          <TableContainer component={Paper} variant="outlined">
            <Table size="small">
              <TableHead><TableRow>{['Gene ID', 'Symbol', 'log2FC', 'p-value', 'Adjusted p-value', 'Statistic', 'Mean expression', 'Direction', 'Significant', 'Method'].map((label) => <TableCell key={label}>{label}</TableCell>)}</TableRow></TableHead>
              <TableBody>
                {degQuery.data.items.map((gene) => {
                  const testable = gene.testable ?? (gene.pvalue != null && gene.adjusted_p_value != null && gene.statistic != null)
                  return <TableRow key={gene.gene_id} hover>
                    <TableCell>{gene.ensembl_id}</TableCell>
                    <TableCell>{gene.gene_symbol ?? '—'}</TableCell>
                    <TableCell>{display(gene.log2fc)}</TableCell>
                    <TableCell>{testable ? display(gene.pvalue) : 'Not testable'}</TableCell>
                    <TableCell>{testable ? display(gene.adjusted_p_value) : 'Not testable'}</TableCell>
                    <TableCell>{testable ? display(gene.statistic) : 'Not testable'}</TableCell>
                    <TableCell>{display(gene.base_mean ?? gene.average_expression)}</TableCell>
                    <TableCell>{testable ? display(gene.direction) : 'Not testable'}</TableCell>
                    <TableCell>{testable ? gene.significant ? 'Yes' : 'No' : 'Not testable'}</TableCell>
                    <TableCell>{gene.method}</TableCell>
                  </TableRow>
                })}
                {!degQuery.data.items.length && <TableRow><TableCell colSpan={10}>No saved genes are available for this table.</TableCell></TableRow>}
              </TableBody>
            </Table>
          </TableContainer>
          <TablePagination component="div" count={degQuery.data.total} page={degPage} onPageChange={(_, next) => setDegPage(next)} rowsPerPage={PAGE_SIZE} onRowsPerPageChange={() => undefined} rowsPerPageOptions={[PAGE_SIZE]} />
        </>}
        {resultsType === 'deg' && species === 'mouse' && mouseTableQuery.data && <>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
            {`deg/mouse/cross_study_exploratory/${mouseTable}`}
            {' · '}{mouseTableQuery.data.total.toLocaleString()} rows
          </Typography>
          <TableContainer component={Paper} variant="outlined">
            <Table size="small">
              <TableHead><TableRow>{Object.keys(mouseTableQuery.data.items[0] ?? {}).map((column) => <TableCell key={column} sx={{ whiteSpace: 'nowrap' }}>{column}</TableCell>)}</TableRow></TableHead>
              <TableBody>
                {mouseTableQuery.data.items.map((row, index) => <TableRow key={`${String(row.gene_id ?? row.sample_id ?? index)}-${index}`} hover>
                  {Object.entries(row).map(([column, value]) => <TableCell key={column} sx={{ whiteSpace: 'nowrap' }}>{value || '—'}</TableCell>)}
                </TableRow>)}
                {!mouseTableQuery.data.items.length && <TableRow><TableCell colSpan={1}>No saved rows are available for this table.</TableCell></TableRow>}
              </TableBody>
            </Table>
          </TableContainer>
          <TablePagination component="div" count={mouseTableQuery.data.total} page={degPage} onPageChange={(_, next) => setDegPage(next)} rowsPerPage={PAGE_SIZE} onRowsPerPageChange={() => undefined} rowsPerPageOptions={[PAGE_SIZE]} />
        </>}
        {resultsType === 'integrated' && integratedQuery.isLoading && <LinearProgress sx={{ mb: 1.5 }} />}
        {resultsType === 'integrated' && integratedQuery.isError && <Alert severity="error" sx={{ mb: 1.5 }}>Could not load the saved {species} integrated analysis for this run.</Alert>}
        {resultsType === 'integrated' && integratedQuery.data && <>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
            {`integrated/${species}_gene_integration.csv`}
            {' · '}{integratedQuery.data.total.toLocaleString()} genes
          </Typography>
          <TableContainer component={Paper} variant="outlined">
            <Table size="small">
              <TableHead><TableRow>{['Gene ID', 'Symbol', 'log2FC', 'p-value', 'Adjusted p-value', 'Significant', 'Direction', 'Degree', 'Weighted degree', 'Betweenness', 'Closeness', 'Eigenvector', 'Module'].map((label) => <TableCell key={label}>{label}</TableCell>)}</TableRow></TableHead>
              <TableBody>
                {integratedQuery.data.items.map((gene) => <TableRow key={gene.gene_id} hover>
                  <TableCell>{gene.ensembl_id}</TableCell>
                  <TableCell>{gene.gene_symbol ?? '—'}</TableCell>
                  <TableCell>{display(gene.log2fc)}</TableCell>
                  <TableCell>{display(gene.pvalue)}</TableCell>
                  <TableCell>{display(gene.adjusted_p_value)}</TableCell>
                  <TableCell>{gene.significant ? 'Yes' : 'No'}</TableCell>
                  <TableCell>{display(gene.direction)}</TableCell>
                  <TableCell>{display(gene.degree)}</TableCell>
                  <TableCell>{display(gene.weighted_degree)}</TableCell>
                  <TableCell>{display(gene.betweenness_centrality)}</TableCell>
                  <TableCell>{display(gene.closeness_centrality)}</TableCell>
                  <TableCell>{display(gene.eigenvector_centrality)}</TableCell>
                  <TableCell>{gene.module_id ?? 'Not assigned'}</TableCell>
                </TableRow>)}
                {!integratedQuery.data.items.length && <TableRow><TableCell colSpan={13}>No integrated results are available for this species in the selected run.</TableCell></TableRow>}
              </TableBody>
            </Table>
          </TableContainer>
          <TablePagination component="div" count={integratedQuery.data.total} page={integratedPage} onPageChange={(_, next) => setIntegratedPage(next)} rowsPerPage={PAGE_SIZE} onRowsPerPageChange={() => undefined} rowsPerPageOptions={[PAGE_SIZE]} />
        </>}
      </Paper>
    </>}
  </Box>
}

export default IntegratedAnalysisPage
