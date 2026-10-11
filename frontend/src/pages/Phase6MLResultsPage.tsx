import { useEffect, useState } from 'react'
import { Link as RouterLink } from 'react-router-dom'
import { useParams } from 'react-router-dom'
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  CircularProgress,
  Grid,
  LinearProgress,
  MenuItem,
  Paper,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TablePagination,
  TableRow,
  TextField,
  Typography,
} from '@mui/material'
import { useQuery } from '@tanstack/react-query'
import { phase6Api, type Phase6Biomarker, type Phase6FeatureImportance, type Phase6ModelMetrics, type Phase6Summary } from '@/api/client'
import { RunHeader } from '@/pages/analysis/shared'

const PAGE_SIZE = 25
const MODEL_LABELS: Record<string, string> = {
  logistic_regression: 'Logistic regression',
  random_forest: 'Random forest',
  svm: 'Linear SVM',
  gradient_boosting: 'Gradient boosting',
}

function formatMetric(value: number | null | undefined) {
  return value == null || !Number.isFinite(value) ? '—' : value.toFixed(3)
}

function evidenceValue(value: unknown) {
  if (value == null || value === '') return 'No matching gene-level annotation in saved run.'
  if (typeof value === 'number') return value.toLocaleString(undefined, { maximumFractionDigits: 4 })
  if (typeof value === 'boolean') return value ? 'Yes' : 'No'
  return String(value)
}

function MetricCard({ label, value, detail }: { label: string; value: string; detail?: string }) {
  return (
    <Card variant="outlined" sx={{ height: '100%' }}>
      <CardContent>
        <Typography variant="caption" color="text.secondary" fontWeight={700}>{label}</Typography>
        <Typography variant="h5" fontWeight={800} sx={{ mt: 0.5 }}>{value}</Typography>
        {detail && <Typography variant="caption" color="text.secondary">{detail}</Typography>}
      </CardContent>
    </Card>
  )
}

function ModelCard({ name, result }: { name: string; result: Phase6ModelMetrics }) {
  const metrics = result.out_of_fold_metrics
  const interval = result.auc_95_percentile_interval
  return (
    <Card variant="outlined" sx={{ height: '100%' }}>
      <CardContent>
        <Typography variant="h6" fontWeight={800} gutterBottom>{MODEL_LABELS[name] ?? name}</Typography>
        <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap" sx={{ mb: 1.5 }}>
          <Chip size="small" color="primary" label={`ROC-AUC ${formatMetric(metrics.roc_auc)}`} />
          <Chip size="small" variant="outlined" label={`PR-AUC ${formatMetric(metrics.pr_auc)}`} />
          <Chip size="small" variant="outlined" label={`${result.n_samples} out-of-fold samples`} />
        </Stack>
        <Table size="small">
          <TableBody>
            {[
              ['Accuracy', metrics.accuracy],
              ['Balanced accuracy', metrics.balanced_accuracy],
              ['Sensitivity', metrics.sensitivity],
              ['Specificity', metrics.specificity],
              ['Precision', metrics.precision],
              ['F1', metrics.f1],
              ['Brier score', metrics.brier_score],
            ].map(([label, value]) => (
              <TableRow key={label as string}>
                <TableCell sx={{ pl: 0 }}>{label}</TableCell>
                <TableCell align="right" sx={{ pr: 0 }}>{formatMetric(value as number | null)}</TableCell>
              </TableRow>
            ))}
            <TableRow>
              <TableCell sx={{ pl: 0 }}>95% AUC interval</TableCell>
              <TableCell align="right" sx={{ pr: 0 }}>
                {interval ? `${formatMetric(interval[0])}–${formatMetric(interval[1])}` : 'Not estimable'}
              </TableCell>
            </TableRow>
            <TableRow>
              <TableCell sx={{ pl: 0 }}>Confusion matrix (TN / FP / FN / TP)</TableCell>
              <TableCell align="right" sx={{ pr: 0 }}>
                {metrics.confusion_matrix.tn} / {metrics.confusion_matrix.fp} / {metrics.confusion_matrix.fn} / {metrics.confusion_matrix.tp}
              </TableCell>
            </TableRow>
          </TableBody>
        </Table>
        <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 1 }}>
          AUC interval resampled by {result.auc_interval_resampling_unit.replace('_', ' ')}.
        </Typography>
      </CardContent>
    </Card>
  )
}

function SavedPlot({ runId, filename, title, species }: {
  runId: string
  filename: string
  title: string
  species: 'human' | 'mouse'
}) {
  const { data, isLoading, isError } = useQuery({
    queryKey: ['phase6-plot', runId, species, filename],
    queryFn: () => phase6Api.artifact(runId, filename, species).then((response) => response.data),
  })
  const [url, setUrl] = useState<string | null>(null)

  useEffect(() => {
    if (!data) {
      setUrl(null)
      return
    }
    const objectUrl = URL.createObjectURL(data)
    setUrl(objectUrl)
    return () => URL.revokeObjectURL(objectUrl)
  }, [data])

  return (
    <Paper variant="outlined" sx={{ p: 2, height: '100%' }}>
      <Typography variant="subtitle1" fontWeight={800} sx={{ mb: 1 }}>{title}</Typography>
      {isLoading && <CircularProgress size={22} />}
      {isError && <Alert severity="error">Could not load the saved {title.toLowerCase()}.</Alert>}
      {url && <Box component="img" src={url} alt={title} sx={{ display: 'block', width: '100%', height: 'auto' }} />}
    </Paper>
  )
}

const FEATURE_GROUP_PAGES: Record<string, { title: string; page: string }> = {
  differential_expression: { title: 'View DEG results', page: 'deg' },
  network_features: { title: 'View networks', page: 'networks' },
  module_features: { title: 'View modules', page: 'modules' },
  orthology_features: { title: 'View orthology', page: 'orthology' },
  network_drift_features: { title: 'View drift results', page: 'drift' },
  pathway_features: { title: 'View pathways', page: 'pathways' },
  morphology_features: { title: 'View morphology results', page: 'morphology' },
}

function FeatureSources({ runId, summary }: { runId: string; summary: Phase6Summary }) {
  return (
    <Paper variant="outlined" sx={{ p: 2 }}>
      <Typography variant="h6" fontWeight={800} sx={{ mb: 0.5 }}>Saved biological results</Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
        Phase 3–5 outputs are shown as available cohort-level annotations. They are not sample-level model inputs, so availability does not imply an ML comparison was evaluated.
      </Typography>
      <Grid container spacing={1.5}>
        {Object.entries(summary.feature_groups).map(([key, group]) => (
          <Grid item xs={12} md={6} key={key}>
            <Paper variant="outlined" sx={{ p: 1.5, height: '100%' }}>
              <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 0.75 }}>
                <Typography fontWeight={700}>{key.replace(/_/g, ' ')}</Typography>
                <Chip
                  size="small"
                  color={['EVALUATED', 'ANNOTATION_AVAILABLE', 'DESCRIPTIVE_METADATA_AVAILABLE'].includes(group.status) ? 'success' : 'default'}
                  label={group.status.replace(/_/g, ' ')}
                />
              </Stack>
              {group.features != null && <Typography variant="body2">{group.features.toLocaleString()} expression features · sample-level</Typography>}
              {group.reason && <Typography variant="body2" color="text.secondary">{group.reason}</Typography>}
              {FEATURE_GROUP_PAGES[key] && group.sources?.length ? (
                <Button
                  component={RouterLink}
                  to={`/runs/${runId}/${FEATURE_GROUP_PAGES[key].page}`}
                  size="small"
                  sx={{ mt: 0.5, px: 0 }}
                >
                  {FEATURE_GROUP_PAGES[key].title}
                </Button>
              ) : null}
            </Paper>
          </Grid>
        ))}
      </Grid>
    </Paper>
  )
}

export default function Phase6MLResultsPage() {
  const { runId = '' } = useParams<{ runId: string }>()
  const [species, setSpecies] = useState<'human' | 'mouse'>('human')
  const [page, setPage] = useState(0)
  const [biomarkerPage, setBiomarkerPage] = useState(0)
  const [featurePage, setFeaturePage] = useState(0)
  const [selectedModel, setSelectedModel] = useState('logistic_regression')
  const summaryQuery = useQuery({
    queryKey: ['phase6-summary', runId, species],
    queryFn: () => phase6Api.summary(runId, species).then((response) => response.data),
    enabled: !!runId,
  })
  const predictionsQuery = useQuery({
    queryKey: ['phase6-predictions', runId, species, page],
    queryFn: () => phase6Api.predictions(runId, PAGE_SIZE, page * PAGE_SIZE, species).then((response) => response.data),
    enabled: !!runId && species === 'human' && !!summaryQuery.data && !('cohorts' in summaryQuery.data),
  })
  const biomarkersQuery = useQuery({
    queryKey: ['phase6-biomarkers', runId, species, biomarkerPage],
    queryFn: () => phase6Api.biomarkers(runId, PAGE_SIZE, biomarkerPage * PAGE_SIZE, species).then((response) => response.data),
    enabled: !!runId && species === 'human' && !!summaryQuery.data && !('cohorts' in summaryQuery.data),
  })
  const featureImportanceQuery = useQuery({
    queryKey: ['phase6-feature-importance', runId, species, selectedModel, featurePage],
    queryFn: () => phase6Api.featureImportance(runId, selectedModel, PAGE_SIZE, featurePage * PAGE_SIZE, species).then((response) => response.data),
    enabled: !!runId && species === 'human' && !!summaryQuery.data && !('cohorts' in summaryQuery.data),
  })
  const summary = summaryQuery.data

  return (
    <Box sx={{ maxWidth: 1400, mx: 'auto' }}>
      <RunHeader
        runId={runId}
        view="ml"
        title="MACHINE LEARNING RESULTS"
        subtitle="Saved Phase 6 model evaluation and validation results for this analysis run"
      />
      <TextField
        select
        size="small"
        label="Species cohort"
        value={species}
        onChange={(event) => {
          const selectedSpecies = event.target.value
          if (selectedSpecies === 'human' || selectedSpecies === 'mouse') {
            setSpecies(selectedSpecies)
          }
          setPage(0)
          setBiomarkerPage(0)
          setFeaturePage(0)
        }}
        sx={{ minWidth: 220, mb: 2 }}
      >
        <MenuItem value="human">Human only</MenuItem>
        <MenuItem value="mouse">Mouse only</MenuItem>
      </TextField>
      {summaryQuery.isLoading && <LinearProgress sx={{ mb: 2 }} />}
      {summaryQuery.isError && (
        <Alert severity="error" sx={{ mb: 2 }}>
          Could not load saved Phase 6 results for this run. Confirm Phase 6 has completed and that you can access this run.
        </Alert>
      )}
      {summary && 'cohorts' in summary && <Paper variant="outlined" sx={{ p: 2, mb: 2 }}>
        <Typography variant="h5" fontWeight={800} sx={{ mb: 1 }}>Mouse-only ML: not estimable</Typography>
        <Alert severity="warning" sx={{ mb: 2 }}>{summary.reason}</Alert>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
          Cohorts stay separate. Pooling a cancer-only study with a healthy-only study would let the model identify the study rather than disease status.
        </Typography>
        <TableContainer>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>Mouse study</TableCell>
                <TableCell>Tissue</TableCell>
                <TableCell align="right">Samples</TableCell>
                <TableCell align="right">Healthy</TableCell>
                <TableCell align="right">Cancer</TableCell>
                <TableCell>ML eligibility</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {summary.cohorts.map((cohort) => (
                <TableRow key={cohort.accession}>
                  <TableCell>{cohort.accession}</TableCell>
                  <TableCell>{cohort.tissue ?? '—'}</TableCell>
                  <TableCell align="right">{cohort.total_samples}</TableCell>
                  <TableCell align="right">{cohort.healthy_samples}</TableCell>
                  <TableCell align="right">{cohort.cancer_samples}</TableCell>
                  <TableCell>
                    {cohort.healthy_samples > 0 && cohort.cancer_samples > 0
                      ? 'Both classes present; not run'
                      : 'Not estimable: single class'}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
        <Typography variant="body2" sx={{ mt: 2 }}>{summary.next_step}</Typography>
      </Paper>}
      {summary && !('cohorts' in summary) && <>
        <Alert severity="warning" sx={{ mb: 2 }}>
          {summary.scientific_scope} These cross-validation results are exploratory, not evidence of clinical performance.
        </Alert>
        <Grid container spacing={1.5} sx={{ mb: 2 }}>
          <Grid item xs={12} sm={6} md={3}>
            <MetricCard label="COHORT" value={summary.data_provenance.accession} detail={`${summary.species} expression cohort`} />
          </Grid>
          <Grid item xs={12} sm={6} md={3}>
            <MetricCard label="SAMPLES" value={summary.sample_counts.total.toLocaleString()} detail={`${summary.sample_counts.class_counts.healthy} healthy · ${summary.sample_counts.class_counts.cancer} cancer`} />
          </Grid>
          <Grid item xs={12} sm={6} md={3}>
            <MetricCard label="PATIENT GROUPS" value={summary.sample_counts.independent_patient_groups?.toLocaleString() ?? 'Not available'} detail={summary.validation_split.grouped_by_patient ? 'Kept intact between folds' : 'Not patient-grouped'} />
          </Grid>
          <Grid item xs={12} sm={6} md={3}>
            <MetricCard label="VALIDATION" value={summary.independent_validation.status} detail={summary.validation_split.name + ` · ${summary.validation_split.folds} folds`} />
          </Grid>
        </Grid>
        <Alert severity="info" sx={{ mb: 2 }}>
          <strong>Preprocessing audit:</strong> {evidenceValue(summary.preprocessing.matched_labeled_samples)} labeled samples matched to expression;
          {' '}{evidenceValue(summary.preprocessing.unlabeled_samples_excluded)} unlabeled and {evidenceValue(summary.preprocessing.labeled_samples_missing_from_expression)} unmatched samples excluded;
          {' '}{evidenceValue(summary.preprocessing.missing_expression_cells)} missing expression cells (median imputation fitted within training folds);
          {' '}{evidenceValue(summary.preprocessing.constant_features_before_fold_filtering)} constant features before fold-local filtering.
        </Alert>

        <Paper variant="outlined" sx={{ p: 2, mb: 2 }}>
          <Typography variant="h6" fontWeight={800} sx={{ mb: 1 }}>Model comparison</Typography>
          <TableContainer>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>Model</TableCell>
                  <TableCell align="right">ROC-AUC</TableCell>
                  <TableCell align="right">F1</TableCell>
                  <TableCell align="right">Sensitivity</TableCell>
                  <TableCell align="right">Specificity</TableCell>
                  <TableCell>AUC 95% interval</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {summary.model_comparison.map((row) => (
                  <TableRow key={row.model}>
                    <TableCell>{MODEL_LABELS[row.model] ?? row.model}</TableCell>
                    <TableCell align="right">{formatMetric(row.metrics.roc_auc)}</TableCell>
                    <TableCell align="right">{formatMetric(row.metrics.f1)}</TableCell>
                    <TableCell align="right">{formatMetric(row.metrics.sensitivity)}</TableCell>
                    <TableCell align="right">{formatMetric(row.metrics.specificity)}</TableCell>
                    <TableCell>{row.auc_95_percentile_interval
                      ? `${formatMetric(row.auc_95_percentile_interval[0])}–${formatMetric(row.auc_95_percentile_interval[1])} (${row.interval_resampling_unit.replace('_', ' ')})`
                      : 'Not estimable'}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>
        </Paper>

        <Typography variant="h5" fontWeight={800} sx={{ mb: 1.5 }}>Out-of-fold model results</Typography>
        <Grid container spacing={1.5} sx={{ mb: 2 }}>
          {Object.entries(summary.models).map(([name, result]) => (
            <Grid item xs={12} md={6} key={name}>
              <ModelCard name={name} result={result} />
            </Grid>
          ))}
        </Grid>

        <Grid container spacing={1.5} sx={{ mb: 2 }}>
          {[
            ['roc_curves.svg', 'ROC curves'],
            ['precision_recall_curves.svg', 'Precision-recall curves'],
            ['calibration_curves.svg', 'Calibration curves'],
          ].map(([filename, title]) => (
            <Grid item xs={12} lg={4} key={filename}>
              <SavedPlot runId={runId} filename={filename} title={title} species={species} />
            </Grid>
          ))}
        </Grid>

        <Box sx={{ mb: 2 }}><FeatureSources runId={runId} summary={summary} /></Box>
        <Paper variant="outlined" sx={{ p: 2, mb: 2 }}>
          <Typography variant="h6" fontWeight={800} sx={{ mb: 0.5 }}>Feature-group and ablation comparison</Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
            DEG, hub, and cross-species drift panels are re-derived within each patient-grouped training fold. Drift uses a fixed mouse network from a separate study, so study and network-density differences may dominate the score; it is not an independent validation or sample-level drift measurement. Candidate panels are exploratory and are not clinically validated biomarkers.
          </Typography>
          <TableContainer>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>Comparison</TableCell>
                  <TableCell>Status</TableCell>
                  <TableCell>Feature groups</TableCell>
                  <TableCell>ROC-AUC</TableCell>
                  <TableCell>PR-AUC</TableCell>
                  <TableCell>F1</TableCell>
                  <TableCell>Sensitivity</TableCell>
                  <TableCell>Specificity</TableCell>
                  <TableCell>Balanced accuracy</TableCell>
                  <TableCell>Brier</TableCell>
                  <TableCell>Δ ROC-AUC</TableCell>
                  <TableCell>Δ PR-AUC</TableCell>
                  <TableCell>Reason / interpretation</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {summary.feature_group_comparison
                  .filter((comparison) => comparison.status !== 'NOT_EVALUATED')
                  .map((comparison) => {
                  const modelMetric = comparison.model_metrics?.logistic_regression
                  return (
                    <TableRow key={comparison.comparison} hover>
                      <TableCell>{comparison.comparison}</TableCell>
                      <TableCell>
                        <Chip
                          size="small"
                          label={comparison.status.replace(/_/g, ' ')}
                          color={comparison.status === 'EVALUATED' ? 'success' : comparison.status.includes('AVAILABLE') || comparison.status === 'NOT_EVALUATED' ? 'warning' : 'default'}
                        />
                      </TableCell>
                      <TableCell>{comparison.feature_groups.join(', ')}</TableCell>
                      <TableCell>{formatMetric(modelMetric?.roc_auc)}</TableCell>
                      <TableCell>{formatMetric(modelMetric?.pr_auc)}</TableCell>
                      <TableCell>{formatMetric(modelMetric?.f1)}</TableCell>
                      <TableCell>{formatMetric(modelMetric?.sensitivity)}</TableCell>
                      <TableCell>{formatMetric(modelMetric?.specificity)}</TableCell>
                      <TableCell>{formatMetric(modelMetric?.balanced_accuracy)}</TableCell>
                      <TableCell>{formatMetric(modelMetric?.brier_score)}</TableCell>
                      <TableCell>{formatMetric(comparison.delta_from_expression_baseline?.roc_auc)}</TableCell>
                      <TableCell>{formatMetric(comparison.delta_from_expression_baseline?.pr_auc)}</TableCell>
                      <TableCell sx={{ minWidth: 320 }}>{comparison.reason}</TableCell>
                    </TableRow>
                  )
                })}
              </TableBody>
            </Table>
          </TableContainer>
        </Paper>

        {summary.biological_experiments && <Paper variant="outlined" sx={{ p: 2, mb: 2 }}>
          <Typography variant="h6" fontWeight={800} sx={{ mb: 0.5 }}>Fold-local DEG, hub, and drift candidates</Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
            Candidate genes are reported only from evaluated fold-local experiments. Selection frequency is the fraction of patient-grouped training folds that selected the gene; coefficients are model-specific and exploratory, not evidence of clinical biomarker validity.
          </Typography>
          <TableContainer>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>Experiment</TableCell>
                  <TableCell>Gene ID</TableCell>
                  <TableCell>Training-fold evidence</TableCell>
                  <TableCell align="right">Fold stability</TableCell>
                  <TableCell align="right">Mean |coefficient|</TableCell>
                  <TableCell align="right">Mean drift score</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {Object.entries(summary.biological_experiments.experiments).flatMap(([experimentId, experiment]) =>
                  experiment.candidate_features.map((candidate) => (
                    <TableRow key={`${experimentId}-${candidate.gene_id}`} hover>
                      <TableCell>{experiment.label}</TableCell>
                      <TableCell>
                        {candidate.gene_symbol && <Typography variant="body2" fontWeight={700}>{candidate.gene_symbol}</Typography>}
                        <Typography variant="caption" color="text.secondary">{candidate.gene_id}</Typography>
                      </TableCell>
                      <TableCell>
                        {[
                          candidate.selected_as_deg && 'DEG-ranked',
                          candidate.selected_as_hub && 'network hub',
                          candidate.selected_as_drift && 'drift-weighted',
                        ].filter(Boolean).join(', ') || 'integrated candidate'}
                      </TableCell>
                      <TableCell align="right">
                        {candidate.folds_selected}/{experiment.folds_total} ({formatMetric(candidate.selection_frequency)})
                      </TableCell>
                      <TableCell align="right">{formatMetric(candidate.mean_absolute_coefficient)}</TableCell>
                      <TableCell align="right">{formatMetric(candidate.mean_drift_score)}</TableCell>
                    </TableRow>
                  )),
                )}
              </TableBody>
            </Table>
          </TableContainer>
        </Paper>}

        <Paper variant="outlined" sx={{ p: 2, mb: 2 }}>
          <Typography variant="h6" fontWeight={800} sx={{ mb: 0.5 }}>Predictive gene candidates and cross-species evidence</Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
            Ranked using agreement between fold-local model ranks; gene-level Phase 3–5 annotations are context only and were not supplied to the classifiers. These are predictive features, not clinically validated biomarkers.
          </Typography>
          {biomarkersQuery.isError && <Alert severity="error" sx={{ mb: 1 }}>Could not load the saved predictive-gene annotations.</Alert>}
          {biomarkersQuery.isLoading && <LinearProgress sx={{ mb: 1 }} />}
          {biomarkersQuery.data && <>
            <TableContainer>
              <Table size="small">
                <TableHead>
                  <TableRow>
                    <TableCell>Gene</TableCell>
                    <TableCell align="right">Mean model rank</TableCell>
                    <TableCell align="right">Models selected</TableCell>
                    <TableCell>DEG evidence</TableCell>
                    <TableCell>Network / module</TableCell>
                    <TableCell>Mouse ortholog / network</TableCell>
                    <TableCell>Drift</TableCell>
                    <TableCell>Pathway evidence</TableCell>
                    <TableCell>Morphology</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {biomarkersQuery.data.items.map((candidate: Phase6Biomarker) => (
                    <TableRow key={candidate.gene_id} hover>
                      <TableCell sx={{ minWidth: 150 }}>
                        <Typography variant="body2" fontWeight={700}>{evidenceValue(candidate.gene_symbol)}</Typography>
                        <Typography variant="caption" color="text.secondary">{candidate.gene_id}</Typography>
                      </TableCell>
                      <TableCell align="right">{evidenceValue(candidate.mean_model_rank)}</TableCell>
                      <TableCell align="right">
                        {evidenceValue(candidate.models_with_gene_selected)}
                        {candidate.mean_selection_frequency_across_models != null && (
                          <Typography variant="caption" display="block" color="text.secondary">
                            {formatMetric(candidate.mean_selection_frequency_across_models)} mean fold frequency
                          </Typography>
                        )}
                      </TableCell>
                      <TableCell sx={{ minWidth: 130 }}>
                        {candidate.deg_significant == null
                          ? 'No matching gene-level DEG row in the saved results.'
                          : `${candidate.deg_significant ? 'Significant' : 'Not significant'}; log2FC ${evidenceValue(candidate.deg_log2fc)}; FDR ${evidenceValue(candidate.deg_adjusted_p_value)}`}
                      </TableCell>
                      <TableCell sx={{ minWidth: 140 }}>
                        Degree {evidenceValue(candidate.network_degree)}; module {evidenceValue(candidate.network_module_id)}; hub {evidenceValue(candidate.hub_supported)}
                      </TableCell>
                      <TableCell sx={{ minWidth: 180 }}>
                        {evidenceValue(candidate.mouse_symbol ?? candidate.mouse_ensembl_id)}
                        <Typography variant="caption" display="block">Expression: {evidenceValue(candidate.mouse_expression_status)}</Typography>
                        <Typography variant="caption" display="block">Network: {evidenceValue(candidate.mouse_cancer_network_status)}</Typography>
                        <Typography variant="caption" display="block">Orthology: {evidenceValue(candidate.orthology_type)}</Typography>
                      </TableCell>
                      <TableCell sx={{ minWidth: 130 }}>
                        {evidenceValue(candidate.drift_category)}; score {evidenceValue(candidate.drift_score)}
                      </TableCell>
                      <TableCell sx={{ minWidth: 180 }}>
                        {evidenceValue(candidate.enriched_pathway_names)}
                        {candidate.key_drifted_pathway_names && `; key drifted: ${candidate.key_drifted_pathway_names}`}
                      </TableCell>
                      <TableCell sx={{ minWidth: 150 }}>{evidenceValue(candidate.morphology_status)}</TableCell>
                    </TableRow>
                  ))}
                  {!biomarkersQuery.data.items.length && <TableRow><TableCell colSpan={9}>No predictive gene candidates were produced.</TableCell></TableRow>}
                </TableBody>
              </Table>
            </TableContainer>
            <TablePagination
              component="div"
              count={biomarkersQuery.data.total}
              page={biomarkerPage}
              onPageChange={(_, nextPage) => setBiomarkerPage(nextPage)}
              rowsPerPage={PAGE_SIZE}
              onRowsPerPageChange={() => undefined}
              rowsPerPageOptions={[PAGE_SIZE]}
            />
          </>}
        </Paper>

        <Paper variant="outlined" sx={{ p: 2, mb: 2 }}>
          <Stack direction={{ xs: 'column', sm: 'row' }} justifyContent="space-between" spacing={1.5} sx={{ mb: 1 }}>
            <Box>
              <Typography variant="h6" fontWeight={800}>Fold-derived importance by model</Typography>
              <Typography variant="body2" color="text.secondary">Rankings aggregate held-out training-fold feature importance; the final full-cohort fit is not used for this table.</Typography>
            </Box>
            <TextField
              select
              size="small"
              label="Model"
              value={selectedModel}
              onChange={(event) => { setSelectedModel(event.target.value); setFeaturePage(0) }}
              sx={{ minWidth: 220 }}
            >
              {Object.keys(summary.models).map((model) => <MenuItem key={model} value={model}>{MODEL_LABELS[model] ?? model}</MenuItem>)}
            </TextField>
          </Stack>
          {featureImportanceQuery.isError && <Alert severity="error" sx={{ mb: 1 }}>Could not load fold-derived feature importance.</Alert>}
          {featureImportanceQuery.isLoading && <LinearProgress sx={{ mb: 1 }} />}
          {featureImportanceQuery.data && <>
            <TableContainer>
              <Table size="small">
                <TableHead><TableRow>
                  <TableCell>Gene ID</TableCell>
                  <TableCell align="right">Importance</TableCell>
                  <TableCell align="right">Selected folds</TableCell>
                  <TableCell align="right">Selection frequency</TableCell>
                  <TableCell>Direction</TableCell>
                  <TableCell>Method</TableCell>
                </TableRow></TableHead>
                <TableBody>
                  {featureImportanceQuery.data.items.map((feature: Phase6FeatureImportance) => (
                    <TableRow key={feature.gene_id} hover>
                      <TableCell>{feature.gene_id}</TableCell>
                      <TableCell align="right">{formatMetric(feature.importance)}</TableCell>
                      <TableCell align="right">{feature.selected_folds}</TableCell>
                      <TableCell align="right">{formatMetric(feature.selection_frequency)}</TableCell>
                      <TableCell>{feature.direction}</TableCell>
                      <TableCell>{feature.importance_method}</TableCell>
                    </TableRow>
                  ))}
                  {!featureImportanceQuery.data.items.length && <TableRow><TableCell colSpan={6}>No fold-derived importance was saved for this model.</TableCell></TableRow>}
                </TableBody>
              </Table>
            </TableContainer>
            <TablePagination
              component="div"
              count={featureImportanceQuery.data.total}
              page={featurePage}
              onPageChange={(_, nextPage) => setFeaturePage(nextPage)}
              rowsPerPage={PAGE_SIZE}
              onRowsPerPageChange={() => undefined}
              rowsPerPageOptions={[PAGE_SIZE]}
            />
          </>}
        </Paper>

        <Alert severity="info" sx={{ mb: 2 }}>
          <strong>Independent validation {summary.independent_validation.status.toLowerCase()}:</strong> {summary.independent_validation.reason}
        </Alert>
        <Alert severity="info" sx={{ mb: 2 }}>
          <strong>Cross-species interpretation:</strong> {summary.cross_species_analysis.interpretation}
        </Alert>
        <Alert severity="info" sx={{ mb: 2 }}>
          <strong>Biological interpretation:</strong> gene-level pathway, module, and morphology fields are annotations from saved PathDrift analyses, not independently scored predictive pathway/module models. Not available from current PathDrift data as per-sample predictors.
        </Alert>

        <Paper variant="outlined" sx={{ p: 2, mb: 2 }}>
          <Typography variant="h6" fontWeight={800} sx={{ mb: 0.5 }}>Out-of-fold predictions</Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
            Each row is a held-out prediction. Labels: 0 = healthy, 1 = cancer.
          </Typography>
          {predictionsQuery.isError && <Alert severity="error" sx={{ mb: 1 }}>Could not load saved out-of-fold predictions.</Alert>}
          {predictionsQuery.isLoading && <LinearProgress sx={{ mb: 1 }} />}
          {predictionsQuery.data && <>
            <TableContainer>
              <Table size="small">
                <TableHead>
                  <TableRow>
                    <TableCell>Sample</TableCell>
                    <TableCell>Model</TableCell>
                    <TableCell align="right">Fold</TableCell>
                    <TableCell align="right">True label</TableCell>
                    <TableCell align="right">Cancer probability</TableCell>
                    <TableCell align="right">Predicted label</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {predictionsQuery.data.items.map((prediction) => (
                    <TableRow key={`${prediction.model}-${prediction.sample_id}`} hover>
                      <TableCell>{prediction.sample_id}</TableCell>
                      <TableCell>{MODEL_LABELS[prediction.model] ?? prediction.model}</TableCell>
                      <TableCell align="right">{prediction.fold}</TableCell>
                      <TableCell align="right">{prediction.true_label}</TableCell>
                      <TableCell align="right">{formatMetric(prediction.predicted_probability)}</TableCell>
                      <TableCell align="right">{prediction.predicted_label}</TableCell>
                    </TableRow>
                  ))}
                  {!predictionsQuery.data.items.length && <TableRow><TableCell colSpan={6}>No out-of-fold predictions were saved.</TableCell></TableRow>}
                </TableBody>
              </Table>
            </TableContainer>
            <TablePagination
              component="div"
              count={predictionsQuery.data.total}
              page={page}
              onPageChange={(_, nextPage) => setPage(nextPage)}
              rowsPerPage={PAGE_SIZE}
              onRowsPerPageChange={() => undefined}
              rowsPerPageOptions={[PAGE_SIZE]}
            />
          </>}
        </Paper>

        <Typography variant="caption" color="text.secondary">
          Seed {summary.seed} · Completed {new Date(summary.completed_at).toLocaleString()} ·
          {' '}Fold-local selection: {summary.models.logistic_regression?.feature_selection ?? 'as recorded in the saved model results'}
        </Typography>
      </>}
    </Box>
  )
}
