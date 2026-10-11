import { useState } from 'react'
import { useParams } from 'react-router-dom'
import {
  Alert, Box, Chip, LinearProgress, Paper, Tab, Table, TableBody, TableCell,
  TableContainer, TableHead, TablePagination, TableRow, Tabs, Typography,
} from '@mui/material'
import { useQuery } from '@tanstack/react-query'
import { phase5Api } from '@/api/client'
import { Page, RunHeader, RunPicker } from '@/pages/analysis/shared'
import { useProjectStore } from '@/store/projectStore'

type ResultRow = Record<string, string | number | boolean | null>
type MorphologySummary = {
  status: string
  selected_human_sample_count?: number
  selected_human_tumor_sample_count?: number
  selected_human_control_sample_count?: number
  observed_pathology_fields?: string[]
  image_records?: number
  image_derived_features?: number
  mouse_pathology_status?: string
  gene_or_pathway_associations?: string
  association_reason?: string
  interpretation?: string
}
type Summary = { stages?: { morphology?: MorphologySummary } }

const PAGE_SIZE = 50
const VARIABLE_COLUMNS: Array<[string, string]> = [
  ['field', 'Clinical variable'],
  ['evidence_type', 'Evidence type'],
  ['tumor_sample_count', 'Tumor samples'],
  ['observed_sample_count', 'Observed'],
  ['missing_sample_count', 'Missing'],
  ['category_counts_json', 'Observed categories'],
]
const SAMPLE_COLUMNS: Array<[string, string]> = [
  ['sample_id', 'Sample'],
  ['disease_state', 'Condition'],
  ['sample_type', 'Sample type'],
  ['ajcc_pathologic_stage', 'AJCC stage'],
  ['primary_diagnosis', 'Primary diagnosis'],
  ['tumor_grade', 'Tumor grade'],
  ['morphology', 'ICD-O morphology'],
  ['age_at_index_years', 'Age at index'],
  ['sex_at_birth', 'Sex'],
]

function format(value: ResultRow[string]): string {
  if (value == null || value === '') return '—'
  if (typeof value === 'number') return value.toLocaleString()
  return String(value)
}

export default function MorphologyPage() {
  const { runId: routeRunId } = useParams<{ runId: string }>()
  const currentRunId = useProjectStore((state) => state.currentRunId)
  const runId = routeRunId ?? currentRunId ?? undefined
  const [tab, setTab] = useState(0)
  const [page, setPage] = useState(0)
  const tableName = tab === 0 ? 'phenotype-variables' : 'phenotype-samples'
  const columns = tab === 0 ? VARIABLE_COLUMNS : SAMPLE_COLUMNS

  const { data: summary, isLoading: summaryLoading, isError: summaryError } = useQuery({
    queryKey: ['phase5-summary', runId],
    queryFn: () => phase5Api.summary(runId!).then((response) => response.data as Summary),
    enabled: !!runId,
  })
  const { data: result, isLoading, isError } = useQuery({
    queryKey: ['phase5-morphology', runId, tableName, page],
    queryFn: () => phase5Api.table(runId!, tableName, PAGE_SIZE, page * PAGE_SIZE)
      .then((response) => response.data as Page<ResultRow>),
    enabled: !!runId,
  })

  if (!runId) return <RunPicker />
  const morphology = summary?.stages?.morphology

  return (
    <Box sx={{ maxWidth: 1500, mx: 'auto' }}>
      <RunHeader runId={runId} view="morphology" title="MORPHOLOGY & PHENOTYPES"
        subtitle="Run-linked clinical pathology metadata, kept separate from image-derived morphology." />
      {(summaryLoading || isLoading) && <LinearProgress sx={{ mb: 2 }} />}
      {(summaryError || isError) && <Alert severity="error" sx={{ mb: 2 }}>Could not load phenotype evidence for this analysis run.</Alert>}
      {morphology && (
        <>
          <Alert severity={morphology.status === 'DESCRIPTIVE_METADATA_ONLY' ? 'info' : 'warning'} sx={{ mb: 2 }}>
            {morphology.interpretation ?? morphology.association_reason ?? 'No morphology evidence is available.'}
          </Alert>
          <Paper variant="outlined" sx={{ p: 2, mb: 2 }}>
            <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1 }}>
              <Chip label={`${morphology.selected_human_tumor_sample_count ?? 0} linked human tumors`} />
              <Chip variant="outlined" label={`${morphology.selected_human_control_sample_count ?? 0} linked controls`} />
              <Chip variant="outlined" label={`${morphology.image_records ?? 0} pathology images`} />
              <Chip variant="outlined" label={`${morphology.image_derived_features ?? 0} image-derived features`} />
              <Chip variant="outlined" label={`Mouse pathology: ${morphology.mouse_pathology_status ?? 'unavailable'}`} />
              <Chip variant="outlined" label={`Molecular association: ${morphology.gene_or_pathway_associations ?? 'not calculated'}`} />
            </Box>
            {morphology.association_reason && (
              <Typography variant="body2" color="text.secondary" sx={{ mt: 1.5 }}>
                {morphology.association_reason}
              </Typography>
            )}
          </Paper>
        </>
      )}
      {!morphology && !summaryLoading && (
        <Alert severity="info" sx={{ mb: 2 }}>Generate Phase 5 for this run to create its linked phenotype metadata summary.</Alert>
      )}
      <Paper variant="outlined">
        <Tabs value={tab} onChange={(_, value: number) => { setTab(value); setPage(0) }}>
          <Tab label="Clinical variables" />
          <Tab label="Linked samples" />
        </Tabs>
        <TableContainer sx={{ maxHeight: 700, overflowX: 'auto' }}>
          <Table size="small" stickyHeader sx={{ minWidth: 1100 }}>
            <TableHead><TableRow>{columns.map(([, label]) => <TableCell key={label}>{label}</TableCell>)}</TableRow></TableHead>
            <TableBody>
              {result?.items.map((row, index) => <TableRow key={`${row.sample_id ?? row.field}-${index}`} hover>
                {columns.map(([key]) => <TableCell key={key} sx={{ whiteSpace: 'normal', minWidth: key === 'category_counts_json' ? 350 : undefined }}>
                  {format(row[key])}
                </TableCell>)}
              </TableRow>)}
              {result && !result.items.length && <TableRow><TableCell colSpan={columns.length}>
                No linked clinical pathology records were saved for this run.
              </TableCell></TableRow>}
            </TableBody>
          </Table>
        </TableContainer>
        {result && <TablePagination component="div" count={result.total} page={page} rowsPerPage={PAGE_SIZE}
          rowsPerPageOptions={[PAGE_SIZE]} onPageChange={(_, nextPage) => setPage(nextPage)} />}
      </Paper>
      <Alert severity="warning" sx={{ mt: 2 }}>
        The ICD-O morphology value and clinical diagnoses are source metadata, not measurements of tumor area, cell density, nuclear shape, tissue architecture, or necrosis. With the small linked tumor cohort and no validated paired image features, no gene- or pathway-level morphology association is claimed.
      </Alert>
    </Box>
  )
}
