import { Alert, Box, Button, Chip, Grid, Paper, Stack, Typography } from '@mui/material'
import { Link as RouterLink } from 'react-router-dom'
import { asRecord, display, ResultState, RunHeader, summaryValue, useNetworks, useRunId } from './analysis/shared'

export function GeneNetworksPage() {
  const runId = useRunId()
  const { data: networks = [], isLoading, isError } = useNetworks(runId)
  return <Box>
    <RunHeader runId={runId ?? ''} view="networks" title="Gene Networks" subtitle="Run-scoped expression-derived networks and reported network statistics" />
    {runId && <ResultState loading={isLoading} error={isError} empty={!networks.length}>
      <Grid container spacing={2}>{networks.map((network) => {
        const s = network.summary
        const correlationConfig = asRecord(asRecord(s?.filtering).correlation)
        const configuredCorrelation = asRecord(asRecord(network.configuration).correlation)
        return <Grid item xs={12} md={6} key={network.network_id}><Paper variant="outlined" sx={{ p: 2, height: '100%' }}>
          <Stack direction="row" justifyContent="space-between" alignItems="flex-start"><Box><Typography variant="h6" fontWeight={700}>{network.name}</Typography><Typography color="text.secondary">{network.species} · {network.disease_state}</Typography></Box><Chip size="small" label={network.method} /></Stack>
          <Grid container spacing={1} sx={{ mt: 1 }}>{[
            ['Nodes', summaryValue(s, 'n_nodes', 'nodes')], ['Edges', summaryValue(s, 'n_edges', 'edges')],
            ['Density', summaryValue(s, 'density')], ['Average degree', summaryValue(s, 'average_degree', 'avg_degree')],
            ['Components', summaryValue(s, 'connected_components', 'n_components')], ['Largest component', summaryValue(s, 'largest_connected_component', 'largest_component_size')],
            ['Average edge weight', summaryValue(s, 'average_absolute_edge_weight', 'average_edge_weight', 'avg_edge_weight')], ['Correlation method', summaryValue(s, 'method') ?? summaryValue(network.configuration, 'correlation_method')],
            ['Correlation threshold', summaryValue(correlationConfig, 'min_abs_correlation') ?? summaryValue(configuredCorrelation, 'correlation_threshold') ?? summaryValue(network.configuration, 'correlation_threshold')], ['FDR threshold', summaryValue(correlationConfig, 'max_adjusted_p_value') ?? summaryValue(configuredCorrelation, 'fdr_threshold') ?? summaryValue(network.configuration, 'fdr_threshold')],
          ].map(([label, value]) => <Grid item xs={6} key={String(label)}><Typography variant="caption" color="text.secondary">{String(label)}</Typography><Typography variant="body2" fontWeight={700}>{display(value)}</Typography></Grid>)}</Grid>
          <Stack direction="row" spacing={1} sx={{ mt: 2 }}><Button component={RouterLink} to={`/runs/${runId}/network-explorer?network=${network.network_id}`} size="small">Explore network</Button><Button component={RouterLink} to={`/runs/${runId}/modules?network=${network.network_id}`} size="small">View modules</Button></Stack>
        </Paper></Grid>
      })}</Grid>
      {networks.length < 2 && <Alert severity="info" sx={{ mt: 2 }}>Only networks returned for this run are shown. No missing reference network has been inferred.</Alert>}
    </ResultState>}
  </Box>
}

export default GeneNetworksPage
