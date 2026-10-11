import { useState } from 'react'
import { Link as RouterLink } from 'react-router-dom'
import { Alert, Box, Button, Grid, LinearProgress, MenuItem, Paper, Stack, Table, TableBody, TableCell, TableContainer, TableHead, TablePagination, TableRow, TextField, Typography } from '@mui/material'
import CytoscapeComponent from 'react-cytoscapejs'
import { useQuery } from '@tanstack/react-query'
import { phase3Api } from '@/api/client'
import { CY_STYLE, display, fetchAllDeg, NETWORK_EDGE_LIMIT, PAGE_SIZE, ResultState, RunHeader, StatCard, summaryValue, useSelectedModule, useSpeciesComparisons, useRunId, type Edge, type NetworkNode, type Page } from './analysis/shared'

export function ModuleExplorerPage() {
  const runId = useRunId()
  const module = useSelectedModule(runId)
  const moduleSpecies = module.detail.data?.species
  const { comparisons } = useSpeciesComparisons(runId)
  const comparison = moduleSpecies === 'mouse'
    ? 'cancer_vs_healthy_cross_study_exploratory'
    : comparisons.find((item) => item.species === moduleSpecies)?.comparison
  const { data: degGenes = [] } = useQuery({
    queryKey: ['phase3-module-deg', runId, moduleSpecies, comparison],
    queryFn: () => fetchAllDeg(runId!, moduleSpecies!, comparison),
    enabled: !!runId && !!moduleSpecies && !!comparison,
  })
  const { data: moduleNetworkNodes } = useQuery({
    queryKey: ['phase3-module-network-nodes', runId, module.detail.data?.network_id],
    queryFn: () => phase3Api.nodes(runId!, module.detail.data!.network_id, 500, 0).then((response) => response.data as Page<NetworkNode>),
    enabled: !!runId && !!module.detail.data?.network_id,
  })
  const { data: moduleNetworkEdges } = useQuery({
    queryKey: ['phase3-module-network-edges', runId, module.detail.data?.network_id],
    queryFn: () => phase3Api.edges(runId!, module.detail.data!.network_id, NETWORK_EDGE_LIMIT, 0).then((response) => response.data as Page<Edge>),
    enabled: !!runId && !!module.detail.data?.network_id,
  })
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(0)
  const [geneFilter, setGeneFilter] = useState('all')
  const [geneSort, setGeneSort] = useState('centrality')
  const allGenes = module.genes.data?.items ?? []
  const networkNodeMap = new Map<string, NetworkNode>()
  for (const node of moduleNetworkNodes?.items ?? []) {
    networkNodeMap.set(node.gene_id, node)
    networkNodeMap.set(node.ensembl_id, node)
  }
  const degMap = new Map<string, (typeof degGenes)[number]>()
  for (const gene of degGenes) {
    degMap.set(gene.ensembl_id, gene)
    degMap.set(gene.gene_id, gene)
  }
  const rows = allGenes.map((gene) => {
    const geneIdentifier = gene.ensembl_id || gene.gene_id
    const node = networkNodeMap.get(gene.gene_id)
      ?? networkNodeMap.get(geneIdentifier)
      ?? (gene.degree == null ? undefined : {
        gene_id: gene.gene_id,
        ensembl_id: geneIdentifier,
        gene_symbol: gene.gene_symbol,
        degree: gene.degree,
        weighted_degree: gene.weighted_degree ?? null,
        betweenness_centrality: gene.betweenness_centrality ?? null,
        closeness_centrality: gene.closeness_centrality ?? null,
        eigenvector_centrality: gene.eigenvector_centrality ?? null,
        module_id: module.detail.data?.module_id ?? null,
      })
    return {
      gene,
      geneIdentifier,
      geneSymbol: gene.gene_symbol || node?.gene_symbol,
      node,
      deg: degMap.get(geneIdentifier) ?? degMap.get(gene.gene_id),
    }
  })
    .filter(({ geneIdentifier, geneSymbol, deg }) => `${geneIdentifier} ${geneSymbol ?? ''}`.toLowerCase().includes(search.toLowerCase())
      && (geneFilter === 'all' || (geneFilter === 'significant' && deg?.significant) || (geneFilter === 'up' && deg?.significant && deg.direction === 'up') || (geneFilter === 'down' && deg?.significant && deg.direction === 'down')))
    .sort((a, b) => geneSort === 'fdr'
      ? (a.deg?.adjusted_p_value ?? Infinity) - (b.deg?.adjusted_p_value ?? Infinity)
      : (b.node?.betweenness_centrality ?? -Infinity) - (a.node?.betweenness_centrality ?? -Infinity))
  const stats = module.detail.data?.statistics ?? module.selected?.statistics
  const memberIds = new Set(allGenes.map((gene) => gene.gene_id))
  const moduleGraphNodes = new Map<string, string>()
  const boundedModuleEdges = (moduleNetworkEdges?.items ?? []).filter((edge) => memberIds.has(edge.source_gene_id) && memberIds.has(edge.target_gene_id))
  const memberNetworkNodes = (moduleNetworkNodes?.items ?? []).filter((node) => memberIds.has(node.gene_id))
  memberNetworkNodes.forEach((node) => moduleGraphNodes.set(node.gene_id, node.gene_symbol || node.ensembl_id))
  boundedModuleEdges.forEach((edge) => {
    moduleGraphNodes.set(edge.source_gene_id, moduleGraphNodes.get(edge.source_gene_id) || edge.source_ensembl_id)
    moduleGraphNodes.set(edge.target_gene_id, moduleGraphNodes.get(edge.target_gene_id) || edge.target_ensembl_id)
  })
  const graphElements = [
    ...Array.from(moduleGraphNodes, ([id, label]) => ({ data: { id, label } })),
    ...boundedModuleEdges.map((edge, index) => ({ data: { id: `module-edge-${index}`, source: edge.source_gene_id, target: edge.target_gene_id, weight: edge.weight } })),
  ]
  return <Box>
    <RunHeader runId={runId ?? ''} view="module-explorer" title="Module Explorer" subtitle="Inspect a saved module and its backend-returned gene membership" />
    {runId && <>
      {module.isLoading && <LinearProgress />}
      {module.isError && <Alert severity="error">Could not load the run's module list.</Alert>}
      {!module.isLoading && !module.isError && !module.data?.total && <Alert severity="info">No modules are available in this run.</Alert>}
      {!!module.data?.items.length && <>
        <TextField select size="small" label="Module" value={module.moduleId} onChange={(event) => module.choose(event.target.value)} sx={{ minWidth: 360, mb: 2 }}>
          {module.data.items.map((item) => <MenuItem key={item.module_id} value={item.module_id}>{item.network_name} · {item.module_key} · {item.species}</MenuItem>)}
        </TextField>
        {module.moduleId && <ResultState loading={module.detail.isLoading || module.genes.isLoading} error={module.detail.isError || module.genes.isError} empty={!module.detail.data}>
          <Grid container spacing={1.5} sx={{ mb: 2 }}>
            {[['Module', module.detail.data?.module_key], ['Species', module.detail.data?.species], ['Network', module.detail.data?.network_name], ['Genes', module.genes.data?.total], ['Density', summaryValue(stats, 'density')], ['Average internal edge weight', summaryValue(stats, 'average_internal_edge_weight', 'avg_internal_edge_weight')], ['Detection', module.detail.data?.detection_method], ['Parameters', module.detail.data?.parameters]].map(([label, value]) => <Grid item xs={6} md={3} key={String(label)}><StatCard label={String(label)} value={value} /></Grid>)}
          </Grid>
          {moduleSpecies === 'mouse' && <Alert severity="warning" sx={{ mb: 1 }}>
            Mouse DEG labels below are exploratory: GSE155577 tumor samples are compared with normal mammary samples from the separate GSE116385 study. Positive log2FC means higher in the tumor cohort; negative means lower. Study, assay, and processing differences are confounded with condition, so these are not confirmatory cancer-versus-normal findings.
          </Alert>}
          {module.genes.data && module.genes.data.total > allGenes.length && <Alert severity="info" sx={{ mb: 1 }}>Showing {allGenes.length} of {module.genes.data.total} module genes.</Alert>}
            <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1} sx={{ mb: 1 }}>
              <TextField size="small" label="Search module genes" value={search} onChange={(event) => { setSearch(event.target.value); setPage(0) }} />
              <TextField select size="small" label="DEG filter" value={geneFilter} onChange={(event) => setGeneFilter(event.target.value)} sx={{ minWidth: 160 }}><MenuItem value="all">All genes</MenuItem><MenuItem value="significant">Significant</MenuItem><MenuItem value="up">Upregulated</MenuItem><MenuItem value="down">Downregulated</MenuItem></TextField>
              <TextField select size="small" label="Sort by" value={geneSort} onChange={(event) => setGeneSort(event.target.value)} sx={{ minWidth: 180 }}><MenuItem value="centrality">Betweenness</MenuItem><MenuItem value="fdr">Adjusted p-value</MenuItem></TextField>
            </Stack>
            <TableContainer component={Paper} variant="outlined"><Table size="small"><TableHead><TableRow>{['Gene ID', 'Gene symbol', moduleSpecies === 'mouse' ? 'Exploratory DEG' : 'DEG', 'log2FC', 'Adjusted p-value', 'Degree', 'Weighted degree', 'Betweenness', 'Module membership'].map((name) => <TableCell key={name} title={name === 'Degree' ? 'Number of connections a gene has within the network.' : name === 'Weighted degree' ? "Sum of the absolute weights of a gene's network connections." : name === 'Betweenness' ? 'Measures how frequently a node lies on shortest paths connecting other nodes.' : name === 'Module membership' ? 'Membership value returned for this gene in the saved module.' : undefined}>{name}</TableCell>)}</TableRow></TableHead><TableBody>
              {rows.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE).map(({ gene, geneIdentifier, geneSymbol, node, deg }) => <TableRow key={gene.gene_id}>
                <TableCell><Button size="small" component={RouterLink} to={`/runs/${runId}/network-explorer?network=${module.detail.data?.network_id}&gene=${encodeURIComponent(geneIdentifier)}`}>{geneIdentifier}</Button></TableCell>
              <TableCell>{geneSymbol ?? 'Not provided'}</TableCell><TableCell>{deg ? (deg.significant ? deg.direction : 'Not significant') : (moduleSpecies === 'mouse' ? 'No exploratory DEG row' : 'Not available')}</TableCell>
                <TableCell>{display(deg?.log2fc)}</TableCell><TableCell>{display(deg?.adjusted_p_value)}</TableCell>
                <TableCell>{display(node?.degree)}</TableCell><TableCell>{display(node?.weighted_degree)}</TableCell><TableCell>{display(node?.betweenness_centrality)}</TableCell><TableCell>{display(gene.membership ?? module.detail.data?.module_key)}</TableCell>
              </TableRow>)}
              {!rows.length && <TableRow><TableCell colSpan={9}>No module genes match this search or filter.</TableCell></TableRow>}
            </TableBody></Table></TableContainer>
            <TablePagination component="div" count={rows.length} page={page} onPageChange={(_, next) => setPage(next)} rowsPerPage={PAGE_SIZE} onRowsPerPageChange={() => undefined} rowsPerPageOptions={[PAGE_SIZE]} />
            <Typography variant="subtitle1" fontWeight={700} sx={{ mt: 2 }}>Module network (bounded data returned by API)</Typography>
            {graphElements.length > 1
              ? <Paper variant="outlined" sx={{ mt: 1 }}><CytoscapeComponent elements={graphElements} stylesheet={CY_STYLE} layout={{ name: 'cose', animate: false }} style={{ width: '100%', height: 420 }} /></Paper>
              : <Alert severity="info" sx={{ mt: 1 }}>No module-contained edges were present in the returned node/edge pages; no graph is inferred.</Alert>}
            <Typography variant="caption" color="text.secondary">Network node and edge data are paginated; this visualization is only the returned subgraph, not a complete module network.</Typography>
        </ResultState>}
      </>}
    </>}
  </Box>
}

export default ModuleExplorerPage
