import { useMemo, useState } from 'react'
import {
  Alert, Autocomplete, Box, Button, Chip, CircularProgress, Grid, LinearProgress,
  MenuItem, Paper, Stack, Table, TableBody, TableCell, TableContainer,
  TableHead, TableRow, TextField, ToggleButton, ToggleButtonGroup, Typography,
} from '@mui/material'
import { OpenInNew, Search } from '@mui/icons-material'
import CytoscapeComponent from 'react-cytoscapejs'
import { useMutation, useQuery } from '@tanstack/react-query'
import { phase3Api, ppiApi } from '@/api/client'
import { RunHeader, useRunId, type DEG, type Page, type Species } from './analysis/shared'

interface PPINetwork {
  source: 'STRING'
  species: 'human' | 'mouse'
  network_type: 'physical'
  query_identifier: string
  mapped_query: { string_id: string; preferred_name: string; annotation?: string | null }
  confidence_level: 'high' | 'medium' | 'all'
  minimum_combined_score: number
  node_count: number
  interaction_count: number
  nodes: Array<{ string_id: string; preferred_name: string; is_query: boolean }>
  interactions: Array<{
    protein_a: string
    protein_b: string
    preferred_name_a: string
    preferred_name_b: string
    score: number
    experimental_score: number
    database_score: number
  }>
  string_search_url: string
}

const CONFIDENCE_LEVELS = [
  { value: 'high', label: 'High confidence', description: 'Combined score ≥ 0.700' },
  { value: 'medium', label: 'Medium confidence', description: 'Combined score ≥ 0.400' },
  { value: 'all', label: 'All', description: 'All returned scores' },
] as const

export default function PPINetworkPage() {
  const runId = useRunId()
  const [identifier, setIdentifier] = useState('')
  const [species, setSpecies] = useState<Species>('human')
  const [confidence, setConfidence] = useState<'high' | 'medium' | 'all'>('high')

  const { data: genePage, isLoading: genesLoading, isError: genesError } = useQuery({
    queryKey: ['ppi-run-genes', runId, species],
    queryFn: () => phase3Api.deg(runId!, { species, limit: 500, offset: 0 })
      .then((response) => response.data as Page<DEG>),
    enabled: !!runId,
  })
  const runGenes = genePage?.items ?? []

  const searchMutation = useMutation({
    mutationKey: ['ppi', 'string-network'],
    mutationFn: () => ppiApi.search({ identifier: identifier.trim(), species, confidence })
      .then((response) => response.data as PPINetwork),
  })
  const network = searchMutation.data

  const elements = useMemo(() => {
    if (!network) return []
    const degree = new Map<string, number>()
    for (const edge of network.interactions) {
      degree.set(edge.protein_a, (degree.get(edge.protein_a) ?? 0) + 1)
      degree.set(edge.protein_b, (degree.get(edge.protein_b) ?? 0) + 1)
    }
    return [
      ...network.nodes.map((node) => ({
        data: {
          id: node.string_id,
          label: node.preferred_name,
          degree: degree.get(node.string_id) ?? 0,
          isQuery: node.is_query,
        },
      })),
      ...network.interactions.map((edge) => ({
        data: {
          id: `${edge.protein_a}-${edge.protein_b}`,
          source: edge.protein_a,
          target: edge.protein_b,
          score: edge.score,
        },
      })),
    ]
  }, [network])

  const handleSearch = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!identifier.trim()) return
    searchMutation.mutate()
  }

  return (
    <Box sx={{ maxWidth: 1320, mx: 'auto' }}>
      <RunHeader runId={runId ?? ''} view="ppi-network" title="PPI Network" subtitle="Explore physical protein interactions seeded from saved run genes" />
      <Stack direction={{ xs: 'column', sm: 'row' }} justifyContent="space-between" alignItems={{ xs: 'flex-start', sm: 'center' }} spacing={1.5} sx={{ mb: 2.5 }}>
        <Box>
          <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
            Choose a gene from this run’s differential-expression results or enter an identifier. Physical interactions are retrieved live from STRING.
          </Typography>
        </Box>
        <Chip size="small" variant="outlined" label="Live source: STRING" />
      </Stack>

      <Paper component="form" onSubmit={handleSearch} variant="outlined" sx={{ p: 2, mb: 2.5 }}>
        <Grid container spacing={1.5} alignItems="center">
          <Grid item xs={12} sm={5}>
            <Autocomplete
              freeSolo
              options={runGenes}
              getOptionLabel={(option) => typeof option === 'string'
                ? option
                : `${option.gene_symbol || option.ensembl_id} · ${option.ensembl_id}`}
              inputValue={identifier}
              onInputChange={(_, value, reason) => {
                if (reason === 'input' || reason === 'clear') setIdentifier(value)
              }}
              onChange={(_, value) => {
                if (typeof value === 'string') setIdentifier(value)
                else if (value) setIdentifier(value.gene_symbol || value.ensembl_id)
              }}
              loading={genesLoading}
              renderInput={(params) => <TextField
                {...params}
                fullWidth
                size="small"
                label="Run gene or protein identifier"
                helperText="Suggestions use this run’s saved differential-expression genes."
                inputProps={{ ...params.inputProps, maxLength: 100 }}
              />}
            />
          </Grid>
          <Grid item xs={6} sm={2}>
            <TextField
              select
              fullWidth
              size="small"
              label="Species"
              value={species}
              onChange={(event) => { setSpecies(event.target.value as Species); setIdentifier(''); searchMutation.reset() }}
            >
              <MenuItem value="human">Human</MenuItem>
              <MenuItem value="mouse">Mouse</MenuItem>
            </TextField>
          </Grid>
          <Grid item xs={12} sm={3}>
            <ToggleButtonGroup
              exclusive
              fullWidth
              size="small"
              value={confidence}
              onChange={(_, value: 'high' | 'medium' | 'all' | null) => { if (value) setConfidence(value) }}
              aria-label="STRING interaction confidence"
            >
              {CONFIDENCE_LEVELS.map((level) => (
                <ToggleButton key={level.value} value={level.value} aria-label={level.label}>
                  {level.value === 'high' ? 'High' : level.value === 'medium' ? 'Medium' : 'All'}
                </ToggleButton>
              ))}
            </ToggleButtonGroup>
          </Grid>
          <Grid item xs={12} sm={2}>
            <Button type="submit" variant="contained" fullWidth startIcon={searchMutation.isPending ? <CircularProgress size={17} color="inherit" /> : <Search />} disabled={!identifier.trim() || searchMutation.isPending}>
              {searchMutation.isPending ? 'Searching' : 'Search STRING'}
            </Button>
          </Grid>
          <Grid item xs={12}>
            <Typography variant="caption" color="text.secondary">
              {CONFIDENCE_LEVELS.find((level) => level.value === confidence)?.description} · one run gene seed with up to 20 STRING-added partners
            </Typography>
          </Grid>
        </Grid>
      </Paper>

      {genesError && <Alert severity="error" sx={{ mb: 2 }}>Saved run genes could not be loaded. You can still enter a gene or protein identifier manually.</Alert>}
      {!genesLoading && !genesError && runGenes.length === 0 && (
        <Alert severity="info" sx={{ mb: 2 }}>No differential-expression genes are saved for this species in the selected run. Enter a gene or protein identifier manually.</Alert>
      )}
      {runGenes.length > 0 && (
        <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 1.5 }}>
          Suggestions are the first {runGenes.length} saved {species} genes, ordered by the run’s differential-expression results.
        </Typography>
      )}

      {searchMutation.isPending && <LinearProgress sx={{ mb: 2 }} />}
      {searchMutation.isError && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {((searchMutation.error as { response?: { data?: { detail?: string } } })?.response?.data?.detail)
            ?? 'STRING could not return an interaction network. Check the identifier and try again.'}
        </Alert>
      )}

      {network && (
        <>
          <Grid container spacing={1.5} sx={{ mb: 2 }}>
            {[
              { label: 'NODES', value: network.node_count.toLocaleString(), color: '#1677a8' },
              { label: 'INTERACTIONS', value: network.interaction_count.toLocaleString(), color: '#25856b' },
              { label: 'MINIMUM SCORE', value: network.minimum_combined_score.toFixed(3), color: '#be5a32' },
            ].map((metric) => (
              <Grid item xs={4} key={metric.label}>
                <Paper variant="outlined" sx={{ p: 1.75, borderTop: `3px solid ${metric.color}` }}>
                  <Typography variant="caption" color="text.secondary" fontWeight={700} letterSpacing="0.06em">{metric.label}</Typography>
                  <Typography variant="h5" fontWeight={800}>{metric.value}</Typography>
                </Paper>
              </Grid>
            ))}
          </Grid>

          <Grid container spacing={2}>
            <Grid item xs={12} lg={8}>
              <Paper variant="outlined" sx={{ overflow: 'hidden' }}>
                <Stack direction={{ xs: 'column', sm: 'row' }} justifyContent="space-between" alignItems={{ xs: 'flex-start', sm: 'center' }} spacing={0.5} sx={{ p: 1.75, borderBottom: '1px solid', borderColor: 'divider' }}>
                  <Box>
                    <Typography variant="subtitle1" fontWeight={800}>{network.mapped_query.preferred_name}</Typography>
                    <Typography variant="caption" color="text.secondary">{network.mapped_query.string_id} · {network.species} · physical interactions</Typography>
                  </Box>
                  <Button size="small" endIcon={<OpenInNew />} component="a" href={network.string_search_url} target="_blank" rel="noreferrer">
                    Open STRING
                  </Button>
                </Stack>
                {network.interaction_count > 0 ? (
                  <CytoscapeComponent
                    elements={elements}
                    style={{ width: '100%', height: 'min(65vh, 620px)', minHeight: 400, background: '#f6f8fa' }}
                    stylesheet={[
                      { selector: 'node', style: { 'background-color': '#1677a8', label: 'data(label)', color: '#fff', 'font-size': 9, 'text-valign': 'center', 'text-halign': 'center', width: 'mapData(degree, 1, 15, 24, 48)', height: 'mapData(degree, 1, 15, 24, 48)', 'border-width': 1, 'border-color': '#fff' } },
                      { selector: 'node[?isQuery]', style: { 'background-color': '#be5a32', 'border-width': 3, 'border-color': '#273e59', width: 52, height: 52, 'font-size': 11, 'font-weight': 700 } },
                      { selector: 'edge', style: { width: 'mapData(score, 0.4, 1, 1, 4)', 'line-color': '#8799a7', opacity: 0.72, 'curve-style': 'bezier' } },
                    ]}
                    layout={{ name: 'cose', animate: false, randomize: false, nodeRepulsion: 7000, idealEdgeLength: 65 }}
                  />
                ) : (
                  <Box sx={{ minHeight: 400, display: 'grid', placeItems: 'center', p: 3 }}>
                    <Typography variant="body2" color="text.secondary">STRING returned no physical interactions at this confidence level.</Typography>
                  </Box>
                )}
              </Paper>
            </Grid>
            <Grid item xs={12} lg={4}>
              <Paper variant="outlined" sx={{ p: 2 }}>
                <Typography variant="h6" fontWeight={800} gutterBottom>STRING INTERACTIONS</Typography>
                <TableContainer sx={{ maxHeight: 570 }}>
                  <Table size="small" stickyHeader>
                    <TableHead><TableRow><TableCell>Partner</TableCell><TableCell align="right">Score</TableCell></TableRow></TableHead>
                    <TableBody>
                      {network.interactions.map((interaction) => {
                        const isProteinA = interaction.protein_a === network.mapped_query.string_id
                        const partner = isProteinA ? interaction.preferred_name_b : interaction.preferred_name_a
                        return (
                          <TableRow key={`${interaction.protein_a}-${interaction.protein_b}`} hover>
                            <TableCell>
                              <Typography variant="body2" fontWeight={600}>{partner}</Typography>
                              <Typography variant="caption" color="text.secondary">
                                Experimental {(interaction.experimental_score ?? 0).toFixed(2)} · Database {(interaction.database_score ?? 0).toFixed(2)}
                              </Typography>
                            </TableCell>
                            <TableCell align="right"><Chip size="small" label={interaction.score.toFixed(3)} color={interaction.score >= 0.7 ? 'success' : interaction.score >= 0.4 ? 'warning' : 'default'} /></TableCell>
                          </TableRow>
                        )
                      })}
                      {network.interactions.length === 0 && <TableRow><TableCell colSpan={2}>No STRING interactions at this threshold.</TableCell></TableRow>}
                    </TableBody>
                  </Table>
                </TableContainer>
              </Paper>
            </Grid>
          </Grid>
          <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 1.5 }}>
            Counts and edges are from the live STRING physical network response for this query and confidence filter. One seed was expanded by up to 20 STRING partners.
          </Typography>
        </>
      )}

      {!network && !searchMutation.isPending && !searchMutation.isError && (
        <Alert severity="info">Search a protein identifier to retrieve its STRING physical interaction neighborhood.</Alert>
      )}
    </Box>
  )
}