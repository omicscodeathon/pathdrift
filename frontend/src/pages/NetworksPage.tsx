/**
 * Network Visualization Page — interactive Cytoscape.js network explorer.
 */
import { useEffect, useRef, useState } from 'react'
import {
  Box, Typography, Paper, Grid, TextField, Button, Slider, FormControl,
  InputLabel, Select, MenuItem, Chip, Alert, CircularProgress, Divider,
  Table, TableBody, TableCell, TableHead, TableRow, LinearProgress,
} from '@mui/material'
import CytoscapeComponent from 'react-cytoscapejs'
import { useQuery } from '@tanstack/react-query'
import { networkApi } from '@/api/client'
import type { NetworkNode, NetworkEdge } from '@/types'
import { useProjectStore } from '@/store/projectStore'

const CYTOSCAPE_STYLE = [
  {
    selector: 'node',
    style: {
      'background-color': '#1565c0',
      'label': 'data(label)',
      'font-size': '8px',
      'color': '#fff',
      'text-valign': 'center',
      'text-halign': 'center',
      'width': 'mapData(degree, 1, 50, 15, 45)',
      'height': 'mapData(degree, 1, 50, 15, 45)',
      'border-width': 1,
      'border-color': '#0d47a1',
    },
  },
  {
    selector: 'node:selected',
    style: { 'background-color': '#00acc1', 'border-width': 3, 'border-color': '#fff' },
  },
  {
    selector: 'edge',
    style: {
      'width': 'mapData(weight, 0.5, 1, 0.5, 3)',
      'line-color': 'mapData(weight, 0.5, 1, #90caf9, #1565c0)',
      'opacity': 0.6,
      'curve-style': 'bezier',
    },
  },
]

export default function NetworksPage() {
  const { healthyNetworkId, diseaseNetworkId } = useProjectStore()
  const [networkId, setNetworkId] = useState('')
  const [loadedNetworkId, setLoadedNetworkId] = useState('')
  const [selectedNode, setSelectedNode] = useState<NetworkNode | null>(null)
  const [correlationFilter, setCorrelationFilter] = useState(0.6)
  const cyRef = useRef<unknown>(null)

  useEffect(() => {
    if (!loadedNetworkId && healthyNetworkId) {
      setNetworkId(healthyNetworkId)
      setLoadedNetworkId(healthyNetworkId)
    } else if (!loadedNetworkId && diseaseNetworkId) {
      setNetworkId(diseaseNetworkId)
      setLoadedNetworkId(diseaseNetworkId)
    }
  }, [diseaseNetworkId, healthyNetworkId, loadedNetworkId])

  const { data: nodes, isLoading: nodesLoading } = useQuery({
    queryKey: ['network-nodes', loadedNetworkId],
    queryFn: () => networkApi.getNodes(loadedNetworkId).then(r => r.data as NetworkNode[]),
    enabled: !!loadedNetworkId,
  })

  const { data: edges, isLoading: edgesLoading } = useQuery({
    queryKey: ['network-edges', loadedNetworkId, correlationFilter],
    queryFn: () => networkApi.getEdges(loadedNetworkId, 2000).then(r => {
      const all = r.data as NetworkEdge[]
      return all.filter(e => Math.abs(e.weight) >= correlationFilter)
    }),
    enabled: !!loadedNetworkId,
  })

  const { data: networkInfo } = useQuery({
    queryKey: ['network-info', loadedNetworkId],
    queryFn: () => networkApi.get(loadedNetworkId).then(r => r.data),
    enabled: !!loadedNetworkId,
  })

  // Build Cytoscape elements
  const cyElements = []
  if (nodes) {
    for (const n of nodes.slice(0, 500)) {
      cyElements.push({
        data: {
          id: n.gene_id,
          label: n.gene_id.slice(0, 8),
          degree: n.degree,
          weight: n.weighted_degree,
        },
      })
    }
  }
  if (edges && nodes) {
    const nodeIds = new Set(nodes.slice(0, 500).map(n => n.gene_id))
    for (const e of edges.slice(0, 1500)) {
      if (nodeIds.has(e.gene1) && nodeIds.has(e.gene2)) {
        cyElements.push({
          data: {
            id: `${e.gene1}-${e.gene2}`,
            source: e.gene1,
            target: e.gene2,
            weight: e.weight,
          },
        })
      }
    }
  }

  const handleCyInit = (cy: unknown) => {
    cyRef.current = cy
    ;(cy as any).on('tap', 'node', (evt: unknown) => {
      const nodeId = (evt as { target: { id: () => string } }).target.id()
      const node = nodes?.find(n => n.gene_id === nodeId)
      if (node) setSelectedNode(node)
    })
  }

  const isLoading = nodesLoading || edgesLoading

  return (
    <Box>
      <Typography variant="h4" fontWeight={700} gutterBottom>Network Explorer</Typography>
      <Typography variant="body2" color="text.secondary" mb={3}>
        Interactive visualization of gene co-expression networks.
        Click a node to inspect its properties. Use the correlation filter to focus on strong interactions.
      </Typography>

      {/* Controls */}
      <Paper sx={{ p: 2, mb: 2 }} variant="outlined">
        <Grid container spacing={2} alignItems="center">
          <Grid item xs={12} sm={5}>
            <TextField
              label="Network ID" fullWidth size="small"
              value={networkId} onChange={e => setNetworkId(e.target.value)}
            />
          </Grid>
          <Grid item xs={12} sm={3}>
            <Button variant="contained" fullWidth onClick={() => setLoadedNetworkId(networkId)} disabled={!networkId}>
              Load Network
            </Button>
          </Grid>
          <Grid item xs={12} sm={4}>
            <Typography variant="body2" gutterBottom>Min Correlation: {correlationFilter.toFixed(2)}</Typography>
            <Slider
              value={correlationFilter}
              onChange={(_, v) => setCorrelationFilter(v as number)}
              min={0.3} max={1} step={0.05} size="small"
            />
          </Grid>
        </Grid>
      </Paper>

      {networkInfo && (
        <Box sx={{ display: 'flex', gap: 1, mb: 2, flexWrap: 'wrap' }}>
          <Chip label={`${networkInfo.species === 'human' ? '🧬 Human' : '🐭 Mouse'}`} />
          <Chip label={`${networkInfo.disease_state}`} color={networkInfo.disease_state === 'healthy' ? 'success' : 'error'} />
          <Chip label={`${networkInfo.n_nodes} nodes`} />
          <Chip label={`${networkInfo.n_edges} edges`} />
          <Chip label={`Density: ${networkInfo.density?.toFixed(4)}`} />
          <Chip label={`Avg degree: ${networkInfo.avg_degree?.toFixed(1)}`} />
        </Box>
      )}

      {isLoading && <LinearProgress sx={{ mb: 1 }} />}

      {!loadedNetworkId ? (
        <Alert severity="info">Enter a Network ID above to visualize the network.</Alert>
      ) : cyElements.length > 0 ? (
        <Grid container spacing={2}>
          <Grid item xs={12} md={9}>
            <Paper variant="outlined" sx={{ overflow: 'hidden' }}>
              <CytoscapeComponent
                elements={cyElements}
                style={{ width: '100%', height: '580px', background: '#0f1729' }}
                stylesheet={CYTOSCAPE_STYLE}
                layout={{ name: 'cose', animate: false, randomize: false }}
                cy={handleCyInit}
              />
            </Paper>
          </Grid>
          <Grid item xs={12} md={3}>
            <Paper sx={{ p: 2, height: '100%' }} variant="outlined">
              <Typography variant="subtitle1" fontWeight={600} gutterBottom>
                {selectedNode ? 'Gene Details' : 'Select a node'}
              </Typography>
              {selectedNode && (
                <Box>
                  <Typography variant="body2" sx={{ fontFamily: 'monospace', fontWeight: 600, mb: 1 }}>
                    {selectedNode.gene_id}
                  </Typography>
                  <Divider sx={{ mb: 1 }} />
                  {[
                    ['Degree', selectedNode.degree],
                    ['Weighted Degree', selectedNode.weighted_degree?.toFixed(2)],
                    ['Betweenness', selectedNode.betweenness?.toFixed(4)],
                    ['Closeness', selectedNode.closeness?.toFixed(4)],
                    ['Clustering', selectedNode.clustering?.toFixed(4)],
                    ['Module', selectedNode.module],
                  ].map(([label, value]) => (
                    <Box key={label as string} sx={{ display: 'flex', justifyContent: 'space-between', mb: 0.5 }}>
                      <Typography variant="caption" color="text.secondary">{label}</Typography>
                      <Typography variant="caption" fontWeight={600}>{value ?? '—'}</Typography>
                    </Box>
                  ))}
                </Box>
              )}
            </Paper>
          </Grid>
        </Grid>
      ) : (
        <Alert severity="warning">
          No data to display. The network may still be computing, or correlation filter is too strict.
        </Alert>
      )}
    </Box>
  )
}
