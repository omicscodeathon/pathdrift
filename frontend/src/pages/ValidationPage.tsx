import { Box, Typography, Alert, Paper, Grid, Button, TextField, MenuItem, CircularProgress, Table, TableBody, TableCell, TableHead, TableRow, TableContainer } from '@mui/material'
import { useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { useSnackbar } from 'notistack'
import { validationApi, mlApi } from '@/api/client'
import type { ModelMetric } from '@/types'

export default function ValidationPage() {
  const { enqueueSnackbar } = useSnackbar()
  const [expId, setExpId] = useState('')
  const [loaded, setLoaded] = useState('')

  const { data: comparison, isLoading } = useQuery({
    queryKey: ['model-comparison', loaded],
    queryFn: () => validationApi.compareModels(loaded).then(r => r.data as {
      analysis_id: string;
      research_question: string;
      comparison: Array<{ experiment_id: string; name: string; experiment_type: string; model_type: string; status: string; metrics: ModelMetric[] }>;
    }),
    enabled: !!loaded,
  })

  return (
    <Box>
      <Typography variant="h4" fontWeight={700} gutterBottom>Independent Validation</Typography>
      <Typography variant="body2" color="text.secondary" mb={2}>
        Compare model performance across training, cross-validation, and external validation splits.
        External validation on an independent dataset is the only scientifically rigorous performance estimate.
      </Typography>

      <Alert severity="warning" sx={{ mb: 3 }}>
        <strong>Scientific integrity:</strong> Do not report training accuracy as evidence of predictive utility.
        Cross-validation and external validation are the relevant metrics.
        A model with high training accuracy and low validation accuracy is overfit.
      </Alert>

      <Paper sx={{ p: 2, mb: 3 }} variant="outlined">
        <Box sx={{ display: 'flex', gap: 2 }}>
          <TextField label="Any Experiment ID from Analysis" size="small" value={expId}
            onChange={e => setExpId(e.target.value)} sx={{ flex: 1 }} />
          <Button variant="outlined" onClick={() => setLoaded(expId)} disabled={!expId}>Load</Button>
        </Box>
      </Paper>

      {isLoading && <Typography color="text.secondary">Loading…</Typography>}

      {comparison && (
        <>
          <Alert severity="info" sx={{ mb: 3 }}>
            <strong>{comparison.research_question}</strong>
          </Alert>

          {comparison.comparison.map(exp => {
            const splitOrder = ['train', 'cv', 'external_val']
            const metricsBySplit = Object.fromEntries(exp.metrics.map(m => [m.split, m]))
            return (
              <Paper key={exp.experiment_id} sx={{ p: 2.5, mb: 2 }} variant="outlined">
                <Typography variant="subtitle1" fontWeight={700} gutterBottom>
                  {exp.name} — {exp.experiment_type.replace('_', ' ')} | {exp.model_type.replace('_', ' ')}
                </Typography>
                <TableContainer>
                  <Table size="small">
                    <TableHead>
                      <TableRow sx={{ '& th': { fontWeight: 600 } }}>
                        <TableCell>Split</TableCell>
                        <TableCell align="right">AUROC</TableCell>
                        <TableCell align="right">95% CI</TableCell>
                        <TableCell align="right">AUPRC</TableCell>
                        <TableCell align="right">Sensitivity</TableCell>
                        <TableCell align="right">Specificity</TableCell>
                        <TableCell align="right">F1</TableCell>
                      </TableRow>
                    </TableHead>
                    <TableBody>
                      {splitOrder.filter(s => metricsBySplit[s]).map(split => {
                        const m = metricsBySplit[split]
                        const isExt = split === 'external_val'
                        return (
                          <TableRow key={split} sx={{ bgcolor: isExt ? '#e3f2fd' : undefined }}>
                            <TableCell sx={{ fontWeight: isExt ? 700 : 400 }}>{split === 'external_val' ? '★ External Validation' : split.toUpperCase()}</TableCell>
                            <TableCell align="right" sx={{ fontWeight: 700 }}>{m.auroc?.toFixed(3) ?? '—'}</TableCell>
                            <TableCell align="right" sx={{ fontSize: 11, color: 'text.secondary' }}>
                              {m.auroc_ci_lower != null ? `[${m.auroc_ci_lower.toFixed(3)}, ${m.auroc_ci_upper?.toFixed(3)}]` : '—'}
                            </TableCell>
                            <TableCell align="right">{m.auprc?.toFixed(3) ?? '—'}</TableCell>
                            <TableCell align="right">{m.sensitivity?.toFixed(3) ?? '—'}</TableCell>
                            <TableCell align="right">{m.specificity?.toFixed(3) ?? '—'}</TableCell>
                            <TableCell align="right">{m.f1?.toFixed(3) ?? '—'}</TableCell>
                          </TableRow>
                        )
                      })}
                    </TableBody>
                  </Table>
                </TableContainer>
              </Paper>
            )
          })}
        </>
      )}
    </Box>
  )
}
