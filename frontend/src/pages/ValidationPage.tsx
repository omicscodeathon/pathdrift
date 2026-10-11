import { useState } from 'react'
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  CircularProgress,
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
import { Science } from '@mui/icons-material'
import { useMutation, useQuery } from '@tanstack/react-query'
import { validationApi } from '@/api/client'
import { useProjectStore } from '@/store/projectStore'

type ValidationSection = {
  available: boolean
  reason?: string | null
  method?: string
}

type ValidationReport = {
  drift_analysis_id: string
  species: string
  biological: ValidationSection & {
    evidence_independent: boolean
    limitation: string
    relationship_preservation: ValidationSection & {
      relationship_type: string
      conserved_edges_assessed: number
      pathway_supported_conserved_edges: number
      fraction_supported: number | null
      examples: Array<{ gene1: string; gene2: string; pathways: string[] }>
    }
    pathway_results: Array<{
      pathway_result_id: string
      gene_set: string
      source: string
      significant_term_count: number
      top_terms: Array<{ term: string; adjusted_pvalue: number | null; genes: string[] }>
    }>
  }
  statistical: ValidationSection & {
    observed?: number
    saved_global_drift_score?: number | null
    null_mean?: number
    null_std?: number
    p_value?: number
    permutations?: number
    shared_nodes?: number
  }
  network: ValidationSection & {
    observed?: number
    null_mean?: number
    null_std?: number
    p_value?: number
    permutations?: number
    healthy_edges: number
    disease_edges: number
    healthy_network_id: string
    disease_network_id: string
  }
  machine_learning: ValidationSection & {
    experiments: Array<{
      experiment_id: string
      name: string
      model_type: string
      experiment_type: string
      cv_folds: number
      cross_validation: { auroc: number | null; auprc: number | null; accuracy: number | null; f1: number | null } | null
      independent_test: { auroc: number | null; auprc: number | null; accuracy: number | null; f1: number | null } | null
      external_dataset_configured: boolean
      leakage_warnings: string[]
    }>
  }
}

type ValidationJob = {
  id: string
  status: string
  progress: number
  progress_message: string | null
  error_message: string | null
  result: ValidationReport | null
}

function Metric({ label, value, detail }: { label: string; value: number | string | null | undefined; detail?: string }) {
  return (
    <Card variant="outlined">
      <CardContent>
        <Typography variant="caption" color="text.secondary">{label}</Typography>
        <Typography variant="h6" fontWeight={800}>
          {value == null ? 'Not available' : typeof value === 'number' ? value.toFixed(4) : value}
        </Typography>
        {detail && <Typography variant="caption" color="text.secondary">{detail}</Typography>}
      </CardContent>
    </Card>
  )
}

function SectionUnavailable({ section }: { section: ValidationSection }) {
  if (section.available) return null
  return <Alert severity="info">{section.reason ?? 'No result is available for this validation.'}</Alert>
}

export default function ValidationPage() {
  const storedDriftId = useProjectStore((state) => state.humanDriftId ?? state.mouseDriftId)
  const [driftId, setDriftId] = useState(storedDriftId ?? '')
  const [permutations, setPermutations] = useState(199)
  const [jobId, setJobId] = useState('')

  const runMutation = useMutation({
    mutationFn: () => validationApi.createRun({ drift_analysis_id: driftId.trim(), permutations }),
    onSuccess: (response) => setJobId(response.data.id as string),
  })

  const { data: job, isError: jobError } = useQuery({
    queryKey: ['scientific-validation', jobId],
    queryFn: () => validationApi.getRun(jobId).then((response) => response.data as ValidationJob),
    enabled: !!jobId,
    refetchInterval: (query) => {
      const status = query.state.data?.status
      return status === 'queued' || status === 'running' ? 1500 : false
    },
  })
  const report = job?.result

  return (
    <Box sx={{ maxWidth: 1200, mx: 'auto' }}>
      <Paper variant="outlined" sx={{ p: 2, mb: 3 }}>
        <Typography variant="h6" fontWeight={800} sx={{ mb: 1.5 }}>Run drift validation</Typography>
        <Stack direction={{ xs: 'column', md: 'row' }} spacing={1.5} alignItems="center">
          <TextField
            fullWidth
            size="small"
            label="Drift analysis ID"
            value={driftId}
            onChange={(event) => setDriftId(event.target.value.trim())}
          />
          <TextField
            size="small"
            type="number"
            label="Permutations"
            value={permutations}
            onChange={(event) => setPermutations(Math.max(19, Math.min(999, Number(event.target.value) || 19)))}
            inputProps={{ min: 19, max: 999, step: 10 }}
            sx={{ minWidth: { md: 150 } }}
          />
          <Button
            variant="contained"
            startIcon={<Science />}
            disabled={!driftId.trim() || runMutation.isPending}
            onClick={() => {
              setJobId('')
              runMutation.mutate()
            }}
            sx={{ minWidth: 170 }}
          >
            Run validation
          </Button>
        </Stack>
      </Paper>

      {runMutation.isError && <Alert severity="error" sx={{ mb: 2 }}>Validation could not be started. Confirm the drift ID belongs to a completed analysis.</Alert>}
      {jobError && <Alert severity="error" sx={{ mb: 2 }}>The validation job status could not be loaded.</Alert>}
      {job && (job.status === 'queued' || job.status === 'running') && (
        <Paper variant="outlined" sx={{ p: 2, mb: 2 }}>
          <Stack direction="row" spacing={1.5} alignItems="center">
            <CircularProgress size={20} />
            <Typography>{job.progress_message ?? 'Validation is running'} · {job.progress}%</Typography>
          </Stack>
        </Paper>
      )}
      {job?.status === 'failed' && <Alert severity="error" sx={{ mb: 2 }}>{job.error_message ?? 'Validation failed.'}</Alert>}

      {report && (
        <>
          <Alert severity="success" sx={{ mb: 2 }}>
            Saved validation report for {report.species} drift run <strong>{report.drift_analysis_id}</strong>.
          </Alert>

          <Grid container spacing={2} sx={{ mb: 2 }}>
            <Grid item xs={12} lg={6}>
              <Paper variant="outlined" sx={{ p: 2, height: '100%' }}>
                <Typography variant="h6" fontWeight={800} gutterBottom>Biological evidence</Typography>
                <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>{report.biological.method}</Typography>
                <Alert severity="info" sx={{ mb: 1.5 }}>{report.biological.limitation}</Alert>
                <SectionUnavailable section={report.biological} />
                <Typography variant="subtitle1" fontWeight={800} sx={{ mt: 1, mb: 1 }}>Preserved curated relationships</Typography>
                <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 1.5 }}>
                  {report.biological.relationship_preservation.relationship_type}
                </Typography>
                {report.biological.relationship_preservation.available ? (
                  <>
                    <Grid container spacing={1.5} sx={{ mb: 1.5 }}>
                      <Grid item xs={6} md={4}><Metric label="Conserved edges assessed" value={report.biological.relationship_preservation.conserved_edges_assessed} /></Grid>
                      <Grid item xs={6} md={4}><Metric label="Pathway-supported edges" value={report.biological.relationship_preservation.pathway_supported_conserved_edges} /></Grid>
                      <Grid item xs={6} md={4}><Metric label="Fraction supported" value={report.biological.relationship_preservation.fraction_supported} /></Grid>
                    </Grid>
                    {report.biological.relationship_preservation.examples.length > 0 && (
                      <TableContainer sx={{ mb: 2 }}>
                        <Table size="small">
                          <TableHead><TableRow><TableCell>Conserved edge</TableCell><TableCell>Shared curated pathway</TableCell></TableRow></TableHead>
                          <TableBody>
                            {report.biological.relationship_preservation.examples.map((edge) => (
                              <TableRow key={`${edge.gene1}-${edge.gene2}`}>
                                <TableCell>{edge.gene1} — {edge.gene2}</TableCell>
                                <TableCell>{edge.pathways.join(', ')}</TableCell>
                              </TableRow>
                            ))}
                          </TableBody>
                        </Table>
                      </TableContainer>
                    )}
                  </>
                ) : <Alert severity="info">{report.biological.relationship_preservation.reason ?? 'No curated relationship result is available.'}</Alert>}
                {report.biological.pathway_results.map((pathway) => (
                  <Box key={pathway.pathway_result_id} sx={{ mb: 2 }}>
                    <Typography variant="subtitle2" fontWeight={700}>{pathway.gene_set} · {pathway.significant_term_count} significant terms</Typography>
                    <TableContainer>
                      <Table size="small">
                        <TableHead><TableRow><TableCell>Curated term</TableCell><TableCell align="right">FDR</TableCell><TableCell>Genes</TableCell></TableRow></TableHead>
                        <TableBody>
                          {pathway.top_terms.map((term) => (
                            <TableRow key={term.term}>
                              <TableCell>{term.term}</TableCell>
                              <TableCell align="right">{term.adjusted_pvalue == null ? 'Not available' : term.adjusted_pvalue.toExponential(2)}</TableCell>
                              <TableCell>{term.genes.join(', ') || 'Not available'}</TableCell>
                            </TableRow>
                          ))}
                        </TableBody>
                      </Table>
                    </TableContainer>
                  </Box>
                ))}
              </Paper>
            </Grid>

            <Grid item xs={12} lg={6}>
              <Paper variant="outlined" sx={{ p: 2, height: '100%' }}>
                <Typography variant="h6" fontWeight={800} gutterBottom>Statistical validation</Typography>
                <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>{report.statistical.method ?? 'Permutation test'}</Typography>
                <SectionUnavailable section={report.statistical} />
                {report.statistical.available && (
                  <>
                    <Grid container spacing={1.5}>
                      <Grid item xs={6}><Metric label="Observed turnover" value={report.statistical.observed} /></Grid>
                      <Grid item xs={6}><Metric label="Permutation p-value" value={report.statistical.p_value} /></Grid>
                      <Grid item xs={6}><Metric label="Null mean ± SD" value={report.statistical.null_mean} detail={report.statistical.null_std == null ? undefined : `SD ${report.statistical.null_std.toFixed(4)}`} /></Grid>
                      <Grid item xs={6}><Metric label="Saved global drift score" value={report.statistical.saved_global_drift_score} /></Grid>
                    </Grid>
                    <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 1.5 }}>
                      {report.statistical.permutations} permutations · {report.statistical.shared_nodes} shared genes · p-value tests whether observed turnover exceeds the label-permutation null.
                    </Typography>
                  </>
                )}
              </Paper>
            </Grid>

            <Grid item xs={12}>
              <Paper variant="outlined" sx={{ p: 2 }}>
                <Typography variant="h6" fontWeight={800} gutterBottom>Network validation</Typography>
                <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>{report.network.method ?? 'Degree-preserving network null'}</Typography>
                <SectionUnavailable section={report.network} />
                {report.network.available && (
                  <Grid container spacing={1.5}>
                    <Grid item xs={6} md={3}><Metric label="Observed edge turnover" value={report.network.observed} /></Grid>
                    <Grid item xs={6} md={3}><Metric label="Null mean ± SD" value={report.network.null_mean} detail={report.network.null_std == null ? undefined : `SD ${report.network.null_std.toFixed(4)}`} /></Grid>
                    <Grid item xs={6} md={3}><Metric label="Null p-value" value={report.network.p_value} /></Grid>
                    <Grid item xs={6} md={3}><Metric label="Healthy / disease edges" value={`${report.network.healthy_edges} / ${report.network.disease_edges}`} /></Grid>
                  </Grid>
                )}
                <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 1.5 }}>
                  Edge totals: healthy {report.network.healthy_edges}; disease {report.network.disease_edges}. Networks: {report.network.healthy_network_id} / {report.network.disease_network_id}.
                </Typography>
              </Paper>
            </Grid>

            <Grid item xs={12}>
              <Paper variant="outlined" sx={{ p: 2 }}>
                <Typography variant="h6" fontWeight={800} gutterBottom>Machine-learning validation</Typography>
                <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>{report.machine_learning.method}</Typography>
                <SectionUnavailable section={report.machine_learning} />
                {report.machine_learning.experiments.map((experiment) => (
                  <Box key={experiment.experiment_id} sx={{ mb: 2 }}>
                    <Typography variant="subtitle2" fontWeight={700} gutterBottom>
                      {experiment.name} · {experiment.model_type} · {experiment.cv_folds}-fold CV
                    </Typography>
                    <TableContainer>
                      <Table size="small">
                        <TableHead><TableRow><TableCell>Evaluation</TableCell><TableCell align="right">AUROC</TableCell><TableCell align="right">AUPRC</TableCell><TableCell align="right">Accuracy</TableCell><TableCell align="right">F1</TableCell></TableRow></TableHead>
                        <TableBody>
                          {[
                            { label: 'Stratified cross-validation', metrics: experiment.cross_validation },
                            { label: 'Independent test dataset', metrics: experiment.independent_test },
                          ].map(({ label, metrics }) => (
                            <TableRow key={label}>
                              <TableCell>{label}</TableCell>
                              <TableCell align="right">{metrics?.auroc == null ? 'Not available' : metrics.auroc.toFixed(3)}</TableCell>
                              <TableCell align="right">{metrics?.auprc == null ? 'Not available' : metrics.auprc.toFixed(3)}</TableCell>
                              <TableCell align="right">{metrics?.accuracy == null ? 'Not available' : metrics.accuracy.toFixed(3)}</TableCell>
                              <TableCell align="right">{metrics?.f1 == null ? 'Not available' : metrics.f1.toFixed(3)}</TableCell>
                            </TableRow>
                          ))}
                        </TableBody>
                      </Table>
                    </TableContainer>
                    {!experiment.external_dataset_configured && <Typography variant="caption" color="text.secondary">No independent validation dataset was configured for this experiment.</Typography>}
                    {experiment.leakage_warnings.map((warning) => <Alert key={warning} severity="warning" sx={{ mt: 1 }}>{warning}</Alert>)}
                  </Box>
                ))}
              </Paper>
            </Grid>
          </Grid>
        </>
      )}
    </Box>
  )
}
