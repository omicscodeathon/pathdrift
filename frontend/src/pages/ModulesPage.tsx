import { useMemo, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { Alert, Box, Grid, MenuItem, Paper, Stack, Table, TableBody, TableCell, TableContainer, TableHead, TablePagination, TableRow, TextField, Typography } from '@mui/material'
import { display, MODULE_LIMIT, numberValue, PAGE_SIZE, ResultState, RunHeader, StatCard, summaryValue, useAllModules, useRunId, type Module } from './analysis/shared'

function ModuleTable({ modules, runId, networkFilter = '' }: { modules: Module[]; runId: string; networkFilter?: string }) {
  const navigate = useNavigate()
  const [search, setSearch] = useState('')
  const [species, setSpecies] = useState('all')
  const [degOnly, setDegOnly] = useState(false)
  const [sort, setSort] = useState('network')
  const [page, setPage] = useState(0)
  const filtered = modules.filter((module) =>
    (!networkFilter || module.network_id === networkFilter)
    && (species === 'all' || module.species === species)
    && (!degOnly || (numberValue(summaryValue(module.statistics, 'deg_gene_count')) ?? 0) > 0)
    && `${module.module_key} ${module.network_name} ${module.species}`.toLowerCase().includes(search.toLowerCase()),
  ).sort((a, b) => {
    if (sort === 'size') return b.size - a.size
    if (sort === 'deg') return (numberValue(summaryValue(b.statistics, 'deg_gene_count')) ?? -1) - (numberValue(summaryValue(a.statistics, 'deg_gene_count')) ?? -1)
    return a.network_name.localeCompare(b.network_name) || a.module_key.localeCompare(b.module_key)
  })
  return <>
    <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1} sx={{ mb: 1.5 }}>
      <TextField size="small" label="Search modules" value={search} onChange={(event) => { setSearch(event.target.value); setPage(0) }} />
      <TextField select size="small" label="Species" value={species} onChange={(event) => { setSpecies(event.target.value); setPage(0) }} sx={{ minWidth: 150 }}><MenuItem value="all">All</MenuItem><MenuItem value="human">Human</MenuItem><MenuItem value="mouse">Mouse</MenuItem></TextField>
      <TextField select size="small" label="Modules with DEGs" value={degOnly ? 'yes' : 'all'} onChange={(event) => { setDegOnly(event.target.value === 'yes'); setPage(0) }} sx={{ minWidth: 180 }}><MenuItem value="all">All modules</MenuItem><MenuItem value="yes">DEG-containing only</MenuItem></TextField>
      <TextField select size="small" label="Sort by" value={sort} onChange={(event) => { setSort(event.target.value); setPage(0) }} sx={{ minWidth: 170 }}><MenuItem value="network">Network / module</MenuItem><MenuItem value="size">Module size</MenuItem><MenuItem value="deg">DEG count</MenuItem></TextField>
    </Stack>
    <TableContainer component={Paper} variant="outlined"><Table size="small"><TableHead><TableRow>{['Module', 'Network', 'Species', 'Size', 'DEGs*', 'Up*', 'Down*', 'Detection', 'Density', 'Average internal weight'].map((text) => <TableCell key={text}>{text}</TableCell>)}</TableRow></TableHead><TableBody>
      {filtered.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE).map((module) => <TableRow key={module.module_id} hover sx={{ cursor: 'pointer' }} onClick={() => navigate(`/runs/${runId}/module-explorer?module=${module.module_id}`)}>
        <TableCell>{module.module_key}</TableCell><TableCell>{module.network_name}</TableCell><TableCell>{module.species}</TableCell><TableCell>{module.size.toLocaleString()}</TableCell><TableCell>{display(summaryValue(module.statistics, 'deg_gene_count'))}</TableCell><TableCell>{display(summaryValue(module.statistics, 'upregulated_deg_count'))}</TableCell><TableCell>{display(summaryValue(module.statistics, 'downregulated_deg_count'))}</TableCell><TableCell>{module.detection_method}</TableCell><TableCell>{display(summaryValue(module.statistics, 'density'))}</TableCell><TableCell>{display(summaryValue(module.statistics, 'average_internal_edge_weight', 'avg_internal_edge_weight'))}</TableCell>
      </TableRow>)}
      {!filtered.length && <TableRow><TableCell colSpan={10}>No modules match this selection.</TableCell></TableRow>}
    </TableBody></Table></TableContainer>
    <TablePagination component="div" count={filtered.length} page={page} onPageChange={(_, next) => setPage(next)} rowsPerPage={PAGE_SIZE} onRowsPerPageChange={() => undefined} rowsPerPageOptions={[PAGE_SIZE]} />
  </>
}

export function ModulesPage() {
  const runId = useRunId()
  const [searchParams] = useSearchParams()
  const { data, isLoading, isError } = useAllModules(runId)
  const modules = data?.items ?? []
  const perSpecies = useMemo(() => ({ human: modules.filter((module) => module.species === 'human').length, mouse: modules.filter((module) => module.species === 'mouse').length }), [modules])
  return <Box>
    <RunHeader runId={runId ?? ''} view="modules" title="Network Modules" subtitle="Real network communities detected and persisted for this analysis run" />
    {runId && <ResultState loading={isLoading} error={isError} empty={!data?.total}>
      {data && data.total > modules.length && <Alert severity="info" sx={{ mb: 2 }}>The API returned {modules.length} of {data.total} modules; the table is limited to the backend page size.</Alert>}
      {modules.some((module) => module.species === 'mouse') && <Alert severity="warning" sx={{ mb: 2 }}>
        * Mouse DEG, Up, and Down counts are exploratory cross-study results comparing GSE155577 tumor samples with GSE116385 normal mammary samples. Only module genes present in that DEG comparison are counted. Because condition is confounded with study and processing, these counts are not confirmatory. Cancer and healthy networks are clustered independently, so their Louvain module counts can differ. The three mouse cancer modules contain 999 genes; the remaining network node, Nr1d1, has no edges and is excluded by the configured minimum module size.
      </Alert>}
      <Grid container spacing={1.5} sx={{ mb: 2 }}><Grid item xs={6} md={3}><StatCard label="Modules returned" value={data?.total} /></Grid><Grid item xs={6} md={3}><StatCard label="Human modules" value={perSpecies.human} /></Grid><Grid item xs={6} md={3}><StatCard label="Mouse modules" value={perSpecies.mouse} /></Grid><Grid item xs={6} md={3}><StatCard label="Genes across returned modules" value={modules.reduce((sum, module) => sum + module.size, 0)} /></Grid></Grid>
      <ModuleTable modules={modules} runId={runId} networkFilter={searchParams.get('network') ?? ''} />
    </ResultState>}
  </Box>
}

export default ModulesPage
