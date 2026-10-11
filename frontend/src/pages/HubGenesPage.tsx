import { useState } from 'react'
import {
  Alert, Box, Chip, LinearProgress, Paper, Table, TableBody,
  TableCell, TableContainer, TableHead, TablePagination, TableRow, Tabs, Tab,
  Typography,
} from '@mui/material'
import { useQuery } from '@tanstack/react-query'
import { useParams } from 'react-router-dom'
import { phase5Api } from '@/api/client'
import { Page, RunHeader } from '@/pages/analysis/shared'
import { RunPicker } from '@/pages/analysis/shared'

type HubRow = Record<string, string | null>
type NetworkOption = {
  id: 'hub-human-cancer' | 'hub-human-healthy' | 'hub-mouse-cancer' | 'hub-mouse-healthy'
  label: string
}

const NETWORKS: NetworkOption[] = [
  { id: 'hub-human-cancer', label: 'Human cancer' },
  { id: 'hub-human-healthy', label: 'Human healthy' },
  { id: 'hub-mouse-cancer', label: 'Mouse cancer' },
  { id: 'hub-mouse-healthy', label: 'Mouse healthy' },
]
const PAGE_SIZE = 50
const COLUMNS = [
  ['gene_symbol', 'Gene'],
  ['gene_id', 'Gene ID'],
  ['module_id', 'Module'],
  ['hub_supported', 'Hub supported'],
  ['hub_score', 'Mean centrality percentile'],
  ['hub_metric_count', 'Available metrics'],
  ['degree', 'Degree'],
  ['weighted_degree', 'Weighted degree'],
  ['betweenness_centrality', 'Betweenness'],
  ['eigenvector_centrality', 'Eigenvector'],
  ['closeness_centrality', 'Closeness'],
  ['intramodular_connectivity', 'Intramodular connectivity'],
] as const

export default function HubGenesPage() {
  const { runId } = useParams<{ runId: string }>()
  const [networkId, setNetworkId] = useState<NetworkOption['id']>('hub-human-cancer')
  const [page, setPage] = useState(0)
  const { data: summary, isLoading: summaryLoading, isError: summaryError } = useQuery({
    queryKey: ['phase5-hub-summary', runId],
    queryFn: () => phase5Api.summary(runId!).then((response) => response.data as {
      stages?: { hub_genes?: { status: string; networks?: Record<string, { genes: number; module_assigned_genes: number; hub_supported_genes: number; modules: number }> } }
    }),
    enabled: !!runId,
  })
  const { data: result, isLoading, isError } = useQuery({
    queryKey: ['phase5-hub-table', runId, networkId, page],
    queryFn: () => phase5Api.table(runId!, networkId, PAGE_SIZE, page * PAGE_SIZE).then((response) => response.data as Page<HubRow>),
    enabled: !!runId,
  })

  if (!runId) return <RunPicker />
  const selected = NETWORKS.find((network) => network.id === networkId)!
  const networkSummary = summary?.stages?.hub_genes?.networks?.[selected.label.toLowerCase().replace(' ', '_')]

  return (
    <Box sx={{ maxWidth: 1500, mx: 'auto' }}>
      <RunHeader runId={runId} view="hub-genes" title="HUB GENES"
        subtitle="Within-module multi-metric centrality for genes in saved human and mouse networks." />
      {(summaryLoading || isLoading) && <LinearProgress sx={{ mb: 2 }} />}
      {(summaryError || isError) && <Alert severity="error" sx={{ mb: 2 }}>Could not load hub metrics for this analysis run.</Alert>}
      {summary?.stages?.hub_genes?.status === 'UNAVAILABLE' && <Alert severity="info" sx={{ mb: 2 }}>Hub analysis is not available for this run.</Alert>}
      <Alert severity="info" sx={{ mb: 2 }}>
        Hub support requires at least two available metrics and a mean within-module percentile of 0.90 or higher across degree, weighted degree, betweenness, eigenvector centrality, closeness, and intramodular connectivity. It does not by itself imply biomarker status.
      </Alert>
      <Paper variant="outlined" sx={{ mb: 2 }}>
        <Tabs value={networkId} onChange={(_, value: NetworkOption['id']) => { setNetworkId(value); setPage(0) }}
          variant="scrollable" scrollButtons="auto">
          {NETWORKS.map((network) => <Tab key={network.id} value={network.id} label={network.label} />)}
        </Tabs>
        {networkSummary && (
          <Box sx={{ p: 2 }}>
            <Chip size="small" label={`${networkSummary.hub_supported_genes} hub-supported genes`} sx={{ mr: 1 }} />
            <Chip size="small" variant="outlined" label={`${networkSummary.module_assigned_genes} module-assigned genes`} sx={{ mr: 1 }} />
            <Chip size="small" variant="outlined" label={`${networkSummary.modules} modules`} />
          </Box>
        )}
        {result && (
          <>
            <TableContainer sx={{ maxHeight: 680, overflowX: 'auto' }}>
              <Table size="small" stickyHeader sx={{ minWidth: 1300 }}>
                <TableHead><TableRow>{COLUMNS.map(([, label]) => <TableCell key={label}>{label}</TableCell>)}</TableRow></TableHead>
                <TableBody>
                  {result.items.map((row) => <TableRow hover key={row.gene_id}>
                    {COLUMNS.map(([key]) => <TableCell key={key} sx={{ whiteSpace: 'nowrap' }}>{row[key] || '—'}</TableCell>)}
                  </TableRow>)}
                  {!result.items.length && <TableRow><TableCell colSpan={COLUMNS.length}>No hub metrics are available for this network.</TableCell></TableRow>}
                </TableBody>
              </Table>
            </TableContainer>
            <TablePagination component="div" count={result.total} page={page} rowsPerPage={PAGE_SIZE}
              rowsPerPageOptions={[PAGE_SIZE]} onPageChange={(_, nextPage) => setPage(nextPage)} />
          </>
        )}
      </Paper>
      {networkSummary && <Typography variant="caption" color="text.secondary">Table contains {networkSummary.genes.toLocaleString()} measured network nodes.</Typography>}
    </Box>
  )
}
