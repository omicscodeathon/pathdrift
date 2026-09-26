import { Box, Typography, Alert, Paper, Grid, Button, TextField, MenuItem, CircularProgress, Table, TableBody, TableCell, TableHead, TableRow, TableContainer, Chip, LinearProgress } from '@mui/material'
import { useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { useSnackbar } from 'notistack'
import { pathwayApi } from '@/api/client'

const GENE_SETS_HUMAN = [
  'GO_Biological_Process_2023', 'GO_Molecular_Function_2023',
  'KEGG_2021_Human', 'Reactome_2022', 'MSigDB_Hallmark_2020',
]
const GENE_SETS_MOUSE = [
  'GO_Biological_Process_2023', 'GO_Molecular_Function_2023',
  'KEGG_2019_Mouse', 'Reactome_2022',
]

export default function PathwaysPage() {
  const { enqueueSnackbar } = useSnackbar()
  const [config, setConfig] = useState({
    analysis_id: '', gene_set: 'GO_Biological_Process_2023',
    source: 'drift', source_id: '', species: 'human', fdr_threshold: 0.05,
  })
  const [pwId, setPwId] = useState('')
  const [loadedId, setLoadedId] = useState('')

  const { data: pwResult } = useQuery({
    queryKey: ['pw-result', loadedId],
    queryFn: () => pathwayApi.get(loadedId).then(r => r.data),
    enabled: !!loadedId,
    refetchInterval: (query) => {
      const status = (query.state.data as { status?: string } | undefined)?.status
      return status === 'running' ? 5000 : false
    },
  })

  const { data: terms, isLoading: termsLoading } = useQuery({
    queryKey: ['pw-terms', loadedId],
    queryFn: () => pathwayApi.getTerms(loadedId).then(r => r.data as Array<{ term: string; overlap: string; pvalue: number; padj: number; odds_ratio: number; genes: string; significant: boolean }>),
    enabled: !!loadedId && (pwResult as { status?: string })?.status === 'completed',
  })

  const runMutation = useMutation({
    mutationKey: ['pathways', 'run'],
    mutationFn: () => pathwayApi.run(config),
    onSuccess: () => enqueueSnackbar('Pathway analysis queued', { variant: 'info' }),
    onError: () => enqueueSnackbar('Failed to start pathway analysis', { variant: 'error' }),
  })

  const geneSets = config.species === 'human' ? GENE_SETS_HUMAN : GENE_SETS_MOUSE

  return (
    <Box>
      <Typography variant="h4" fontWeight={700} gutterBottom>Pathway Analysis</Typography>
      <Typography variant="body2" color="text.secondary" mb={2}>
        Over-representation analysis of drifting or differentially expressed genes.
        Results are computational predictions; they do not constitute validated clinical biomarkers.
      </Typography>

      <Alert severity="info" sx={{ mb: 3 }}>
        Gene identifiers must be converted to gene symbols before enrichment analysis.
        Unmapped Ensembl IDs will be excluded and reported in the logs.
      </Alert>

      <Paper sx={{ p: 3, mb: 3 }} variant="outlined">
        <Typography variant="h6" fontWeight={600} gutterBottom>Configure</Typography>
        <Grid container spacing={2} alignItems="flex-end">
          <Grid item xs={12} sm={3}>
            <TextField select label="Source" fullWidth size="small" value={config.source}
              onChange={e => setConfig(c => ({ ...c, source: e.target.value }))}>
              <MenuItem value="drift">Network Drift Genes</MenuItem>
              <MenuItem value="deg">Differentially Expressed Genes</MenuItem>
            </TextField>
          </Grid>
          <Grid item xs={12} sm={3}>
            <TextField label="Source ID (drift/DEG result ID)" fullWidth size="small" value={config.source_id}
              onChange={e => setConfig(c => ({ ...c, source_id: e.target.value }))} />
          </Grid>
          <Grid item xs={12} sm={2}>
            <TextField select label="Species" fullWidth size="small" value={config.species}
              onChange={e => setConfig(c => ({ ...c, species: e.target.value }))}>
              <MenuItem value="human">Human</MenuItem>
              <MenuItem value="mouse">Mouse</MenuItem>
            </TextField>
          </Grid>
          <Grid item xs={12} sm={4}>
            <TextField select label="Gene Set" fullWidth size="small" value={config.gene_set}
              onChange={e => setConfig(c => ({ ...c, gene_set: e.target.value }))}>
              {geneSets.map(gs => <MenuItem key={gs} value={gs}>{gs}</MenuItem>)}
            </TextField>
          </Grid>
          <Grid item xs={6} sm={2}>
            <TextField label="FDR Threshold" type="number" fullWidth size="small" value={config.fdr_threshold}
              onChange={e => setConfig(c => ({ ...c, fdr_threshold: parseFloat(e.target.value) }))} />
          </Grid>
          <Grid item xs={6} sm={2}>
            <Button variant="contained" fullWidth disabled={runMutation.isPending || !config.source_id}
              onClick={() => runMutation.mutate()}>
              {runMutation.isPending ? <CircularProgress size={20} color="inherit" /> : 'Run ORA'}
            </Button>
          </Grid>
        </Grid>
      </Paper>

      <Box sx={{ display: 'flex', gap: 2, mb: 3 }}>
        <TextField label="Pathway Result ID" size="small" value={pwId} onChange={e => setPwId(e.target.value)} sx={{ flex: 1 }} />
        <Button variant="outlined" onClick={() => setLoadedId(pwId)} disabled={!pwId}>Load</Button>
      </Box>

      {termsLoading && <LinearProgress sx={{ mb: 2 }} />}

      {terms && terms.length > 0 && (
        <Paper variant="outlined">
          <Box sx={{ p: 2, borderBottom: '1px solid', borderColor: 'divider' }}>
            <Typography variant="subtitle1" fontWeight={600}>
              Enriched Pathways ({terms.filter(t => t.significant).length} significant)
            </Typography>
          </Box>
          <TableContainer sx={{ maxHeight: 500 }}>
            <Table size="small" stickyHeader>
              <TableHead>
                <TableRow sx={{ '& th': { fontWeight: 600 } }}>
                  <TableCell>Pathway Term</TableCell>
                  <TableCell align="right">Overlap</TableCell>
                  <TableCell align="right">adj. p-value</TableCell>
                  <TableCell align="right">Odds Ratio</TableCell>
                  <TableCell>Significance</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {terms.slice(0, 100).map((t, i) => (
                  <TableRow key={i} hover sx={{ bgcolor: t.significant ? undefined : 'action.hover' }}>
                    <TableCell sx={{ maxWidth: 350, fontSize: 12 }}>{t.term}</TableCell>
                    <TableCell align="right">{t.overlap}</TableCell>
                    <TableCell align="right">{t.padj?.toExponential(2)}</TableCell>
                    <TableCell align="right">{t.odds_ratio?.toFixed(2)}</TableCell>
                    <TableCell>
                      <Chip size="small" label={t.significant ? 'Significant' : 'NS'}
                        color={t.significant ? 'success' : 'default'} />
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>
        </Paper>
      )}

      {loadedId && !termsLoading && !terms?.length && (
        <Alert severity="info">No pathway results available. The analysis may still be running.</Alert>
      )}
    </Box>
  )
}
