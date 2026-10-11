import { useEffect, useMemo, useState } from 'react'
import { Link as RouterLink, useParams } from 'react-router-dom'
import {
  Alert, Box, Button, Chip, LinearProgress, MenuItem, Paper, Stack,
  Tab, Table, TableBody, TableCell, TableContainer, TableHead, TablePagination,
  TableRow, Tabs, TextField, Typography,
} from '@mui/material'
import { useQuery } from '@tanstack/react-query'
import { phase5Api } from '@/api/client'
import { Page, RunHeader, RunPicker } from '@/pages/analysis/shared'
import { useProjectStore } from '@/store/projectStore'

type ResultRow = Record<string, string | number | boolean | null>
type GeneSetOption = { species: string; gene_set_key: string; gene_set_label: string; gene_count: number }
type PathwaySummary = {
  status: string
  reason?: string
  significant_pathway_counts?: Record<string, number>
  limitations?: string[]
}

const PAGE_SIZE = 50
const RESULT_TABS = [
  { key: 'pathway-enrichment', label: 'Enrichment results' },
  { key: 'pathway-gene-sets', label: 'Gene set members' },
  { key: 'pathway-comparisons', label: 'Pathway comparisons' },
] as const
type PathwayResultName = typeof RESULT_TABS[number]['key']
const COLUMNS: Record<PathwayResultName, Array<[string, string]>> = {
  'pathway-enrichment': [
    ['species', 'Species'],
    ['gene_set_key', 'Gene set key'],
    ['gene_set_label', 'Gene set'],
    ['database', 'Database'],
    ['pathway_id', 'Pathway ID'],
    ['pathway_name', 'Pathway'],
    ['method', 'Method'],
    ['input_gene_count', 'Input genes'],
    ['background_gene_count', 'Expressed background'],
    ['pathway_gene_count', 'Pathway genes'],
    ['overlap_gene_count', 'Overlap'],
    ['overlapping_gene_ids', 'Overlapping gene IDs'],
    ['overlapping_gene_symbols', 'Overlapping genes'],
    ['enrichment_ratio', 'Enrichment ratio'],
    ['p_value', 'P-value'],
    ['adjusted_p_value', 'Adjusted p-value'],
    ['fdr_threshold', 'FDR threshold'],
    ['source_version', 'Source version'],
  ],
  'pathway-gene-sets': [
    ['species', 'Species'],
    ['gene_set_key', 'Gene set key'],
    ['gene_set_label', 'Gene set'],
    ['gene_id', 'Gene ID'],
    ['gene_symbol', 'Gene symbol'],
    ['source_artifact', 'Source'],
  ],
  'pathway-comparisons': [
    ['database', 'Database'],
    ['pathway_name', 'Pathway'],
    ['pathway_id', 'Pathway ID'],
    ['human_gene_set_key', 'Human input'],
    ['mouse_gene_set_key', 'Mouse input'],
    ['network_state', 'Network state'],
    ['pathway_presence', 'ORA evidence'],
    ['human_fdr', 'Human FDR'],
    ['mouse_fdr', 'Mouse FDR'],
    ['pathway_drift_score', 'Edge divergence'],
    ['gene_membership_drift_score', 'Membership divergence'],
    ['conserved_ortholog_count', 'Conserved orthologs'],
    ['human_unpaired_pathway_member_count', 'Unpaired human members'],
    ['mouse_unpaired_pathway_member_count', 'Unpaired mouse members'],
    ['conserved_edge_count', 'Conserved edges'],
    ['lost_edge_count', 'Lost edges'],
    ['gained_edge_count', 'Gained edges'],
    ['mapped_edge_union_count', 'Mapped edge union'],
    ['human_mean_degree', 'Human mean degree'],
    ['mouse_mean_degree', 'Mouse mean degree'],
    ['module_preservation_jaccard', 'Module preservation'],
    ['best_matching_module_pair', 'Best module pair'],
    ['key_drifted_pathway', 'Key drifted'],
    ['ranking_reason', 'Ranking reason'],
    ['network_density_limitation', 'Network limitation'],
  ],
}

function displayValue(value: ResultRow[string]): string {
  if (value == null || value === '') return '—'
  if (typeof value === 'number') {
    return value < 0.001 && value > 0 ? value.toExponential(2) : value.toLocaleString(undefined, { maximumFractionDigits: 4 })
  }
  return String(value)
}

export default function PathwaysPage() {
  const { runId: routeRunId } = useParams<{ runId: string }>()
  const currentRunId = useProjectStore((state) => state.currentRunId)
  const runId = routeRunId ?? currentRunId ?? undefined
  const [species, setSpecies] = useState<'all' | 'human' | 'mouse'>('all')
  const [geneSetKey, setGeneSetKey] = useState('all')
  const [database, setDatabase] = useState('all')
  const [significantOnly, setSignificantOnly] = useState(false)
  const [page, setPage] = useState(0)
  const [activeTab, setActiveTab] = useState<PathwayResultName>('pathway-enrichment')

  const { data: summary, isLoading: summaryLoading, isError: summaryError } = useQuery({
    queryKey: ['phase5-summary', runId],
    queryFn: () => phase5Api.summary(runId!).then((response) => response.data as {
      stages?: { pathways?: PathwaySummary }
    }),
    enabled: !!runId,
  })
  const { data: geneSets = [], isLoading: geneSetsLoading, isError: geneSetsError } = useQuery({
    queryKey: ['phase5-pathway-gene-sets', runId, species],
    queryFn: () => phase5Api.pathwayGeneSets(runId!, species === 'all' ? undefined : species)
      .then((response) => response.data as GeneSetOption[]),
    enabled: !!runId,
  })
  const availableDatabases = useMemo(() => {
    const values = new Set<string>(['GO-BP', 'GO-MF', 'GO-CC', 'Reactome', 'WikiPathways'])
    return [...values]
  }, [])
  const selectedGeneSet = geneSets.find((item) => item.gene_set_key === geneSetKey)
  const { data: results, isLoading, isError } = useQuery({
    queryKey: ['phase5-pathway-results', runId, activeTab, species, geneSetKey, database, significantOnly, page],
    queryFn: () => phase5Api.table(runId!, activeTab, PAGE_SIZE, page * PAGE_SIZE, {
      species: species === 'all' || activeTab === 'pathway-comparisons' ? undefined : species,
      gene_set_key: geneSetKey === 'all' ? undefined : geneSetKey,
      database: activeTab === 'pathway-gene-sets' || database === 'all' ? undefined : database,
      significant_only: activeTab !== 'pathway-gene-sets' && significantOnly,
    }).then((response) => response.data as Page<ResultRow>),
    enabled: !!runId,
  })

  useEffect(() => {
    if (geneSetKey !== 'all' && geneSets.length && !geneSets.some((item) => item.gene_set_key === geneSetKey)) {
      setGeneSetKey(geneSets[0].gene_set_key)
      setPage(0)
    }
  }, [geneSetKey, geneSets])

  if (!runId) return <RunPicker />
  const pathwaySummary = summary?.stages?.pathways
  const columns = COLUMNS[activeTab]
  const emptyMessage = activeTab === 'pathway-gene-sets'
      ? 'No gene-set members match the selected filters.'
      : activeTab === 'pathway-comparisons'
        ? 'No pathway comparisons match the selected filters.'
        : 'No overlapping pathway terms match the selected filters.'

  return (
    <Box sx={{ maxWidth: 1500, mx: 'auto' }}>
      <RunHeader runId={runId} view="pathways" title="PATHWAY ENRICHMENT"
        subtitle="Local, run-scoped GO, Reactome, and species-specific WikiPathways results." />
      {(summaryLoading || geneSetsLoading || isLoading) && <LinearProgress sx={{ mb: 2 }} />}
      {(summaryError || geneSetsError || isError) && (
        <Alert severity="error" sx={{ mb: 2 }}>Could not load pathway results for this analysis run.</Alert>
      )}
      {pathwaySummary?.status === 'UNAVAILABLE' && (
        <Alert severity="warning" sx={{ mb: 2 }}>{pathwaySummary.reason ?? 'Local pathway references are unavailable.'}</Alert>
      )}
      <Alert severity="info" sx={{ mb: 2 }}>
        Gene IDs are mapped and tested locally against versioned references; no identifiers are uploaded. Human and mouse libraries are kept separate. Mouse differential-expression results are from an independent-study exploratory comparison, not matched replication.
      </Alert>
      <Paper variant="outlined" sx={{ p: 2, mb: 2 }}>
        <Stack direction={{ xs: 'column', md: 'row' }} spacing={1.5}>
          <TextField select size="small" label="Species" value={species} onChange={(event) => {
            setSpecies(event.target.value as 'all' | 'human' | 'mouse')
            setPage(0)
          }} disabled={activeTab === 'pathway-comparisons'} sx={{ minWidth: 150 }}>
            <MenuItem value="all">All species</MenuItem>
            <MenuItem value="human">Human</MenuItem>
            <MenuItem value="mouse">Mouse</MenuItem>
          </TextField>
          <TextField select size="small" label="Gene set" value={geneSetKey} onChange={(event) => {
            setGeneSetKey(event.target.value)
            setPage(0)
          }} sx={{ minWidth: 260, flex: 1 }}>
            <MenuItem value="all">All gene sets</MenuItem>
            {geneSets.map((item) => (
              <MenuItem key={`${item.species}-${item.gene_set_key}`} value={item.gene_set_key}>
                {item.gene_set_label} · {item.species} · {item.gene_count.toLocaleString()} genes
              </MenuItem>
            ))}
          </TextField>
          <TextField select size="small" label="Database" value={database} disabled={activeTab === 'pathway-gene-sets'} onChange={(event) => {
            setDatabase(event.target.value)
            setPage(0)
          }} sx={{ minWidth: 180 }}>
            <MenuItem value="all">All databases</MenuItem>
            {availableDatabases.map((name) => <MenuItem key={name} value={name}>{name}</MenuItem>)}
          </TextField>
          <TextField select size="small" label="Significance" value={significantOnly ? 'significant' : 'all'} disabled={activeTab === 'pathway-gene-sets'} onChange={(event) => {
            setSignificantOnly(event.target.value === 'significant')
            setPage(0)
          }} sx={{ minWidth: 180 }}>
            <MenuItem value="significant">FDR ≤ 0.05</MenuItem>
            <MenuItem value="all">All overlapping terms</MenuItem>
          </TextField>
        </Stack>
        <Stack direction="row" spacing={1} alignItems="center" sx={{ mt: 1.5 }}>
          {activeTab === 'pathway-enrichment' && (
            <Chip size="small" variant="outlined" label={`${results?.total.toLocaleString() ?? '—'} saved enrichment rows`} />
          )}
          <Button component={RouterLink} to={`/runs/${runId}/key-drifted-pathways`} size="small">
            View cross-species pathway drift
          </Button>
        </Stack>
      </Paper>

      {activeTab === 'pathway-gene-sets' && !geneSetsLoading && !geneSets.length && pathwaySummary?.status !== 'UNAVAILABLE' && (
        <Alert severity="info">No eligible gene-set inputs are available in this run.</Alert>
      )}
      <Paper variant="outlined">
        <Tabs value={activeTab} onChange={(_, value: PathwayResultName) => {
          setActiveTab(value)
          setPage(0)
        }} variant="scrollable" scrollButtons="auto">
          {RESULT_TABS.map(({ key, label }) => <Tab key={key} value={key} label={label} />)}
        </Tabs>
        <Box sx={{ p: 2, pb: 0 }}>
          <Typography variant="subtitle1" fontWeight={700}>
            {activeTab === 'pathway-gene-sets'
              ? `Gene set members · ${selectedGeneSet?.gene_set_label ?? 'All gene sets'} · ${species}`
              : activeTab === 'pathway-comparisons'
                ? `Pathway comparisons · ${selectedGeneSet?.gene_set_label ?? 'All gene sets'}`
                : `${selectedGeneSet?.gene_set_label ?? 'All enrichment results'} · ${species}`}
          </Typography>
          <Typography variant="caption" color="text.secondary">
            {activeTab === 'pathway-enrichment'
              ? 'The background is the species-specific set of tested genes that map to each database.'
              : activeTab === 'pathway-gene-sets'
                  ? 'Run-scoped gene members used as input to pathway analysis.'
                  : activeTab === 'pathway-comparisons'
                    ? 'Run-scoped pathway enrichment and ortholog-mapped network comparison evidence.'
                    : 'Showing saved enrichment CSV rows with no filters by default.'}
          </Typography>
        </Box>
        <TableContainer sx={{ maxHeight: 700, overflowX: 'auto' }}>
          <Table size="small" stickyHeader sx={{ minWidth: activeTab === 'pathway-comparisons' ? 2200 : 1250 }}>
            <TableHead><TableRow>{columns.map(([, label]) => <TableCell key={label}>{label}</TableCell>)}</TableRow></TableHead>
            <TableBody>
              {results?.items.map((row, index) => (
                <TableRow key={`${row.database}-${row.pathway_id}-${row.gene_id}-${index}`} hover>
                  {columns.map(([key]) => (
                    <TableCell key={key} sx={{ whiteSpace: 'nowrap' }}>
                      {displayValue(row[key])}
                    </TableCell>
                  ))}
                </TableRow>
              ))}
              {results && !results.items.length && (
                <TableRow><TableCell colSpan={columns.length}>{emptyMessage}</TableCell></TableRow>
              )}
            </TableBody>
          </Table>
        </TableContainer>
        {results && <TablePagination component="div" count={results.total} page={page} rowsPerPage={PAGE_SIZE}
          rowsPerPageOptions={[PAGE_SIZE]} onPageChange={(_, nextPage) => setPage(nextPage)} />}
      </Paper>
      {pathwaySummary?.limitations?.map((limitation) => (
        <Typography key={limitation} variant="caption" display="block" color="text.secondary" sx={{ mt: 1 }}>
          {limitation}
        </Typography>
      ))}
    </Box>
  )
}
