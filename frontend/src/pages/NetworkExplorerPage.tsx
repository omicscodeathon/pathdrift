import { useEffect, useState } from 'react'
import { Link as RouterLink, useSearchParams } from 'react-router-dom'
import { Alert, Box, Button, Grid, LinearProgress, MenuItem, Paper, Stack, Table, TableBody, TableCell, TableContainer, TableHead, TableRow, TextField, Typography } from '@mui/material'
import CytoscapeComponent from 'react-cytoscapejs'
import { useQuery } from '@tanstack/react-query'
import { phase3Api } from '@/api/client'
import { CY_STYLE, display, NETWORK_EDGE_LIMIT, NETWORK_NODE_LIMIT, ResultState, RunHeader, useNetworks, useRunId, type Edge, type NetworkNode, type Page } from './analysis/shared'

export function NetworkExplorerPage() {
  const runId = useRunId()
  const [searchParams, setSearchParams] = useSearchParams()
  const { data: networks = [], isLoading: networksLoading, isError: networksError } = useNetworks(runId)
  const [search, setSearch] = useState(searchParams.get('gene') ?? '')
  const [minCorrelation, setMinCorrelation] = useState(0)
  const [neighborLimit, setNeighborLimit] = useState(25)
  const networkId = searchParams.get('network') ?? ''
  const setNetworkId = (value: string) => {
    setSearch('')
    setSearchParams((params) => { params.set('network', value); params.delete('gene'); return params }, { replace: true })
  }
  const { data: nodePage, isLoading: nodesLoading, isError: nodesError } = useQuery({
    queryKey: ['phase3-network-nodes', runId, networkId],
    queryFn: () => phase3Api.nodes(runId!, networkId, NETWORK_NODE_LIMIT, 0).then((response) => response.data as Page<NetworkNode>),
    enabled: !!runId && !!networkId,
  })
  const { data: edgePage, isLoading: edgesLoading, isError: edgesError } = useQuery({
    queryKey: ['phase3-network-edges', runId, networkId],
    queryFn: () => phase3Api.edges(runId!, networkId, NETWORK_EDGE_LIMIT, 0).then((response) => response.data as Page<Edge>),
    enabled: !!runId && !!networkId,
  })
  const nodes = nodePage?.items ?? []
  const edges = edgePage?.items ?? []
  useEffect(() => {
    if (!networks.some((network) => network.network_id === networkId) && networks.length) setNetworkId(networks[0].network_id)
  }, [networkId, networks])
  const selectedGene = nodes.find((node) => node.gene_id === search || node.ensembl_id.toLowerCase() === search.toLowerCase() || node.gene_symbol?.toLowerCase() === search.toLowerCase())
  const connectedEdges = selectedGene ? edges.filter((edge) =>
    (edge.source_gene_id === selectedGene.gene_id || edge.target_gene_id === selectedGene.gene_id)
    && edge.absolute_correlation >= minCorrelation,
  ) : []
  const graphEdges = selectedGene
    ? connectedEdges.slice(0, neighborLimit)
    : edges.filter((edge) => edge.absolute_correlation >= minCorrelation)
  const visibleEdges = graphEdges.slice(0, selectedGene ? neighborLimit : Math.min(neighborLimit, NETWORK_EDGE_LIMIT))
  const graphNodeIds = new Set<string>()
  if (selectedGene) {
    graphNodeIds.add(selectedGene.gene_id)
    graphEdges.forEach((edge) => graphNodeIds.add(edge.source_gene_id === selectedGene.gene_id ? edge.target_gene_id : edge.source_gene_id))
  } else {
    graphEdges.forEach((edge) => {
      graphNodeIds.add(edge.source_gene_id)
      graphNodeIds.add(edge.target_gene_id)
    })
  }
  const graphNodes = nodes.filter((node) => graphNodeIds.has(node.gene_id))
  const graphNodeMap = new Map(graphNodes.map((node) => [node.gene_id, node.gene_symbol || node.ensembl_id]))
  graphEdges.forEach((edge) => {
    graphNodeMap.set(edge.source_gene_id, graphNodeMap.get(edge.source_gene_id) || edge.source_ensembl_id)
    graphNodeMap.set(edge.target_gene_id, graphNodeMap.get(edge.target_gene_id) || edge.target_ensembl_id)
  })
  const graphElements = [
    ...Array.from(graphNodeMap, ([id, label]) => ({ data: { id, label } })),
    ...graphEdges.filter((edge) => graphNodeIds.has(edge.source_gene_id) && graphNodeIds.has(edge.target_gene_id)).map((edge, index) => ({ data: { id: `${edge.source_gene_id}-${edge.target_gene_id}-${index}`, source: edge.source_gene_id, target: edge.target_gene_id, weight: edge.weight } })),
  ]
  return <Box>
    <RunHeader runId={runId ?? ''} view="network-explorer" title="Network Explorer" subtitle="Inspect real run nodes and a bounded set of returned edges" />
    {runId && <>
      <ResultState loading={networksLoading} error={networksError} empty={!networks.length}>
        <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1.5} sx={{ mb: 2 }}>
          <TextField select size="small" label="Network" value={networkId} onChange={(event) => setNetworkId(event.target.value)} sx={{ minWidth: 300 }}>
            {networks.map((network) => <MenuItem key={network.network_id} value={network.network_id}>{network.name} · {network.species}</MenuItem>)}
          </TextField>
          <TextField size="small" label="Search loaded top-100 nodes by symbol or ID" value={search} onChange={(event) => setSearch(event.target.value)} />
          <TextField size="small" type="number" label="Minimum |correlation|" value={minCorrelation} inputProps={{ min: 0, max: 1, step: 0.05 }} onChange={(event) => setMinCorrelation(Math.min(1, Math.max(0, Number(event.target.value))))} sx={{ width: 180 }} />
          <TextField size="small" type="number" label="Neighbor limit" value={neighborLimit} inputProps={{ min: 1, max: 50 }} onChange={(event) => setNeighborLimit(Math.min(50, Math.max(1, Number(event.target.value))))} sx={{ width: 150 }} />
        </Stack>
        {(nodesLoading || edgesLoading) && <LinearProgress sx={{ mb: 2 }} />}
        {(nodesError || edgesError) && <Alert severity="error">Network nodes or edges could not be loaded.</Alert>}
        <Alert severity="info" sx={{ mb: 2 }}>
          {selectedGene
            ? `Showing up to ${neighborLimit} returned connections for ${selectedGene.gene_symbol || selectedGene.ensembl_id}.`
            : `Network overview from the first ${NETWORK_EDGE_LIMIT} ordered edges returned by the API. Search a loaded node to inspect its connections.`}
          {' '}The full large graph is not loaded into the browser.
        </Alert>
        {(selectedGene || graphElements.length > 0) ? <Grid container spacing={2}>
          {selectedGene && <Grid item xs={12} md={4}><Paper variant="outlined" sx={{ p: 2 }}>
            <Typography variant="h6">{selectedGene.gene_symbol || selectedGene.ensembl_id}</Typography>
            <Typography variant="body2" color="text.secondary">{selectedGene.ensembl_id}</Typography>
            <Typography sx={{ mt: 1 }}>Degree: {selectedGene.degree.toLocaleString()} · Weighted degree: {display(selectedGene.weighted_degree)}</Typography>
            <Typography>Betweenness: {display(selectedGene.betweenness_centrality)}</Typography><Typography>Closeness: {display(selectedGene.closeness_centrality)}</Typography>
            <Typography>Eigenvector: {display(selectedGene.eigenvector_centrality)}</Typography><Typography>Module: {selectedGene.module_id ?? 'Not assigned'}</Typography>
            {selectedGene.module_id && <Button component={RouterLink} to={`/runs/${runId}/module-explorer?module=${selectedGene.module_id}`} sx={{ mt: 1 }}>Explore module</Button>}
          </Paper></Grid>}
          <Grid item xs={12} md={selectedGene ? 8 : 12}><Paper variant="outlined" sx={{ p: 1 }}>
            {graphElements.length > 1 ? <CytoscapeComponent elements={graphElements} stylesheet={CY_STYLE} layout={{ name: 'cose', animate: false }} style={{ width: '100%', height: 420 }} /> : <Alert severity="info">No matching selected-gene edges were present in the bounded edge page.</Alert>}
          </Paper></Grid>
          <Grid item xs={12}><TableContainer component={Paper} variant="outlined"><Table size="small"><TableHead><TableRow>{['Neighbor', 'Correlation', 'FDR', 'Weight'].map((label) => <TableCell key={label}>{label}</TableCell>)}</TableRow></TableHead><TableBody>
            {visibleEdges.map((edge) => <TableRow key={`${edge.source_gene_id}-${edge.target_gene_id}`}><TableCell>{selectedGene ? (edge.source_gene_id === selectedGene.gene_id ? edge.target_ensembl_id : edge.source_ensembl_id) : `${edge.source_ensembl_id} — ${edge.target_ensembl_id}`}</TableCell><TableCell>{display(edge.correlation)}</TableCell><TableCell>{display(edge.adjusted_p_value)}</TableCell><TableCell>{display(edge.weight)}</TableCell></TableRow>)}
            {!visibleEdges.length && <TableRow><TableCell colSpan={4}>No edges were returned for this network.</TableCell></TableRow>}
          </TableBody></Table></TableContainer></Grid>
        </Grid> : <Alert severity="info">This network has no edges in the returned page.</Alert>}
        {!!nodes.length && <Typography variant="caption" color="text.secondary">Loaded {nodes.length} of {nodePage?.total.toLocaleString()} nodes. Search matches the currently returned node page only.</Typography>}
      </ResultState>
    </>}
  </Box>
}

export default NetworkExplorerPage
