import { useEffect, useRef, useState } from 'react'
import {
  Alert, Box, Button, Chip, CircularProgress, Divider, FormControl,
  Grid, InputLabel, LinearProgress, MenuItem, Paper, Select, Slider,
  Stack, TextField, Typography,
} from '@mui/material'
import CytoscapeComponent from 'react-cytoscapejs'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useSnackbar } from 'notistack'
import { networkApi, projectApi, datasetApi } from '@/api/client'
import type { Dataset, NetworkEdge, NetworkNode, Species } from '@/types'
import { useProjectStore } from '@/store/projectStore'

interface NetworkSummary {
  id: string
  analysis_id: string
  dataset_id: string
  name: string
  species: Species
  disease_state: string
  network_type: string
  correlation_method: string
  correlation_threshold: number
  n_nodes: number | null
  n_edges: number | null
  module_count: number | null
  density: number | null
  avg_degree: number | null
  status: string
  created_at: string
}

interface GeneDetails {
  gene_id: string
  expression_mean: number | null
  degree: number
  module: string | null
  hub_score: number
  ppi_degree: number | null
  ortholog: { gene_id: string; symbol: string | null } | null
  drift_score: number | null
  gene_loss_risk: number | null
  gene_loss_basis: string | null
}

const MODULE_COLORS = ['#1677a8', '#c4673d', '#25856b', '#a04f7c', '#9a7b20', '#5364a5', '#4e7b77', '#9a554f']

const CYTOSCAPE_STYLE = [
  {
    selector: 'node',
    style: {
      'background-color': 'data(color)',
      label: 'data(label)',
      color: '#fff',
      'font-size': 8,
      'text-valign': 'center',
      'text-halign': 'center',
      width: 'mapData(degree, 1, 40, 12, 34)',
      height: 'mapData(degree, 1, 40, 12, 34)',
      'border-width': 1,
      'border-color': '#f8fafc',
    },
  },
  { selector: 'node:selected', style: { 'background-color': '#f0b84b', 'border-width': 3, 'border-color': '#fff' } },
  {
    selector: 'edge',
    style: {
      width: 'mapData(weight, 0.5, 1, 0.5, 2.5)',
      'line-color': '#8aa6bb',
      opacity: 0.45,
      'curve-style': 'bezier',
    },
  },
]

function formatCount(value: number | null | undefined) {
  return value == null ? '—' : value.toLocaleString()
}

export default function NetworksPage() {
  const { enqueueSnackbar } = useSnackbar()
  const queryClient = useQueryClient()
  const {
    currentProjectId, currentAnalysisId, currentDatasetId,
    healthyNetworkId, diseaseNetworkId, setCurrentDataset, setWorkflowIds,
  } = useProjectStore()
  const [species, setSpecies] = useState<Species>('human')
  const [networkType, setNetworkType] = useState('co-expression')
  const [diseaseState, setDiseaseState] = useState<'cancer' | 'healthy'>('cancer')
  const [datasetId, setDatasetId] = useState(currentDatasetId ?? '')
  const [selectedNetworkId, setSelectedNetworkId] = useState(diseaseNetworkId ?? healthyNetworkId ?? '')
  const [selectedNode, setSelectedNode] = useState<NetworkNode | null>(null)
  const [correlationThreshold, setCorrelationThreshold] = useState(0.6)
  const [topGeneCount, setTopGeneCount] = useState(500)
  const nodeRowsRef = useRef<NetworkNode[]>([])

  const { data: projects = [] } = useQuery({
    queryKey: ['projects'],
    queryFn: () => projectApi.list().then((response) => response.data as Array<{ id: string; name: string }>),
  })
  const { data: datasets = [] } = useQuery({
    queryKey: ['datasets', currentProjectId],
    queryFn: () => currentProjectId ? datasetApi.list(currentProjectId).then((response) => response.data as Dataset[]) : [],
    enabled: !!currentProjectId,
  })
  const { data: networks = [], isLoading: networksLoading } = useQuery({
    queryKey: ['networks', currentProjectId],
    queryFn: () => currentProjectId ? networkApi.listForProject(currentProjectId).then((response) => response.data as NetworkSummary[]) : [],
    enabled: !!currentProjectId,
    refetchInterval: (query) => query.state.data?.some((network) => network.status === 'queued' || network.status === 'running') ? 4000 : false,
  })

  useEffect(() => {
    const availableDataset = datasets.find((dataset) => String(dataset.id) === String(datasetId) && dataset.species === species)
      ?? datasets.find((dataset) => String(dataset.id) === String(currentDatasetId) && dataset.species === species)
      ?? datasets.find((dataset) => dataset.species === species)
    if (availableDataset && String(availableDataset.id) !== datasetId) {
      setDatasetId(String(availableDataset.id))
      setCurrentDataset(String(availableDataset.id))
    } else if (!availableDataset && datasetId) {
      setDatasetId('')
    }
  }, [currentDatasetId, datasetId, datasets, setCurrentDataset, species])

  const matchingNetworks = networks.filter((network) =>
    network.species === species && network.disease_state === diseaseState,
  )
  useEffect(() => {
    if (selectedNetworkId && !networks.some((network) => network.id === selectedNetworkId)) return
    if (matchingNetworks.some((network) => network.id === selectedNetworkId)) return
    const workflowNetworkId = diseaseState === 'cancer' ? diseaseNetworkId : healthyNetworkId
    const nextNetwork = matchingNetworks.find((network) => network.id === workflowNetworkId)
      ?? matchingNetworks.find((network) => network.status === 'completed')
      ?? matchingNetworks[0]
    setSelectedNetworkId(nextNetwork?.id ?? '')
  }, [diseaseNetworkId, diseaseState, healthyNetworkId, matchingNetworks, selectedNetworkId])

  useEffect(() => {
    setSelectedNetworkId('')
    setSelectedNode(null)
  }, [currentProjectId])

  const selectedNetwork = networks.find((network) => network.id === selectedNetworkId) ?? null
  const { data: networkInfo, isLoading: networkInfoLoading } = useQuery({
    queryKey: ['network-info', selectedNetworkId],
    queryFn: () => networkApi.get(selectedNetworkId).then((response) => response.data as NetworkSummary),
    enabled: !!selectedNetworkId,
    refetchInterval: (query) => {
      const status = (query.state.data as NetworkSummary | undefined)?.status
      return status === 'queued' || status === 'running' ? 3000 : false
    },
  })
  const { data: nodes = [], isLoading: nodesLoading } = useQuery({
    queryKey: ['network-nodes', selectedNetworkId],
    queryFn: () => networkApi.getNodes(selectedNetworkId, 500).then((response) => response.data as NetworkNode[]),
    enabled: !!selectedNetworkId && networkInfo?.status === 'completed',
  })
  const { data: edges = [], isLoading: edgesLoading } = useQuery({
    queryKey: ['network-edges', selectedNetworkId],
    queryFn: () => networkApi.getEdges(selectedNetworkId, 3500).then((response) => response.data as NetworkEdge[]),
    enabled: !!selectedNetworkId && networkInfo?.status === 'completed',
  })
  const { data: geneDetails, isLoading: geneDetailsLoading } = useQuery({
    queryKey: ['network-gene-details', selectedNetworkId, selectedNode?.gene_id],
    queryFn: () => networkApi.getGeneDetails(selectedNetworkId, selectedNode!.gene_id).then((response) => response.data as GeneDetails),
    enabled: !!selectedNetworkId && !!selectedNode && networkInfo?.status === 'completed',
  })

  useEffect(() => {
    nodeRowsRef.current = nodes
  }, [nodes])
  useEffect(() => {
    setSelectedNode(null)
  }, [selectedNetworkId])

  const buildMutation = useMutation({
    mutationKey: ['networks', 'build'],
    mutationFn: () => {
      if (!currentAnalysisId || !datasetId) throw new Error('Select an analysis and dataset first')
      const stateName = diseaseState === 'healthy' ? 'Normal' : 'Breast Cancer'
      return networkApi.build({
        analysis_id: currentAnalysisId,
        dataset_id: datasetId,
        name: `${species === 'human' ? 'Human' : 'Mouse'} ${stateName} ${networkType}`,
        species,
        disease_state: diseaseState,
        correlation_method: 'pearson',
        correlation_threshold: correlationThreshold,
        fdr_threshold: 0.05,
        top_n_genes: topGeneCount,
        min_gene_variance: 0.1,
      })
    },
    onSuccess: (response) => {
      const job = response.data as { id: string; result_ref?: string }
      const networkId = job.result_ref ?? job.id
      setSelectedNetworkId(networkId)
      setWorkflowIds(diseaseState === 'healthy'
        ? { healthyNetworkId: networkId }
        : { diseaseNetworkId: networkId })
      queryClient.invalidateQueries({ queryKey: ['networks', currentProjectId] })
      enqueueSnackbar('Network construction queued', { variant: 'info' })
    },
    onError: () => enqueueSnackbar('Unable to start network construction', { variant: 'error' }),
  })

  const handleCyInit = (cy: any) => {
    cy.on('tap', 'node', (event: any) => {
      const geneId = event.target.id() as string
      const node = nodeRowsRef.current.find((row) => row.gene_id === geneId)
      if (node) setSelectedNode(node)
    })
  }

  const visibleNodeIds = new Set(nodes.map((node) => node.gene_id))
  const moduleIds = [...new Set(nodes.map((node) => node.module ?? 'M0'))]
  const elements = [
    ...nodes.map((node) => ({
      data: {
        id: node.gene_id,
        label: node.gene_id.length > 12 ? node.gene_id.slice(0, 12) : node.gene_id,
        degree: node.degree,
        module: node.module ?? 'M0',
        color: MODULE_COLORS[moduleIds.indexOf(node.module ?? 'M0') % MODULE_COLORS.length],
      },
    })),
    ...edges
      .filter((edge) => visibleNodeIds.has(edge.gene1) && visibleNodeIds.has(edge.gene2) && Math.abs(edge.weight) >= correlationThreshold)
      .map((edge) => ({
        data: { id: `${edge.gene1}-${edge.gene2}`, source: edge.gene1, target: edge.gene2, weight: Math.abs(edge.weight) },
      })),
  ]
  const isGraphLoading = nodesLoading || edgesLoading || networkInfoLoading
  const stateLabel = diseaseState === 'healthy' ? 'Normal' : 'Breast Cancer'
  const activeProjectName = projects.find((project) => project.id === currentProjectId)?.name
  const details = geneDetails
    ? [
        ['Expression (dataset mean)', geneDetails.expression_mean == null ? '—' : geneDetails.expression_mean.toPrecision(4)],
        ['Network degree', geneDetails.degree.toLocaleString()],
        ['Module', geneDetails.module ?? '—'],
        ['Hub score', `${(geneDetails.hub_score * 100).toFixed(1)}%`],
        ['PPI degree', geneDetails.ppi_degree == null ? 'Not available' : geneDetails.ppi_degree.toLocaleString()],
        ['Ortholog', geneDetails.ortholog ? `${geneDetails.ortholog.symbol ?? geneDetails.ortholog.gene_id}` : 'No mapping'],
        ['Drift score', geneDetails.drift_score == null ? 'Not available' : geneDetails.drift_score.toFixed(3)],
        ['Gene-loss risk', geneDetails.gene_loss_risk == null ? 'Not available' : `${(geneDetails.gene_loss_risk * 100).toFixed(1)}%`],
      ]
    : []

  return (
    <Box sx={{ maxWidth: 1440, mx: 'auto' }}>
      <Stack direction={{ xs: 'column', sm: 'row' }} justifyContent="space-between" alignItems={{ xs: 'flex-start', sm: 'center' }} spacing={1} sx={{ mb: 2.5 }}>
        <Box>
          <Typography variant="h4" fontWeight={800}>GENE NETWORKS</Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
            Construct and explore sample-derived co-expression networks{activeProjectName ? ` · ${activeProjectName}` : ''}.
          </Typography>
        </Box>
        {selectedNetwork && <Chip size="small" color={selectedNetwork.status === 'completed' ? 'success' : 'default'} label={selectedNetwork.status} />}
      </Stack>

      <Paper variant="outlined" sx={{ p: { xs: 1.5, md: 2 }, mb: 2.5 }}>
        <Grid container spacing={1.5} alignItems="center">
          <Grid item xs={6} md={1.5}>
            <FormControl fullWidth size="small">
              <InputLabel id="network-species-label">Species</InputLabel>
              <Select labelId="network-species-label" value={species} label="Species" onChange={(event) => setSpecies(event.target.value as Species)}>
                <MenuItem value="human">Human</MenuItem><MenuItem value="mouse">Mouse</MenuItem>
              </Select>
            </FormControl>
          </Grid>
          <Grid item xs={6} md={2}>
            <TextField select fullWidth size="small" label="Network type" value={networkType} onChange={(event) => setNetworkType(event.target.value)}>
              <MenuItem value="co-expression">Co-expression</MenuItem>
            </TextField>
          </Grid>
          <Grid item xs={6} md={1.5}>
            <TextField select fullWidth size="small" label="Condition" value={diseaseState} onChange={(event) => setDiseaseState(event.target.value as 'cancer' | 'healthy')}>
              <MenuItem value="cancer">Cancer</MenuItem><MenuItem value="healthy">Normal</MenuItem>
            </TextField>
          </Grid>
          <Grid item xs={6} md={3}>
            <TextField select fullWidth size="small" label="Dataset" value={datasetId} onChange={(event) => { setDatasetId(event.target.value); setCurrentDataset(event.target.value || null) }}>
              {datasets.filter((dataset) => dataset.species === species).map((dataset) => (
                <MenuItem key={dataset.id} value={String(dataset.id)}>{dataset.name}</MenuItem>
              ))}
            </TextField>
          </Grid>
          <Grid item xs={12} md={2.5}>
            <Stack direction="row" spacing={1} alignItems="center">
              <Typography variant="caption" sx={{ whiteSpace: 'nowrap' }}>Top variable genes</Typography>
              <TextField select size="small" value={topGeneCount} onChange={(event) => setTopGeneCount(Number(event.target.value))} sx={{ minWidth: 100 }}>
                {[500, 1000, 2000, 5000].map((count) => <MenuItem key={count} value={count}>{count.toLocaleString()}</MenuItem>)}
              </TextField>
            </Stack>
          </Grid>
          <Grid item xs={12} md={1.5}>
            <Button variant="contained" fullWidth onClick={() => buildMutation.mutate()} disabled={!currentAnalysisId || !datasetId || buildMutation.isPending}>
              {buildMutation.isPending ? <CircularProgress size={19} color="inherit" /> : 'Build Network'}
            </Button>
          </Grid>
          <Grid item xs={12} md={8}>
            <Typography variant="caption" color="text.secondary">Minimum absolute correlation: {correlationThreshold.toFixed(2)}</Typography>
            <Slider value={correlationThreshold} onChange={(_, value) => setCorrelationThreshold(value as number)} min={0.3} max={0.95} step={0.05} size="small" aria-label="Minimum correlation" />
          </Grid>
          <Grid item xs={12} md={4}>
            <TextField select fullWidth size="small" label="Saved network" value={selectedNetworkId}
              onChange={(event) => { setSelectedNetworkId(event.target.value); setSelectedNode(null) }}
              disabled={!matchingNetworks.length}>
              {matchingNetworks.map((network) => (
                <MenuItem key={network.id} value={network.id}>{network.name} · {network.status}</MenuItem>
              ))}
            </TextField>
          </Grid>
          {!currentAnalysisId && <Grid item xs={12}><Alert severity="warning">Select or create an analysis on Dashboard before building a network.</Alert></Grid>}
          {datasets.length > 0 && datasets.every((dataset) => dataset.species !== species) && <Grid item xs={12}><Alert severity="info">This project has no {species} dataset.</Alert></Grid>}
        </Grid>
      </Paper>

      {networksLoading && <LinearProgress sx={{ mb: 2 }} />}
      {selectedNetwork && networkInfo?.status === 'failed' && <Alert severity="error" sx={{ mb: 2 }}>Network construction failed. Review the analysis job details and adjust the network configuration.</Alert>}

      {networkInfo?.status === 'completed' && (
        <Grid container spacing={1.5} sx={{ mb: 2 }}>
          {[
            ['NODES', networkInfo.n_nodes, '#1677a8'],
            ['EDGES', networkInfo.n_edges, '#be5a32'],
            ['MODULES', selectedNetwork?.module_count ?? null, '#25856b'],
          ].map(([label, value, color]) => (
            <Grid item xs={4} key={String(label)}>
              <Paper variant="outlined" sx={{ p: 1.5, borderTop: `3px solid ${color}` }}>
                <Typography variant="caption" fontWeight={700} color="text.secondary" letterSpacing="0.08em">{label}</Typography>
                <Typography variant="h5" fontWeight={800}>{formatCount(value as number | null)}</Typography>
              </Paper>
            </Grid>
          ))}
        </Grid>
      )}

      {selectedNetworkId && (networkInfo?.status === 'queued' || networkInfo?.status === 'running') && (
        <Paper variant="outlined" sx={{ p: 2, mb: 2 }}>
          <Stack direction="row" spacing={1.5} alignItems="center" sx={{ mb: 1 }}>
            <CircularProgress size={18} />
            <Typography variant="body2">Building {species} {stateLabel.toLowerCase()} network…</Typography>
          </Stack>
          <LinearProgress />
        </Paper>
      )}

      {!currentProjectId && <Alert severity="info" sx={{ mb: 2 }}>Select or create a project before browsing networks.</Alert>}
      {currentProjectId && !networksLoading && matchingNetworks.length === 0 && (
        <Alert severity="info" sx={{ mb: 2 }}>No saved {species} {stateLabel.toLowerCase()} networks. Select a dataset and build one above.</Alert>
      )}

      {isGraphLoading && networkInfo?.status === 'completed' && <LinearProgress sx={{ mb: 1 }} />}
      {networkInfo?.status === 'completed' && elements.length > 0 && (
        <Grid container spacing={2}>
          <Grid item xs={12} lg={8.5}>
            <Paper variant="outlined" sx={{ overflow: 'hidden' }}>
              <Stack direction={{ xs: 'column', sm: 'row' }} justifyContent="space-between" alignItems={{ xs: 'flex-start', sm: 'center' }} spacing={0.5} sx={{ px: 2, py: 1.5, borderBottom: '1px solid', borderColor: 'divider' }}>
                <Box>
                  <Typography fontWeight={800}>{species.toUpperCase()} {stateLabel.toUpperCase()} NETWORK</Typography>
                  <Typography variant="caption" color="text.secondary">Showing a degree-ranked view · {nodes.length.toLocaleString()} genes · {elements.length - nodes.length} strongest visible edges</Typography>
                </Box>
                <Typography variant="caption" color="text.secondary">Colors indicate detected modules</Typography>
              </Stack>
              <Box sx={{ background: '#f4f7f9' }}>
                <CytoscapeComponent
                  elements={elements}
                  style={{ width: '100%', height: 'min(68vh, 680px)', minHeight: 440 }}
                  stylesheet={CYTOSCAPE_STYLE}
                  layout={{ name: 'cose', animate: false, randomize: false, nodeRepulsion: 6500, idealEdgeLength: 55 }}
                  cy={handleCyInit}
                />
              </Box>
              <Stack direction="row" spacing={2} alignItems="center" sx={{ px: 2, py: 1.25, borderTop: '1px solid', borderColor: 'divider' }}>
                <Typography variant="caption" color="text.secondary">Min edge correlation</Typography>
                <Slider value={correlationThreshold} onChange={(_, value) => setCorrelationThreshold(value as number)} min={0.3} max={0.95} step={0.05} size="small" aria-label="Filter graph edges" sx={{ maxWidth: 220 }} />
                <Typography variant="caption" fontWeight={700}>{correlationThreshold.toFixed(2)}</Typography>
              </Stack>
            </Paper>
          </Grid>
          <Grid item xs={12} lg={3.5}>
            <Paper variant="outlined" sx={{ p: 2, minHeight: 280 }}>
              <Typography variant="h6" fontWeight={800} gutterBottom>{selectedNode ? 'GENE DETAILS' : 'SELECT A GENE'}</Typography>
              {!selectedNode ? (
                <Typography variant="body2" color="text.secondary">Select a node in the network to inspect its expression, connectivity, module, orthology, drift, and gene-loss score.</Typography>
              ) : (
                <>
                  <Typography variant="body1" sx={{ fontFamily: 'monospace', fontWeight: 700, overflowWrap: 'anywhere' }}>{selectedNode.gene_id}</Typography>
                  <Typography variant="caption" color="text.secondary">{species} · {networkInfo.name}</Typography>
                  <Divider sx={{ my: 1.5 }} />
                  {geneDetailsLoading && <LinearProgress sx={{ mb: 1.5 }} />}
                  {details.map(([label, value]) => (
                    <Stack key={label} direction="row" justifyContent="space-between" spacing={1} sx={{ py: 0.8, borderBottom: '1px solid', borderColor: 'divider' }}>
                      <Typography variant="caption" color="text.secondary">{label}</Typography>
                      <Typography variant="caption" fontWeight={700} sx={{ textAlign: 'right', overflowWrap: 'anywhere', maxWidth: '58%' }}>{value}</Typography>
                    </Stack>
                  ))}
                  {geneDetails?.gene_loss_basis && <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 1 }}>Risk uses expression and co-expression connectivity.</Typography>}
                  {geneDetails?.ppi_degree == null && <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 1 }}>PPI degree is unavailable: this network contains co-expression edges, not a PPI reference.</Typography>}
                  {selectedNetwork?.status !== 'completed' && <Alert severity="info" sx={{ mt: 1 }}>Gene metrics require a completed network.</Alert>}
                </>
              )}
            </Paper>
          </Grid>
        </Grid>
      )}
      {networkInfo?.status === 'completed' && !isGraphLoading && elements.length === 0 && <Alert severity="warning">This network has no nodes or edges available to display.</Alert>}
      {selectedNetworkId && !networkInfo && !networkInfoLoading && <Alert severity="warning">Could not load the selected network.</Alert>}
      {selectedNetwork && <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 1.5 }}>The graph is a ranked visualization subset. Counts above represent the complete computed network.</Typography>}
    </Box>
  )
}
