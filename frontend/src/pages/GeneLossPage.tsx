import { useEffect, useMemo, useState } from 'react'
import {
  Alert, Box, Button, Chip, LinearProgress, MenuItem, Paper, Stack, Tab,
  Table, TableBody, TableCell, TableContainer, TableHead, TablePagination,
  TableRow, Tabs, TextField, Typography,
} from '@mui/material'
import { useQuery } from '@tanstack/react-query'
import { useNavigate, useParams } from 'react-router-dom'
import { phase5Api } from '@/api/client'
import { Page, Run, RunHeader, RunPicker, useRunContext } from '@/pages/analysis/shared'

type ResultRow = Record<string, string | null>

interface GeneLossSummary {
  status: string
  evidence_rows: number
  scored_gene_pairs: number
  high_risk_gene_pairs: number
  configuration: {
    gene_loss_weights?: Record<string, number>
    risk_thresholds?: Record<string, number>
    deg_fdr_threshold?: number
    deg_lfc_threshold?: number
  }
  limitations: string[]
}

const RESULT_TABLES = [
  { id: 'gene-loss', label: 'Gene loss scores', description: 'All ortholog pairs ranked by evidence-aware score.' },
  { id: 'high-risk', label: 'High-priority pairs', description: 'Pairs meeting the configured high-priority score threshold.' },
  { id: 'gene-loss-evidence', label: 'Evidence details', description: 'Per-pair expression, drift, orthology, and missing-evidence fields.' },
] as const

const PAGE_SIZE = 50

function columnLabel(column: string) {
  return column.replace(/_/g, ' ').replace(/\b\w/g, (letter) => letter.toUpperCase())
}

export default function GeneLossPage() {
  const { runId } = useParams<{ runId: string }>()
  const navigate = useNavigate()
  const [selectedTable, setSelectedTable] = useState<(typeof RESULT_TABLES)[number]['id']>('gene-loss')
  const [page, setPage] = useState(0)
  const runContext = useRunContext(runId)

  const { data: summary, isLoading: summaryLoading, isError: summaryError } = useQuery({
    queryKey: ['phase5-gene-loss-summary', runId],
    queryFn: () => phase5Api.geneLossSummary(runId!).then((response) => response.data as GeneLossSummary),
    enabled: !!runId,
  })
  const { data: resultPage, isLoading: tableLoading, isError: tableError } = useQuery({
    queryKey: ['phase5-gene-loss-table', runId, selectedTable, page],
    queryFn: () => phase5Api.table(runId!, selectedTable, PAGE_SIZE, page * PAGE_SIZE).then((response) => response.data as Page<ResultRow>),
    enabled: !!runId,
  })
  const { data: figureBlob, isError: figureError } = useQuery({
    queryKey: ['phase5-gene-loss-figure', runId],
    queryFn: () => phase5Api.geneLossFigure(runId!).then((response) => response.data),
    enabled: !!runId,
  })
  const figureUrl = useMemo(() => figureBlob ? URL.createObjectURL(figureBlob) : null, [figureBlob])
  useEffect(() => () => {
    if (figureUrl) URL.revokeObjectURL(figureUrl)
  }, [figureUrl])

  if (!runId) return <RunPicker />

  if (runContext.loading || summaryLoading) {
    return <Box sx={{ maxWidth: 1400, mx: 'auto' }}><RunHeader runId={runId} view="gene-loss" title="GENE LOSS" subtitle="Run-scoped gene-loss evidence and scores." /><LinearProgress /></Box>
  }

  const columns = resultPage?.items[0] ? Object.keys(resultPage.items[0]) : []
  const activeTable = RESULT_TABLES.find((table) => table.id === selectedTable)!
  const availableRuns = runContext.runs
  const summaryItems = summary ? [
    ['Evidence pairs', summary.evidence_rows],
    ['Scored pairs', summary.scored_gene_pairs],
    ['High-priority pairs', summary.high_risk_gene_pairs],
  ] as const : []

  return (
    <Box sx={{ maxWidth: 1500, mx: 'auto' }}>
      <RunHeader runId={runId} view="gene-loss" title="GENE LOSS"
        subtitle="Evidence-aware gene-loss prioritization from saved DEG, orthology, and network-drift results." />
      {runContext.error && <Alert severity="error" sx={{ mb: 2 }}>Unable to load this run or verify your access.</Alert>}
      {summaryError && (
        <Alert severity="warning" sx={{ mb: 2 }}>
          Gene-loss artifacts are not available for this run yet. Generate the run-scoped results with <code>pathdrift phase5 --run-id {runId}</code>, then refresh.
        </Alert>
      )}
      {summary && (
        <>
          <Stack direction={{ xs: 'column', md: 'row' }} spacing={1.5} alignItems={{ xs: 'stretch', md: 'center' }} sx={{ mb: 2 }}>
            <TextField select size="small" label="Analysis run" value={runId}
              onChange={(event) => navigate(`/runs/${event.target.value}/gene-loss`)}
              sx={{ minWidth: { xs: '100%', md: 360 } }}>
              {!availableRuns.some((run: Run) => run.id === runId) && <MenuItem value={runId}>Current run · {runId}</MenuItem>}
              {availableRuns.map((run: Run) => <MenuItem key={run.id} value={run.id}>{run.project_name ?? 'Saved analysis'} · {new Date(run.created_at).toLocaleDateString()}</MenuItem>)}
            </TextField>
            <Chip color="info" variant="outlined" label={`Results: ${summary.status}`} />
            {summaryItems.map(([label, value]) => <Chip key={label} label={`${label}: ${Number(value).toLocaleString()}`} />)}
          </Stack>

          <Alert severity="warning" sx={{ mb: 2 }}>
            Research prioritization only, not a clinical risk estimate. The mouse expression comparison is cross-study exploratory and is excluded from the score. Human and mouse network densities differ substantially.
          </Alert>

          <Stack direction={{ xs: 'column', lg: 'row' }} spacing={2} sx={{ mb: 2 }}>
            <Paper variant="outlined" sx={{ p: 2, flex: 1 }}>
              <Typography variant="subtitle1" fontWeight={700} gutterBottom>Scoring configuration</Typography>
              <Typography variant="body2">Weights: {Object.entries(summary.configuration.gene_loss_weights ?? {}).map(([key, value]) => `${columnLabel(key)} ${value}`).join(' · ')}</Typography>
              <Typography variant="body2">Human DEG threshold: FDR ≤ {summary.configuration.deg_fdr_threshold}; log2FC ≤ -{summary.configuration.deg_lfc_threshold}</Typography>
              <Typography variant="body2">Priority thresholds: {Object.entries(summary.configuration.risk_thresholds ?? {}).map(([key, value]) => `${columnLabel(key)} ≥ ${value}`).join(' · ')}</Typography>
              <Typography variant="caption" color="text.secondary">Scores renormalize the configured weights over available components; missing evidence is not substituted with zero.</Typography>
            </Paper>
            <Paper variant="outlined" sx={{ p: 2, flex: 1 }}>
              <Typography variant="subtitle1" fontWeight={700} gutterBottom>Gene-loss score distribution</Typography>
              {figureUrl && <Box component="img" src={figureUrl} alt="Histogram of evidence-aware gene-loss scores" sx={{ display: 'block', width: '100%', maxHeight: 300, objectFit: 'contain' }} />}
              {figureError && <Typography color="text.secondary">Saved score-distribution figure is not available.</Typography>}
            </Paper>
          </Stack>

          {!!summary.limitations.length && (
            <Paper variant="outlined" sx={{ p: 2, mb: 2 }}>
              <Typography variant="subtitle1" fontWeight={700} gutterBottom>Interpretation and limitations</Typography>
              <Stack component="ul" sx={{ mt: 0, mb: 0, pl: 2.5 }}>
                {summary.limitations.map((limitation) => <Typography component="li" variant="body2" key={limitation}>{limitation}</Typography>)}
              </Stack>
            </Paper>
          )}

          <Paper variant="outlined">
            <Tabs value={selectedTable} onChange={(_, value: (typeof RESULT_TABLES)[number]['id']) => { setSelectedTable(value); setPage(0) }}
              variant="scrollable" scrollButtons="auto">
              {RESULT_TABLES.map((table) => <Tab key={table.id} value={table.id} label={table.label} />)}
            </Tabs>
            <Box sx={{ p: 2, pb: 0 }}>
              <Typography variant="body2" color="text.secondary">{activeTable.description}</Typography>
              {resultPage && <Typography variant="caption" color="text.secondary">{resultPage.total.toLocaleString()} saved rows</Typography>}
            </Box>
            {tableLoading && <LinearProgress sx={{ mt: 1 }} />}
            {tableError && <Alert severity="error" sx={{ m: 2 }}>Could not load the selected gene-loss artifact.</Alert>}
            <TableContainer sx={{ maxHeight: 650, overflowX: 'auto' }}>
              <Table size="small" stickyHeader sx={{ minWidth: 1200 }}>
                <TableHead><TableRow>{columns.map((column) => <TableCell key={column}>{columnLabel(column)}</TableCell>)}</TableRow></TableHead>
                <TableBody>
                  {resultPage?.items.map((row, index) => (
                    <TableRow hover key={`${row.human_gene_id ?? row.gene_id ?? index}-${row.mouse_gene_id ?? ''}`}>
                      {columns.map((column) => <TableCell key={column} sx={{ whiteSpace: 'nowrap' }}>{row[column] || '—'}</TableCell>)}
                    </TableRow>
                  ))}
                  {resultPage && !resultPage.items.length && (
                    <TableRow><TableCell colSpan={Math.max(columns.length, 1)}>No rows are present in this result file.</TableCell></TableRow>
                  )}
                </TableBody>
              </Table>
            </TableContainer>
            {resultPage && <TablePagination component="div" count={resultPage.total} page={page} rowsPerPage={PAGE_SIZE}
              rowsPerPageOptions={[PAGE_SIZE]} onPageChange={(_, nextPage) => setPage(nextPage)} />}
          </Paper>
        </>
      )}
    </Box>
  )
}
