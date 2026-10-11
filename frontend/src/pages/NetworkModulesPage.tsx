import { useEffect, useState } from 'react'
import {
  Alert, Box, Button, Chip, CircularProgress, Divider, Grid, LinearProgress,
  MenuItem, Paper, Stack, Table, TableBody, TableCell, TableContainer,
  TableHead, TableRow, TextField, Typography,
} from '@mui/material'
import { useMutation, useQuery } from '@tanstack/react-query'
import { networkApi } from '@/api/client'
import { useProjectStore } from '@/store/projectStore'

interface NetworkOption {
  id: string
  name: string
  species: 'human' | 'mouse'
  disease_state: string
  n_nodes: number | null
  n_edges: number | null
  status: string
}

interface NetworkModule {
  module_id: string
  size: number
  hub_genes: Array<{ gene_id: string; symbol: string | null; degree: number }>
}

interface ModuleListResponse {
  network_id: string
  module_count: number
  modules: NetworkModule[]
}

interface EnrichmentResponse {
  gene_set: string
  total_genes: number
  mapped_genes: number
  results: Array<{
    term: string
    overlap: string | null
    adjusted_pvalue: number | null
    odds_ratio: number | null
    genes: string | null
    significant: boolean
  }>
  message: string | null
}

const GENE_SETS: Record<'human' | 'mouse', string[]> = {
  human: [
    'GO_Biological_Process_2023', 'GO_Molecular_Function_2023',
    'GO_Cellular_Component_2023', 'KEGG_2021_Human', 'Reactome_2022',
    'MSigDB_Hallmark_2020',
  ],
  mouse: [
    'GO_Biological_Process_2023', 'GO_Molecular_Function_2023',
    'GO_Cellular_Component_2023', 'KEGG_2019_Mouse', 'Reactome_2022',
  ],
}

const MODULE_COLORS = ['#1677a8', '#be5a32', '#25856b', '#a04f7c', '#9a7b20', '#5364a5']

export default function NetworkModulesPage() {
  const { currentProjectId } = useProjectStore()
  const [networkId, setNetworkId] = useState('')
  const [moduleId, setModuleId] = useState('')
  const [geneSet, setGeneSet] = useState(GENE_SETS.human[0])

  const { data: networks = [], isLoading: networksLoading } = useQuery({
    queryKey: ['networks', currentProjectId],
    queryFn: () => currentProjectId
      ? networkApi.listForProject(currentProjectId).then((response) => response.data as NetworkOption[])
      : [],
    enabled: !!currentProjectId,
  })
  const completedNetworks = networks.filter((network) => network.status === 'completed')

  useEffect(() => {
    if (completedNetworks.some((network) => network.id === networkId)) return
    setNetworkId(completedNetworks[0]?.id ?? '')
  }, [completedNetworks, networkId])

  const selectedNetwork = completedNetworks.find((network) => network.id === networkId) ?? null
  const availableGeneSets = selectedNetwork ? GENE_SETS[selectedNetwork.species] : GENE_SETS.human

  useEffect(() => {
    if (!availableGeneSets.includes(geneSet)) setGeneSet(availableGeneSets[0])
  }, [availableGeneSets, geneSet])

  const { data: moduleData, isLoading: modulesLoading, isError: modulesError } = useQuery({
    queryKey: ['network-modules', networkId],
    queryFn: () => networkApi.getModules(networkId).then((response) => response.data as ModuleListResponse),
    enabled: !!networkId,
  })

  useEffect(() => {
    const modules = moduleData?.modules ?? []
    if (modules.length && !modules.some((module) => module.module_id === moduleId)) {
      setModuleId(modules[0].module_id)
    } else if (!modules.length && moduleId) {
      setModuleId('')
    }
  }, [moduleData, moduleId])

  const selectedModule = moduleData?.modules.find((module) => module.module_id === moduleId) ?? null
  const enrichmentMutation = useMutation({
    mutationKey: ['network-module-enrichment', networkId, moduleId, geneSet],
    mutationFn: () => networkApi.enrichModule(networkId, moduleId, geneSet).then((response) => response.data as EnrichmentResponse),
  })
  const enrichment = enrichmentMutation.data

  return (
    <Box sx={{ maxWidth: 1280, mx: 'auto' }}>
      <Stack direction={{ xs: 'column', sm: 'row' }} justifyContent="space-between" alignItems={{ xs: 'flex-start', sm: 'center' }} spacing={2} sx={{ mb: 3 }}>
        <Box>
          <Typography variant="h4" fontWeight={800}>NETWORK MODULES</Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
            Explore detected gene communities, their hubs, and functional enrichment.
          </Typography>
        </Box>
        <TextField
          select
          size="small"
          label="Completed network"
          value={networkId}
          onChange={(event) => { setNetworkId(event.target.value); setModuleId(''); enrichmentMutation.reset() }}
          disabled={!completedNetworks.length}
          sx={{ minWidth: { xs: '100%', sm: 320 } }}
        >
          {completedNetworks.map((network) => (
            <MenuItem key={network.id} value={network.id}>
              {network.name} · {network.species} · {network.disease_state}
            </MenuItem>
          ))}
        </TextField>
      </Stack>

      {!currentProjectId && <Alert severity="info">Select a project on Dashboard to browse its network modules.</Alert>}
      {currentProjectId && networksLoading && <LinearProgress sx={{ mb: 2 }} />}
      {currentProjectId && !networksLoading && !completedNetworks.length && (
        <Alert severity="info">Build and complete a gene network before exploring its modules.</Alert>
      )}
      {modulesError && <Alert severity="error" sx={{ mb: 2 }}>Could not load the selected network's module assignments.</Alert>}
      {modulesLoading && <LinearProgress sx={{ mb: 2 }} />}

      {!!moduleData && (
        <>
          <Stack direction={{ xs: 'column', sm: 'row' }} justifyContent="space-between" alignItems={{ xs: 'flex-start', sm: 'center' }} spacing={1} sx={{ mb: 1.5 }}>
            <Box>
              <Typography variant="h6" fontWeight={700}>Detected communities</Typography>
              <Typography variant="body2" color="text.secondary">
                {moduleData.module_count.toLocaleString()} modules · {selectedNetwork?.n_nodes?.toLocaleString() ?? '—'} network genes
              </Typography>
            </Box>
            <Chip size="small" variant="outlined" label={`${selectedNetwork?.species ?? ''} · ${selectedNetwork?.disease_state ?? ''}`} />
          </Stack>

          <Grid container spacing={1.5} sx={{ mb: 3 }}>
            {moduleData.modules.map((module, index) => {
              const active = module.module_id === moduleId
              const color = MODULE_COLORS[index % MODULE_COLORS.length]
              return (
                <Grid item xs={6} sm={4} md={3} lg={3} key={module.module_id}>
                  <Paper
                    component="button"
                    type="button"
                    variant="outlined"
                    onClick={() => { setModuleId(module.module_id); enrichmentMutation.reset() }}
                    sx={{
                      width: '100%',
                      minHeight: 122,
                      p: 1.75,
                      textAlign: 'left',
                      cursor: 'pointer',
                      borderTop: `3px solid ${color}`,
                      borderColor: active ? color : 'divider',
                      bgcolor: active ? `${color}0d` : 'background.paper',
                      '&:hover': { borderColor: color, bgcolor: `${color}0d` },
                    }}
                  >
                    <Typography variant="subtitle1" fontWeight={800}>{module.module_id}</Typography>
                    <Typography variant="h5" fontWeight={800} sx={{ mt: 0.5 }}>{module.size.toLocaleString()}</Typography>
                    <Typography variant="caption" color="text.secondary">genes</Typography>
                  </Paper>
                </Grid>
              )
            })}
          </Grid>

          {selectedModule && (
            <Grid container spacing={2}>
              <Grid item xs={12} md={5}>
                <Paper variant="outlined" sx={{ p: 2.5, height: '100%' }}>
                  <Typography variant="overline" color="text.secondary" fontWeight={700}>Selected community</Typography>
                  <Typography variant="h5" fontWeight={800} gutterBottom>MODULE {selectedModule.module_id}</Typography>
                  <Chip size="small" color="primary" variant="outlined" label={`${selectedModule.size.toLocaleString()} genes`} sx={{ mb: 2 }} />
                  <Divider sx={{ mb: 1.5 }} />
                  <Typography variant="subtitle1" fontWeight={700} gutterBottom>Hub genes</Typography>
                  {selectedModule.hub_genes.length ? (
                    <Stack spacing={0.25}>
                      {selectedModule.hub_genes.map((gene, index) => (
                        <Stack key={gene.gene_id} direction="row" justifyContent="space-between" alignItems="center" spacing={1} sx={{ py: 0.8, borderBottom: '1px solid', borderColor: 'divider' }}>
                          <Stack direction="row" spacing={1} alignItems="baseline" sx={{ minWidth: 0 }}>
                            <Typography variant="caption" color="text.secondary">{String(index + 1).padStart(2, '0')}</Typography>
                            <Typography variant="body2" fontWeight={700} sx={{ overflowWrap: 'anywhere' }}>{gene.symbol || gene.gene_id}</Typography>
                          </Stack>
                          <Typography variant="caption" color="text.secondary" sx={{ whiteSpace: 'nowrap' }}>degree {gene.degree}</Typography>
                        </Stack>
                      ))}
                    </Stack>
                  ) : (
                    <Typography variant="body2" color="text.secondary">Hub metrics are not present for this module.</Typography>
                  )}
                  {selectedModule.hub_genes.some((gene) => !gene.symbol) && (
                    <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 1.5 }}>
                      Unmapped genes are shown by Ensembl ID.
                    </Typography>
                  )}
                </Paper>
              </Grid>

              <Grid item xs={12} md={7}>
                <Paper variant="outlined" sx={{ p: 2.5, minHeight: 350 }}>
                  <Stack direction={{ xs: 'column', sm: 'row' }} justifyContent="space-between" alignItems={{ xs: 'flex-start', sm: 'center' }} spacing={1.5} sx={{ mb: 2 }}>
                    <Box>
                      <Typography variant="h6" fontWeight={800}>Functional enrichment</Typography>
                      <Typography variant="body2" color="text.secondary">Over-representation analysis of mapped genes in this module.</Typography>
                    </Box>
                    <Stack direction="row" spacing={1}>
                      <TextField select size="small" label="Gene set" value={geneSet} onChange={(event) => { setGeneSet(event.target.value); enrichmentMutation.reset() }} sx={{ minWidth: 210 }}>
                        {availableGeneSets.map((availableGeneSet) => <MenuItem key={availableGeneSet} value={availableGeneSet}>{availableGeneSet}</MenuItem>)}
                      </TextField>
                      <Button variant="contained" onClick={() => enrichmentMutation.mutate()} disabled={enrichmentMutation.isPending}>
                        {enrichmentMutation.isPending ? <CircularProgress size={19} color="inherit" /> : 'Run'}
                      </Button>
                    </Stack>
                  </Stack>
                  {enrichmentMutation.isPending && <LinearProgress sx={{ mb: 2 }} />}
                  {enrichmentMutation.isError && <Alert severity="error" sx={{ mb: 2 }}>Enrichment could not be completed. Verify gene-symbol mappings and retry.</Alert>}
                  {enrichment?.message && <Alert severity="info" sx={{ mb: 2 }}>{enrichment.message}</Alert>}
                  {enrichment && (
                    <>
                      <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 1.5 }}>
                        {enrichment.mapped_genes.toLocaleString()} of {enrichment.total_genes.toLocaleString()} module genes mapped to symbols
                      </Typography>
                      {enrichment.results.length > 0 && (
                        <TableContainer sx={{ maxHeight: 420 }}>
                          <Table size="small" stickyHeader>
                            <TableHead><TableRow><TableCell>Functional term</TableCell><TableCell>Overlap</TableCell><TableCell align="right">Adjusted p</TableCell></TableRow></TableHead>
                            <TableBody>
                              {enrichment.results.map((result) => (
                                <TableRow key={result.term} hover>
                                  <TableCell>
                                    <Typography variant="body2" fontWeight={600}>{result.term}</Typography>
                                    {result.genes && <Typography variant="caption" color="text.secondary">{result.genes}</Typography>}
                                  </TableCell>
                                  <TableCell>{result.overlap ?? '—'}</TableCell>
                                  <TableCell align="right">{result.adjusted_pvalue == null ? '—' : result.adjusted_pvalue.toExponential(2)}</TableCell>
                                </TableRow>
                              ))}
                            </TableBody>
                          </Table>
                        </TableContainer>
                      )}
                    </>
                  )}
                  {!enrichment && !enrichmentMutation.isPending && !enrichmentMutation.isError && (
                    <Typography variant="body2" color="text.secondary" sx={{ py: 4, textAlign: 'center' }}>
                      Run enrichment to calculate pathways for {selectedModule.module_id}.
                    </Typography>
                  )}
                </Paper>
              </Grid>
            </Grid>
          )}
        </>
      )}
    </Box>
  )
}