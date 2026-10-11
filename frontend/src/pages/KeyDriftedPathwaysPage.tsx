import { useState } from 'react'
import { useParams } from 'react-router-dom'
import {
  Alert, Box, Chip, LinearProgress, MenuItem, Paper, Table, TableBody,
  TableCell, TableContainer, TableHead, TablePagination, TableRow, TextField, Typography,
} from '@mui/material'
import { useQuery } from '@tanstack/react-query'
import { phase5Api } from '@/api/client'
import { Page, RunHeader, RunPicker } from '@/pages/analysis/shared'
import { useProjectStore } from '@/store/projectStore'

type ResultRow = Record<string, string | number | boolean | null>
type Summary = { stages?: { pathways?: { key_drifted_pathway_count?: number; limitations?: string[] } } }

const PAGE_SIZE = 50
const GENE_SET_OPTIONS = [
  ['significant_deg', 'Significant DEGs'],
  ['upregulated_deg', 'Upregulated DEGs'],
  ['downregulated_deg', 'Downregulated DEGs'],
  ['drifted_genes', 'Drifted genes'],
  ['interaction_loss_genes', 'Genes with lost interactions'],
  ['interaction_gain_genes', 'Genes with gained interactions'],
  ['hub_human_cancer', 'Human cancer hub genes'],
  ['hub_mouse_cancer', 'Mouse cancer hub genes'],
  ['hub_human_healthy', 'Human healthy hub genes'],
  ['hub_mouse_healthy', 'Mouse healthy hub genes'],
]
const COLUMNS: Array<[string, string]> = [
  ['pathway_name', 'Pathway'],
  ['database', 'Database'],
  ['human_gene_set_key', 'Human input'],
  ['mouse_gene_set_key', 'Mouse input'],
  ['pathway_presence', 'ORA evidence'],
  ['human_fdr', 'Human FDR'],
  ['mouse_fdr', 'Mouse FDR'],
  ['pathway_drift_score', 'Within-pathway edge divergence'],
  ['conserved_ortholog_count', 'Conserved orthologs'],
  ['human_unpaired_pathway_member_count', 'Unpaired human members'],
  ['mouse_unpaired_pathway_member_count', 'Unpaired mouse members'],
  ['conserved_edge_count', 'Conserved edges'],
  ['lost_edge_count', 'Lost mapped edges'],
  ['gained_edge_count', 'Gained mapped edges'],
  ['module_preservation_jaccard', 'Best module Jaccard'],
]

function displayValue(value: ResultRow[string]): string {
  if (value == null || value === '') return '—'
  if (typeof value === 'number') {
    return value < 0.001 && value > 0 ? value.toExponential(2) : value.toLocaleString(undefined, { maximumFractionDigits: 4 })
  }
  return String(value)
}

export default function KeyDriftedPathwaysPage() {
  const { runId: routeRunId } = useParams<{ runId: string }>()
  const currentRunId = useProjectStore((state) => state.currentRunId)
  const runId = routeRunId ?? currentRunId ?? undefined
  const [geneSetKey, setGeneSetKey] = useState('significant_deg')
  const [page, setPage] = useState(0)

  const { data: summary, isLoading: summaryLoading, isError: summaryError } = useQuery({
    queryKey: ['phase5-summary', runId],
    queryFn: () => phase5Api.summary(runId!).then((response) => response.data as Summary),
    enabled: !!runId,
  })
  const { data: results, isLoading, isError } = useQuery({
    queryKey: ['phase5-key-drifted-pathways', runId, geneSetKey, page],
    queryFn: () => phase5Api.table(runId!, 'key-drifted-pathways', PAGE_SIZE, page * PAGE_SIZE, {
      gene_set_key: geneSetKey,
    }).then((response) => response.data as Page<ResultRow>),
    enabled: !!runId,
  })

  if (!runId) return <RunPicker />
  const pathwaySummary = summary?.stages?.pathways

  return (
    <Box sx={{ maxWidth: 1600, mx: 'auto' }}>
      <RunHeader runId={runId} view="key-drifted-pathways" title="KEY DRIFTED PATHWAYS"
        subtitle="Pathway enrichment interpreted alongside ortholog-mapped network and module evidence." />
      {(summaryLoading || isLoading) && <LinearProgress sx={{ mb: 2 }} />}
      {(summaryError || isError) && <Alert severity="error" sx={{ mb: 2 }}>Could not load pathway drift results for this run.</Alert>}
      <Alert severity="warning" sx={{ mb: 2 }}>
        A pathway is listed only when at least one species has significant local ORA and its measurable within-pathway ortholog-mapped edge set differs. Edge divergence is a structural comparison, not proof of biological loss. Human and mouse network densities differ substantially, and mouse DEG evidence is from independent studies.
      </Alert>
      <Alert severity="info" sx={{ mb: 2 }}>
        Unpaired pathway-member counts mean curated members without a retained one-to-one ortholog in the corresponding species' same pathway; they do not indicate biological gene loss.
      </Alert>
      <Paper variant="outlined" sx={{ p: 2, mb: 2 }}>
        <TextField select size="small" label="Input gene set" value={geneSetKey} onChange={(event) => {
          setGeneSetKey(event.target.value)
          setPage(0)
        }} sx={{ minWidth: 340 }}>
          {GENE_SET_OPTIONS.map(([key, label]) => <MenuItem key={key} value={key}>{label}</MenuItem>)}
        </TextField>
        <Chip sx={{ ml: 1.5 }} size="small" label={`${results?.total ?? pathwaySummary?.key_drifted_pathway_count ?? 0} matching key drifted pathways`} />
      </Paper>
      {results && (
        <Paper variant="outlined">
          <TableContainer sx={{ maxHeight: 720, overflowX: 'auto' }}>
            <Table size="small" stickyHeader sx={{ minWidth: 1850 }}>
              <TableHead><TableRow>{COLUMNS.map(([, label]) => <TableCell key={label}>{label}</TableCell>)}</TableRow></TableHead>
              <TableBody>
                {results.items.map((row, index) => <TableRow key={`${row.database}-${row.pathway_id}-${index}`} hover>
                  {COLUMNS.map(([key]) => <TableCell key={key} sx={{ whiteSpace: 'nowrap' }}>{displayValue(row[key])}</TableCell>)}
                </TableRow>)}
                {!results.items.length && <TableRow><TableCell colSpan={COLUMNS.length}>
                  No pathway meets the selected enrichment and measurable network-divergence criteria.
                </TableCell></TableRow>}
              </TableBody>
            </Table>
          </TableContainer>
          <TablePagination component="div" count={results.total} page={page} rowsPerPage={PAGE_SIZE}
            rowsPerPageOptions={[PAGE_SIZE]} onPageChange={(_, nextPage) => setPage(nextPage)} />
        </Paper>
      )}
      {pathwaySummary?.limitations?.map((limitation) => (
        <Typography key={limitation} variant="caption" display="block" color="text.secondary" sx={{ mt: 1 }}>
          {limitation}
        </Typography>
      ))}
    </Box>
  )
}
