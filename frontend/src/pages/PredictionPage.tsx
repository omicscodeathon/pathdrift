import { useMemo, useState } from 'react'
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  Grid,
  Paper,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TextField,
  Typography,
} from '@mui/material'
import { useQuery } from '@tanstack/react-query'
import { mlApi } from '@/api/client'

type MLMetricRow = {
  id: string
  split: string
  auroc?: number | null
  auprc?: number | null
  accuracy?: number | null
  precision?: number | null
  recall?: number | null
  f1?: number | null
  sensitivity?: number | null
  specificity?: number | null
  confusion_matrix?: { matrix?: number[][] } | null
}

export default function PredictionPage() {
  const [experimentId, setExperimentId] = useState('')
  const [selectedId, setSelectedId] = useState('')

  const { data: experiment, isLoading: experimentLoading, isError: experimentError } = useQuery({
    queryKey: ['ml-experiment', selectedId],
    queryFn: () => selectedId ? mlApi.getExperiment(selectedId).then((response) => response.data) : null,
    enabled: !!selectedId,
  })

  const { data: metrics = [] as MLMetricRow[] } = useQuery({
    queryKey: ['ml-metrics', selectedId],
    queryFn: () => selectedId ? mlApi.getMetrics(selectedId).then((response) => response.data as MLMetricRow[]) : [],
    enabled: !!selectedId,
  })

  const { data: featureImportances = [] } = useQuery({
    queryKey: ['ml-features', selectedId],
    queryFn: () => selectedId ? mlApi.getFeatureImportances(selectedId).then((response) => response.data as Array<{ feature: string; importance: number }>) : [],
    enabled: !!selectedId,
  })

  const metricSummary = useMemo(() => {
    const cv = metrics.find((metric) => metric.split === 'cv')
    const external = metrics.find((metric) => metric.split === 'external_val')
    return {
      cv,
      external,
    }
  }, [metrics])

  const featureCandidates = [
    'expression_change',
    'network_degree',
    'network_drift',
    'PPI_degree',
    'PPI_disruption',
    'module_connectivity',
    'gene_loss_score',
    'pathway_features',
    'morphology_features',
  ]

  return (
    <Box sx={{ maxWidth: 1200, mx: 'auto' }}>
      <Typography variant="h4" fontWeight={800} gutterBottom>MACHINE LEARNING</Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        Persisted model results, feature importance, and validation metrics. The training step runs on the backend and the frontend renders the saved outputs.
      </Typography>

      <Paper variant="outlined" sx={{ p: 2, mb: 3 }}>
        <Stack direction={{ xs: 'column', md: 'row' }} spacing={1.5} alignItems="center">
          <TextField
            fullWidth
            size="small"
            label="Saved experiment ID"
            value={experimentId}
            onChange={(event) => setExperimentId(event.target.value.trim())}
            placeholder="Paste a completed ML experiment ID"
          />
          <Button variant="contained" disabled={!experimentId || experimentLoading} onClick={() => setSelectedId(experimentId)}>
            Load results
          </Button>
        </Stack>
      </Paper>

      {!selectedId && !experimentLoading && (
        <Alert severity="info">
          No persisted experiment is loaded yet. Paste a saved ML experiment ID to inspect feature sets, model metrics, and output artifacts.
        </Alert>
      )}

      {experimentError && (
        <Alert severity="error" sx={{ mb: 2 }}>
          This experiment could not be loaded. Check that the ID belongs to a completed ML run.
        </Alert>
      )}

      {experiment && (
        <>
          <Grid container spacing={2} sx={{ mb: 2 }}>
            <Grid item xs={12} md={3}>
              <Card variant="outlined">
                <CardContent>
                  <Typography variant="caption" color="text.secondary">MODEL</Typography>
                  <Typography variant="h6" fontWeight={800}>{experiment.model_type}</Typography>
                </CardContent>
              </Card>
            </Grid>
            <Grid item xs={12} md={3}>
              <Card variant="outlined">
                <CardContent>
                  <Typography variant="caption" color="text.secondary">FEATURE SET</Typography>
                  <Typography variant="h6" fontWeight={800}>{experiment.experiment_type}</Typography>
                </CardContent>
              </Card>
            </Grid>
            <Grid item xs={12} md={3}>
              <Card variant="outlined">
                <CardContent>
                  <Typography variant="caption" color="text.secondary">FEATURES USED</Typography>
                  <Typography variant="h6" fontWeight={800}>{experiment.n_features_used ?? 'n/a'}</Typography>
                </CardContent>
              </Card>
            </Grid>
            <Grid item xs={12} md={3}>
              <Card variant="outlined">
                <CardContent>
                  <Typography variant="caption" color="text.secondary">STATUS</Typography>
                  <Typography variant="h6" fontWeight={800}>{experiment.status}</Typography>
                </CardContent>
              </Card>
            </Grid>
          </Grid>

          <Paper variant="outlined" sx={{ p: 2, mb: 2 }}>
            <Typography variant="subtitle1" fontWeight={800} sx={{ mb: 1.5 }}>Candidate biological features</Typography>
            <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap">
              {featureCandidates.map((feature) => (
                <Chip key={feature} label={feature} variant="outlined" />
              ))}
            </Stack>
          </Paper>

          <Grid container spacing={2} sx={{ mb: 2 }}>
            <Grid item xs={12} md={6}>
              <Paper variant="outlined" sx={{ p: 2, height: '100%' }}>
                <Typography variant="subtitle1" fontWeight={800} sx={{ mb: 1.5 }}>Cross-validation metrics</Typography>
                <TableContainer>
                  <Table size="small">
                    <TableHead>
                      <TableRow>
                        <TableCell>Metric</TableCell>
                        <TableCell align="right">Value</TableCell>
                      </TableRow>
                    </TableHead>
                    <TableBody>
                      {[
                        ['ROC-AUC', metricSummary.cv?.auroc],
                        ['PR-AUC', metricSummary.cv?.auprc],
                        ['Accuracy', metricSummary.cv?.accuracy],
                        ['Precision', metricSummary.cv?.precision],
                        ['Recall', metricSummary.cv?.recall],
                        ['F1', metricSummary.cv?.f1],
                      ].map(([label, value]) => (
                        <TableRow key={label as string}>
                          <TableCell>{label}</TableCell>
                          <TableCell align="right">{value != null ? Number(value).toFixed(3) : '—'}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </TableContainer>
              </Paper>
            </Grid>
            <Grid item xs={12} md={6}>
              <Paper variant="outlined" sx={{ p: 2, height: '100%' }}>
                <Typography variant="subtitle1" fontWeight={800} sx={{ mb: 1.5 }}>External validation metrics</Typography>
                <TableContainer>
                  <Table size="small">
                    <TableHead>
                      <TableRow>
                        <TableCell>Metric</TableCell>
                        <TableCell align="right">Value</TableCell>
                      </TableRow>
                    </TableHead>
                    <TableBody>
                      {[
                        ['ROC-AUC', metricSummary.external?.auroc],
                        ['PR-AUC', metricSummary.external?.auprc],
                        ['Accuracy', metricSummary.external?.accuracy],
                        ['Precision', metricSummary.external?.precision],
                        ['Recall', metricSummary.external?.recall],
                        ['F1', metricSummary.external?.f1],
                      ].map(([label, value]) => (
                        <TableRow key={label as string}>
                          <TableCell>{label}</TableCell>
                          <TableCell align="right">{value != null ? Number(value).toFixed(3) : '—'}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </TableContainer>
              </Paper>
            </Grid>
          </Grid>

          <Grid container spacing={2} sx={{ mb: 2 }}>
            <Grid item xs={12} lg={7}>
              <Paper variant="outlined" sx={{ p: 2 }}>
                <Typography variant="subtitle1" fontWeight={800} sx={{ mb: 1.5 }}>Top feature importances</Typography>
                {featureImportances.length === 0 ? (
                  <Alert severity="info">No feature-importance output is saved for this experiment yet.</Alert>
                ) : (
                  <TableContainer>
                    <Table size="small">
                      <TableHead>
                        <TableRow>
                          <TableCell>Feature</TableCell>
                          <TableCell align="right">Importance</TableCell>
                        </TableRow>
                      </TableHead>
                      <TableBody>
                        {featureImportances.slice(0, 12).map((feature) => (
                          <TableRow key={feature.feature} hover>
                            <TableCell>{feature.feature}</TableCell>
                            <TableCell align="right">{Number(feature.importance).toFixed(4)}</TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </TableContainer>
                )}
              </Paper>
            </Grid>
            <Grid item xs={12} lg={5}>
              <Paper variant="outlined" sx={{ p: 2 }}>
                <Typography variant="subtitle1" fontWeight={800} sx={{ mb: 1.5 }}>Saved artifacts</Typography>
                <Stack spacing={1.5}>
                  <Box>
                    <Typography variant="caption" color="text.secondary">Model file</Typography>
                    <Typography variant="body2" sx={{ wordBreak: 'break-all' }}>{experiment.model_file_path ?? 'Not saved yet'}</Typography>
                  </Box>
                  <Box>
                    <Typography variant="caption" color="text.secondary">Feature importance file</Typography>
                    <Typography variant="body2" sx={{ wordBreak: 'break-all' }}>{experiment.feature_importance_path ?? 'Not saved yet'}</Typography>
                  </Box>
                  <Box>
                    <Typography variant="caption" color="text.secondary">Leakage warnings</Typography>
                    <Typography variant="body2">{experiment.leakage_warnings?.length ? experiment.leakage_warnings.join(', ') : 'None recorded'}</Typography>
                  </Box>
                </Stack>
              </Paper>
            </Grid>
          </Grid>

          <Paper variant="outlined" sx={{ p: 2 }}>
            <Typography variant="subtitle1" fontWeight={800} sx={{ mb: 1.5 }}>Saved validation summary</Typography>
            <TableContainer>
              <Table size="small">
                <TableHead>
                  <TableRow>
                    <TableCell>Split</TableCell>
                    <TableCell align="right">ROC-AUC</TableCell>
                    <TableCell align="right">PR-AUC</TableCell>
                    <TableCell align="right">Accuracy</TableCell>
                    <TableCell align="right">Precision</TableCell>
                    <TableCell align="right">Recall</TableCell>
                    <TableCell align="right">F1</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {metrics.map((metric) => (
                    <TableRow key={metric.id} hover>
                      <TableCell>{metric.split}</TableCell>
                      <TableCell align="right">{metric.auroc != null ? metric.auroc.toFixed(3) : '—'}</TableCell>
                      <TableCell align="right">{metric.auprc != null ? metric.auprc.toFixed(3) : '—'}</TableCell>
                      <TableCell align="right">{metric.accuracy != null ? metric.accuracy.toFixed(3) : '—'}</TableCell>
                      <TableCell align="right">{metric.precision != null ? metric.precision.toFixed(3) : '—'}</TableCell>
                      <TableCell align="right">{metric.recall != null ? metric.recall.toFixed(3) : '—'}</TableCell>
                      <TableCell align="right">{metric.f1 != null ? metric.f1.toFixed(3) : '—'}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </TableContainer>
          </Paper>
        </>
      )}
    </Box>
  )
}
