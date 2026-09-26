import { useMemo, useState } from 'react'
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Grid,
  List,
  ListItem,
  ListItemText,
  Paper,
  Stack,
  TextField,
  Typography,
} from '@mui/material'
import { useMutation } from '@tanstack/react-query'
import { useSnackbar } from 'notistack'
import CytoscapeComponent from 'react-cytoscapejs'

import { geneLossApi } from '@/api/client'
import type { GeneLossAnalysisResult } from '@/types'
import { useProjectStore } from '@/store/projectStore'

function parseGenes(input: string) {
  return input
    .split(/[\n,;]/)
    .map(item => item.trim())
    .filter(Boolean)
}

function parseExpression(input: string) {
  const result: Record<string, number> = {}
  for (const entry of input.split(/[\n,;]/)) {
    const item = entry.trim()
    if (!item) continue
    const [gene, value] = item.split(':')
    if (!gene || value == null) continue
    result[gene.trim()] = Number(value.trim())
  }
  return result
}

function parseInteractions(input: string) {
  return input
    .split(/[\n;]/)
    .map(item => item.trim())
    .filter(Boolean)
    .map(item => item.split(',').map(part => part.trim()).filter(Boolean))
    .filter(pair => pair.length === 2)
}

export default function GeneLossPage() {
  const { enqueueSnackbar } = useSnackbar()
  const { currentAnalysisId, currentDatasetId, healthyNetworkId, diseaseNetworkId } = useProjectStore()
  const [genesText, setGenesText] = useState('GENE_A, GENE_B, GENE_C, GENE_D')
  const [expressionText, setExpressionText] = useState('GENE_A:10, GENE_B:8, GENE_C:2.2, GENE_D:1.1')
  const [interactionText, setInteractionText] = useState('GENE_A,GENE_B; GENE_A,GENE_C; GENE_B,GENE_D')
  const [imageDataUrl, setImageDataUrl] = useState<string | null>(null)
  const selectedNetworkId = diseaseNetworkId ?? healthyNetworkId

  const mutation = useMutation({
    mutationKey: ['gene-loss', 'analyze'],
    mutationFn: () =>
      geneLossApi.analyze({
        analysis_id: currentAnalysisId,
        dataset_id: currentDatasetId,
        network_id: selectedNetworkId,
        genes: currentDatasetId ? [] : parseGenes(genesText),
        expression: currentDatasetId ? {} : parseExpression(expressionText),
        interactions: currentDatasetId && selectedNetworkId ? [] : parseInteractions(interactionText),
        image_data_url: imageDataUrl,
      }),
    onSuccess: () => {
      enqueueSnackbar('Gene-loss analysis completed', { variant: 'success' })
    },
    onError: () => {
      enqueueSnackbar('Gene-loss analysis failed', { variant: 'error' })
    },
  })

  const result = mutation.data?.data as GeneLossAnalysisResult | undefined
  const cyElements = result
    ? [
        ...result.network.nodes.map(node => ({ data: node })),
        ...result.network.edges.map((edge, index) => ({
          data: { id: `${edge.source}-${edge.target}-${index}`, source: edge.source, target: edge.target },
        })),
      ]
    : []

  const rankedGenes = useMemo(
    () => Object.entries(result?.gene_scores ?? {}).sort((a, b) => (b[1].probability ?? 0) - (a[1].probability ?? 0)),
    [result]
  )

  const handleImageUpload = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    if (!file) return
    const reader = new FileReader()
    reader.onload = () => setImageDataUrl(String(reader.result))
    reader.readAsDataURL(file)
  }

  return (
    <Box>
      <Typography variant="h4" fontWeight={700} gutterBottom>Gene Loss Risk</Typography>
      <Typography variant="body2" color="text.secondary" mb={3}>
        Combine image-derived morphology, PPI structure, and expression loss to flag genes at high risk of functional loss.
      </Typography>

      <Grid container spacing={3}>
        <Grid item xs={12} md={5}>
          <Paper sx={{ p: 2, mb: 2 }} variant="outlined">
            <Stack spacing={2}>
              <Alert severity={currentDatasetId ? 'success' : 'info'}>
                {currentDatasetId
                  ? `Current dataset: ${currentDatasetId}${selectedNetworkId ? ` · network: ${selectedNetworkId}` : ''}`
                  : 'No current dataset selected. Manual inputs will be analyzed.'}
              </Alert>
              <TextField
                label="Genes"
                multiline
                minRows={4}
                value={genesText}
                onChange={e => setGenesText(e.target.value)}
              />
              <TextField
                label="Expression (gene:value)"
                multiline
                minRows={4}
                value={expressionText}
                onChange={e => setExpressionText(e.target.value)}
              />
              <TextField
                label="PPI interactions (gene1,gene2)"
                multiline
                minRows={4}
                value={interactionText}
                onChange={e => setInteractionText(e.target.value)}
              />
              <Button variant="outlined" component="label">
                Upload image
                <input hidden accept="image/*" type="file" onChange={handleImageUpload} />
              </Button>
              <Button variant="contained" onClick={() => mutation.mutate()} disabled={mutation.isPending}>
                Analyze gene loss risk
              </Button>
            </Stack>
          </Paper>
        </Grid>

        <Grid item xs={12} md={7}>
          {result ? (
            <Stack spacing={2}>
              <Card variant="outlined">
                <CardContent>
                  <Typography variant="h6" fontWeight={700}>Image summary</Typography>
                  <Typography variant="body2" color="text.secondary">
                    {result.image_summary.width}×{result.image_summary.height}px · mean intensity {result.image_summary.mean_intensity.toFixed(2)} · edge density {result.image_summary.edge_density.toFixed(3)}
                  </Typography>
                </CardContent>
              </Card>

              <Card variant="outlined">
                <CardContent>
                  <Typography variant="h6" fontWeight={700} gutterBottom>Highest risk genes</Typography>
                  <List dense>
                    {result.highest_risk_genes.map(item => (
                      <ListItem key={item.gene} divider>
                        <ListItemText
                          primary={`${item.gene} — ${item.probability.toFixed(3)} risk`}
                          secondary={item.predicted_loss ? 'Predicted loss' : 'Stable signal'}
                        />
                      </ListItem>
                    ))}
                  </List>
                </CardContent>
              </Card>

              <Card variant="outlined">
                <CardContent>
                  <Typography variant="h6" fontWeight={700} gutterBottom>Gene scores</Typography>
                  <Box sx={{ display: 'grid', gap: 1 }}>
                    {rankedGenes.map(([gene, score]) => (
                      <Box key={gene} sx={{ display: 'flex', justifyContent: 'space-between', gap: 2, alignItems: 'center' }}>
                        <Typography variant="body2" fontWeight={600}>{gene}</Typography>
                        <Typography variant="caption" color="text.secondary">
                          {score.probability.toFixed(3)} / {score.risk_score.toFixed(3)}
                        </Typography>
                      </Box>
                    ))}
                  </Box>
                </CardContent>
              </Card>

              <Card variant="outlined">
                <CardContent>
                  <Typography variant="h6" fontWeight={700} gutterBottom>PPI interaction map</Typography>
                  <CytoscapeComponent
                    elements={cyElements}
                    style={{ width: '100%', height: '420px', background: '#0f1729' }}
                    stylesheet={[
                      {
                        selector: 'node',
                        style: {
                          'background-color': '#00acc1',
                          label: 'data(label)',
                          color: '#fff',
                          'font-size': '10px',
                          'text-valign': 'center',
                          'text-halign': 'center',
                          width: 'mapData(degree, 0, 10, 18, 42)',
                          height: 'mapData(degree, 0, 10, 18, 42)',
                        },
                      },
                      { selector: 'edge', style: { width: 2, 'line-color': '#90caf9', opacity: 0.7 } },
                    ]}
                    layout={{ name: 'cose', animate: false }}
                  />
                </CardContent>
              </Card>
            </Stack>
          ) : (
            <Alert severity="info">Run a gene-loss analysis to inspect risk predictions and PPI context.</Alert>
          )}
        </Grid>
      </Grid>
    </Box>
  )
}