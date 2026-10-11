import { useState } from 'react'
import {
  Alert, Box, Chip, LinearProgress, Paper, Stack, Table, TableBody,
  TableCell, TableContainer, TableHead, TablePagination, TableRow, Typography,
} from '@mui/material'
import { useQuery } from '@tanstack/react-query'
import { useParams } from 'react-router-dom'
import { phase5Api } from '@/api/client'
import { RunHeader } from '@/pages/analysis/shared'

type Biomarker = Record<string, string | null>
type Page = { items: Biomarker[]; total: number; limit: number; offset: number }
type Phase5Summary = {
  status: string
  stages: Record<string, {
    status: string
    candidate_count?: number
    reason?: string
    limitations?: string[]
    selection_basis?: string
    clinical_validation?: boolean
  }>
}

const COLUMNS: Array<{ key: string; title: string }> = [
  { key: 'gene_id', title: 'Human gene ID' },
  { key: 'gene_symbol', title: 'Symbol' },
  { key: 'log2fc', title: 'log2FC' },
  { key: 'adjusted_p_value', title: 'Adjusted p-value' },
  { key: 'direction', title: 'Direction' },
  { key: 'candidate_status', title: 'Evidence status' },
  { key: 'evidence_categories', title: 'Evidence categories' },
  { key: 'hub_supported', title: 'Multi-metric hub' },
  { key: 'hub_score', title: 'Within-module hub score' },
  { key: 'intramodular_connectivity', title: 'Intramodular connectivity' },
  { key: 'network_degree', title: 'Network degree' },
  { key: 'one_to_one_mouse_ortholog_id', title: 'Mouse ortholog' },
  { key: 'cross_species_network_drift', title: 'Network drift' },
  { key: 'cross_species_drift_category', title: 'Drift category' },
  { key: 'lost_interaction_count', title: 'Lost interactions' },
  { key: 'gained_interaction_count', title: 'Gained interactions' },
  { key: 'enriched_pathway_names', title: 'Significant DEG pathways' },
  { key: 'key_drifted_pathway_names', title: 'Key drifted pathways' },
  { key: 'morphology_association_status', title: 'Morphology association' },
]

export default function BiomarkersPage() {
  const { runId } = useParams<{ runId: string }>()
  const [page, setPage] = useState(0)
  const pageSize = 50
  const { data: summary, isLoading: summaryLoading, isError: summaryError } = useQuery({
    queryKey: ['phase5-summary', runId],
    queryFn: () => phase5Api.summary(runId!).then((response) => response.data as Phase5Summary),
    enabled: !!runId,
  })
  const { data: candidates, isLoading: candidatesLoading, isError: candidatesError } = useQuery({
    queryKey: ['phase5-biomarkers', runId, page],
    queryFn: () => phase5Api.table(runId!, 'biomarkers', pageSize, page * pageSize).then((response) => response.data as Page),
    enabled: !!runId,
  })
  const unavailable = ['ppi', 'pathways', 'morphology']
    .map((key) => [key, summary?.stages[key]] as const)
    .filter(([, stage]) => stage?.status === 'UNAVAILABLE')

  return (
    <Box sx={{ maxWidth: 1400, mx: 'auto' }}>
      <RunHeader runId={runId ?? ''} view="biomarkers" title="BIOMARKER CANDIDATES"
        subtitle="Research-only candidates from saved human DEG results, with observed network and orthology support." />
      {!runId && <Alert severity="info">Choose a saved analysis run to review its biomarker candidates.</Alert>}
      {!!runId && (summaryLoading || candidatesLoading) && <LinearProgress sx={{ mb: 2 }} />}
      {!!runId && (summaryError || candidatesError) && (
        <Alert severity="warning" sx={{ mb: 2 }}>
          Phase 5 candidate results are not available for this run yet. Generate them with <code>pathdrift phase5 --run-id {runId}</code>, then refresh.
        </Alert>
      )}
      {summary && candidates && (
        <>
          <Alert severity="warning" sx={{ mb: 2 }}>
            These are research candidates, not clinically validated biomarkers. Each must meet the saved human DEG thresholds and have additional evidence, including measured network support (multi-metric hub, drift, or lost/gained interactions). Network drift and edge changes are related evidence, not independent validation. No opaque composite biomarker score is used.
          </Alert>
          <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap" sx={{ mb: 2 }}>
            <Chip label={`${candidates.total.toLocaleString()} candidates`} />
            <Chip variant="outlined" label={`Phase 5: ${summary.status}`} />
            <Chip color="default" variant="outlined" label="Clinical validation: not performed" />
          </Stack>
          {unavailable.map(([stage, value]) => (
            <Alert key={stage} severity="info" sx={{ mb: 1 }}>
              {stage.toUpperCase()} evidence unavailable: {value?.reason}
            </Alert>
          ))}
          <Paper variant="outlined">
            <TableContainer>
              <Table size="small" stickyHeader>
                <TableHead><TableRow>{COLUMNS.map((column) => <TableCell key={column.key}>{column.title}</TableCell>)}</TableRow></TableHead>
                <TableBody>
                  {candidates.items.map((candidate) => (
                    <TableRow key={candidate.gene_id} hover>
                      {COLUMNS.map((column) => <TableCell key={column.key}>{candidate[column.key] || '—'}</TableCell>)}
                    </TableRow>
                  ))}
                  {!candidates.items.length && <TableRow><TableCell colSpan={COLUMNS.length}>No candidates are present in this run.</TableCell></TableRow>}
                </TableBody>
              </Table>
            </TableContainer>
            <TablePagination component="div" count={candidates.total} page={page} rowsPerPage={pageSize}
              rowsPerPageOptions={[pageSize]} onPageChange={(_, nextPage) => setPage(nextPage)} />
          </Paper>
        </>
      )}
    </Box>
  )
}
