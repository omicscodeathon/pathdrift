import { useEffect, useState } from 'react'
import { Alert, Box, Chip, LinearProgress, Paper, Stack, Table, TableBody, TableCell, TableContainer, TableHead, TablePagination, TableRow, Typography } from '@mui/material'
import { useQuery } from '@tanstack/react-query'
import { phase4Api } from '@/api/client'
import { RunHeader, useRunId } from '@/pages/analysis/shared'

type OrthologySummary = {
  total_orthology_mappings?: number
  unique_human_genes_mapped?: number
  unique_mouse_genes_mapped?: number
  one_to_one_mappings?: number
  one_to_many_mappings?: number
  many_to_one_mappings?: number
  many_to_many_mappings?: number
  primary_one_to_one_mappings?: number
  human_network_genes_with_orthologs?: number
  mouse_network_genes_with_orthologs?: number
  source?: string
  source_version?: string
}

type OrthologyPageData = {
  items: Array<{
    human_ensembl_id: string
    mouse_ensembl_id: string
    human_symbol: string | null
    mouse_symbol: string | null
    orthology_type: string
    confidence: number | null
    source: string
    source_version: string
    is_primary: boolean | null
  }>
  total: number
}

const PAGE_SIZE = 50

function formatCount(value: number | undefined) {
  return value == null ? '—' : value.toLocaleString()
}

export default function OrthologyPage() {
  const runId = useRunId()
  const [page, setPage] = useState(0)
  useEffect(() => setPage(0), [runId])
  const { data: summary, isLoading: summaryLoading, isError: summaryError } = useQuery({
    queryKey: ['phase4-orthology-summary', runId],
    queryFn: () => phase4Api.orthologySummary(runId!).then((response) => response.data as OrthologySummary),
    enabled: !!runId,
  })
  const { data, isLoading, isError } = useQuery({
    queryKey: ['phase4-orthology-mappings', runId, page],
    queryFn: () => phase4Api.orthology(runId!, PAGE_SIZE, page * PAGE_SIZE).then((response) => response.data as OrthologyPageData),
    enabled: !!runId,
  })

  return (
    <Box>
      <RunHeader runId={runId ?? ''} view="orthology" title="Orthology" subtitle="Saved human–mouse Ensembl Compara mappings used by this run" />
      {!summaryLoading && !summaryError && !summary && <Alert severity="info" sx={{ mb: 2 }}>No orthology results are saved for this run.</Alert>}
      {summaryLoading && <LinearProgress sx={{ mb: 2 }} />}
      {summaryError && <Alert severity="error" sx={{ mb: 2 }}>Could not load saved orthology summary.</Alert>}
      {summary && (
        <>
          <Box sx={{ display: 'grid', gridTemplateColumns: { xs: 'repeat(2, 1fr)', md: 'repeat(4, 1fr)' }, gap: 1.5, mb: 2 }}>
            {[
              ['Mappings', summary.total_orthology_mappings],
              ['One-to-one', summary.one_to_one_mappings],
              ['Primary one-to-one', summary.primary_one_to_one_mappings],
              ['Network orthologs (human)', summary.human_network_genes_with_orthologs],
              ['Network orthologs (mouse)', summary.mouse_network_genes_with_orthologs],
              ['Unique human genes', summary.unique_human_genes_mapped],
              ['Unique mouse genes', summary.unique_mouse_genes_mapped],
            ].map(([label, value]) => (
              <Paper key={String(label)} variant="outlined" sx={{ p: 1.5 }}>
                <Typography variant="h5" fontWeight={800}>{formatCount(value as number | undefined)}</Typography>
                <Typography variant="caption" color="text.secondary">{label}</Typography>
              </Paper>
            ))}
          </Box>
          <Stack direction="row" spacing={1} sx={{ mb: 1.5 }} useFlexGap flexWrap="wrap">
            {summary.source && <Chip size="small" label={`Source: ${summary.source}`} />}
            {summary.source_version && <Chip size="small" variant="outlined" label={summary.source_version} />}
            {summary.one_to_many_mappings != null && <Chip size="small" variant="outlined" label={`One-to-many: ${summary.one_to_many_mappings.toLocaleString()}`} />}
            {summary.many_to_one_mappings != null && <Chip size="small" variant="outlined" label={`Many-to-one: ${summary.many_to_one_mappings.toLocaleString()}`} />}
            {summary.many_to_many_mappings != null && <Chip size="small" variant="outlined" label={`Many-to-many: ${summary.many_to_many_mappings.toLocaleString()}`} />}
          </Stack>
          {isLoading && <LinearProgress sx={{ mb: 1 }} />}
          {isError && <Alert severity="error" sx={{ mb: 1 }}>Could not load saved orthology mappings.</Alert>}
          <TableContainer component={Paper} variant="outlined">
            <Table size="small">
              <TableHead><TableRow>
                {['Human gene', 'Human symbol', 'Mouse gene', 'Mouse symbol', 'Relationship', 'Confidence', 'Primary'].map((header) => <TableCell key={header}>{header}</TableCell>)}
              </TableRow></TableHead>
              <TableBody>
                {(data?.items ?? []).map((mapping) => (
                  <TableRow key={`${mapping.human_ensembl_id}-${mapping.mouse_ensembl_id}`}>
                    <TableCell sx={{ fontFamily: 'monospace' }}>{mapping.human_ensembl_id}</TableCell>
                    <TableCell>{mapping.human_symbol || 'Symbol unavailable'}</TableCell>
                    <TableCell sx={{ fontFamily: 'monospace' }}>{mapping.mouse_ensembl_id}</TableCell>
                    <TableCell>{mapping.mouse_symbol || 'Symbol unavailable'}</TableCell>
                    <TableCell>{mapping.orthology_type}</TableCell>
                    <TableCell>{mapping.confidence ?? '—'}</TableCell>
                    <TableCell>{mapping.is_primary == null ? '—' : mapping.is_primary ? 'Yes' : 'No'}</TableCell>
                  </TableRow>
                ))}
                {!isLoading && !isError && !data?.total && <TableRow><TableCell colSpan={7}>No orthology mappings are available for this run.</TableCell></TableRow>}
              </TableBody>
            </Table>
          </TableContainer>
          <TablePagination component="div" count={data?.total ?? 0} page={page} onPageChange={(_, next) => setPage(next)} rowsPerPage={PAGE_SIZE} onRowsPerPageChange={() => undefined} rowsPerPageOptions={[PAGE_SIZE]} />
        </>
      )}
    </Box>
  )
}
