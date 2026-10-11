import { useEffect, useState } from 'react'
import { Link as RouterLink } from 'react-router-dom'
import {
  Box, Grid, Paper, Typography, Chip, Alert, Button, TextField, MenuItem, LinearProgress,
  Stack, Divider,
} from '@mui/material'
import { ArrowForward } from '@mui/icons-material'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { analysisApi, healthApi, phase3Api, phase4Api, phase5Api, projectApi } from '@/api/client'
import { useProjectStore } from '@/store/projectStore'
import { useAuthStore } from '@/store/authStore'
import type { Run, RunDataset, Summary } from './analysis/shared'

const EMPTY_PROJECTS: Array<{ id: string; name: string }> = []
const EMPTY_ANALYSES: Array<{ id: string; name: string }> = []
function StatCard({ label, value, color }: { label: string; value: string | number; color: string }) {
  return (
    <Paper
      sx={{
        p: 2.25,
        minHeight: 116,
        display: 'flex',
        flexDirection: 'column',
        justifyContent: 'space-between',
        borderTop: `3px solid ${color}`,
      }}
      elevation={0}
      variant="outlined"
    >
      <Typography variant="caption" sx={{ color: 'text.secondary', fontWeight: 700, letterSpacing: '0.08em' }}>
        {label}
      </Typography>
      <Typography sx={{ color, fontSize: 30, fontWeight: 800, lineHeight: 1.1 }}>
        {value}
      </Typography>
    </Paper>
  )
}

export default function DashboardPage() {
  const queryClient = useQueryClient()
  const { currentProjectId, currentAnalysisId, currentRunId, setCurrentProject, setCurrentAnalysis, setCurrentRun } = useProjectStore()
  const userId = useAuthStore((state) => state.user?.id)
  const [projectName, setProjectName] = useState('')
  const [projectError, setProjectError] = useState<string | null>(null)

  const { data: health } = useQuery({
    queryKey: ['health'],
    queryFn: () => healthApi.check().then(r => r.data),
    refetchInterval: 30_000,
  })

  const { data: projects = EMPTY_PROJECTS, isLoading: projectsLoading } = useQuery({
    queryKey: ['projects'],
    queryFn: () => projectApi.list().then(r => r.data),
  })

  const { data: analyses = EMPTY_ANALYSES, isLoading: analysesLoading } = useQuery({
    queryKey: ['analyses', currentProjectId],
    queryFn: () => currentProjectId ? analysisApi.listForProject(currentProjectId).then(r => r.data) : [],
    enabled: !!currentProjectId,
  })

  const { data: savedRuns = [], isLoading: runsLoading, isError: runsError, error: savedRunsQueryError } = useQuery({
    queryKey: ['saved-analysis-runs', userId],
    queryFn: () => phase3Api.savedRuns().then((response) => response.data as Run[]),
  })
  const selectedRunId = savedRuns.some((run) => run.id === currentRunId) ? currentRunId! : ''
  const { data: runSummary, isLoading: runSummaryLoading, isError: runSummaryError } = useQuery({
    queryKey: ['phase3-summary', selectedRunId],
    queryFn: () => phase3Api.summary(selectedRunId).then((response) => response.data as Summary),
    enabled: !!selectedRunId,
  })
  const { data: runDatasets = [], isLoading: runDatasetsLoading, isError: runDatasetsError } = useQuery({
    queryKey: ['phase3-datasets', selectedRunId],
    queryFn: () => phase3Api.datasets(selectedRunId).then((response) => response.data as RunDataset[]),
    enabled: !!selectedRunId,
  })
  const { data: runArtifacts, isLoading: runArtifactsLoading, isError: runArtifactsError } = useQuery({
    queryKey: ['run-artifacts', selectedRunId],
    queryFn: () => phase3Api.artifacts(selectedRunId).then((response) => response.data as {
      total: number
      items: Array<{ section: string; path: string; name: string; size_bytes: number }>
    }),
    enabled: !!selectedRunId,
  })
  const { data: runOrthology } = useQuery({
    queryKey: ['phase4-orthology-summary', selectedRunId],
    queryFn: () => phase4Api.orthologySummary(selectedRunId).then((response) => response.data as Record<string, unknown>),
    enabled: !!selectedRunId,
  })
  const { data: runCrossSpecies } = useQuery({
    queryKey: ['phase4-cross-species-summary', selectedRunId],
    queryFn: () => phase4Api.crossSpeciesSummary(selectedRunId).then((response) => response.data as Record<string, unknown>),
    enabled: !!selectedRunId,
  })
  const { data: pathwayResults } = useQuery({
    queryKey: ['dashboard-pathways', selectedRunId],
    queryFn: () => phase5Api.table(selectedRunId, 'pathway-enrichment', 5, 0, { significant_only: true })
      .then((response) => response.data as { items: Array<Record<string, string | null>>; total: number }),
    enabled: !!selectedRunId,
  })

  useEffect(() => {
    if (!projectsLoading && !currentProjectId && projects.length > 0) {
      setCurrentProject(projects[0].id)
    }
  }, [currentProjectId, projects, projectsLoading, setCurrentProject])

  useEffect(() => {
    if (analysesLoading) return

    if (!currentProjectId) {
      if (currentAnalysisId) setCurrentAnalysis(null)
      return
    }

    const analysisBelongsToProject = analyses.some((analysis) => analysis.id === currentAnalysisId)
    const nextAnalysisId = analyses[0]?.id ?? null
    if (!analysisBelongsToProject && currentAnalysisId !== nextAnalysisId) {
      setCurrentAnalysis(nextAnalysisId)
    }
  }, [analysesLoading, currentProjectId, currentAnalysisId, analyses, setCurrentAnalysis])

  useEffect(() => {
    if (runsLoading || !savedRuns.length || savedRuns.some((run) => run.id === currentRunId)) return
    setCurrentRun(savedRuns.find((run) => run.status.toUpperCase() === 'COMPLETED')?.id ?? savedRuns[0].id)
  }, [currentRunId, runsLoading, savedRuns, setCurrentRun])

  const createProjectMutation = useMutation({
    mutationKey: ['projects', 'create'],
    mutationFn: async () => {
      const name = projectName.trim()
      if (!name) throw new Error('Project name is required')

      return projectApi.create({ name, is_public: false })
    },
    onSuccess: (response) => {
      queryClient.invalidateQueries({ queryKey: ['projects'] })
      setCurrentProject(response.data.id)
      setProjectName('')
      setProjectError(null)
    },
    onError: (error: unknown) => {
      const detail = (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setProjectError(detail || 'Unable to create project')
    },
  })

  const createAnalysisMutation = useMutation({
    mutationKey: ['analyses', 'create'],
    mutationFn: async () => {
      if (!currentProjectId) throw new Error('Select a project first')
      const name = `Analysis ${new Date().toLocaleString()}`
      return analysisApi.create({ project_id: currentProjectId, name, description: 'Auto-created analysis workflow' })
    },
    onSuccess: (response) => {
      queryClient.invalidateQueries({ queryKey: ['analyses'] })
      setCurrentAnalysis(response.data.id)
    },
    onError: () => {
      setProjectError('Unable to create analysis')
    },
  })

  const selectedProject = projects.find((project) => project.id === currentProjectId) ?? null
  const selectedRun = savedRuns.find((run) => run.id === selectedRunId) ?? null
  const humanSamples = runDatasets.filter((dataset) => dataset.species === 'human')
    .reduce((total, dataset) => total + (dataset.sample_count ?? 0), 0)
  const mouseSamples = runDatasets.filter((dataset) => dataset.species === 'mouse')
    .reduce((total, dataset) => total + (dataset.sample_count ?? 0), 0)
  const significantDegs = runSummary?.differential_expression.reduce((total, result) => total + result.significant_genes, 0) ?? 0
  const humanDegs = runSummary?.differential_expression
    .filter((result) => result.species.toLowerCase() === 'human')
    .reduce((total, result) => total + result.significant_genes, 0)
  const mouseDegs = runSummary?.differential_expression
    .filter((result) => result.species.toLowerCase() === 'mouse')
    .reduce((total, result) => total + result.significant_genes, 0)
  const resultSections = [...new Set(runArtifacts?.items.map((artifact) => artifact.section) ?? [])]
  const runPages: Record<string, { label: string; path: string }> = {
    deg: { label: 'Differential expression', path: 'deg' },
    networks: { label: 'Networks', path: 'network-explorer' },
    drift: { label: 'Network drift', path: 'drift' },
    cross_species: { label: 'Cross-species comparison', path: 'cross-species' },
    orthology: { label: 'Orthology', path: 'orthology' },
    pathways: { label: 'Pathway enrichment', path: 'pathways' },
    modules: { label: 'Modules', path: 'modules' },
    hub_genes: { label: 'Hub genes', path: 'hub-genes' },
    biomarkers: { label: 'Biomarkers', path: 'biomarkers' },
    gene_loss: { label: 'Gene loss', path: 'gene-loss' },
    ml: { label: 'Machine learning', path: 'ml' },
    morphology: { label: 'Morphology', path: 'morphology' },
  }
  const crossSpecies = runCrossSpecies ?? {}
  const conservationPercent = typeof crossSpecies.edge_conservation_rate === 'number'
    ? crossSpecies.edge_conservation_rate * 100
    : null
  const pathways = pathwayResults?.items ?? []
  const formatNumber = (value: unknown) =>
    typeof value === 'number' ? value.toLocaleString() : value == null ? '—' : String(value)

  return (
    <Box sx={{ maxWidth: 1280, mx: 'auto' }}>
      <Typography variant="h4" fontWeight={800} sx={{ letterSpacing: '0.04em' }}>
        PATHDRIFT
      </Typography>
      <Typography variant="body1" color="text.secondary" sx={{ mb: 2.5 }}>
        Cross-Species Breast Cancer Analysis
      </Typography>

      {health?.status !== 'ok' && (
        <Alert severity="warning" sx={{ mb: 2 }}>
          Backend API is not reachable. Ensure the backend server is running.
        </Alert>
      )}

      <Paper sx={{ p: 2, mb: 3 }} elevation={0} variant="outlined">
        <Grid container spacing={1.5} alignItems="center">
          <Grid item xs={12} md={3}>
            <TextField
              select
              size="small"
              label="Project"
              value={currentProjectId ?? ''}
              onChange={(event) => setCurrentProject(event.target.value || null)}
              fullWidth
              disabled={projects.length === 0}
            >
              {projects.map((project) => <MenuItem key={project.id} value={project.id}>{project.name}</MenuItem>)}
            </TextField>
          </Grid>
          <Grid item xs={12} md={4}>
            <TextField
              select
              size="small"
              label="Analysis"
              value={currentAnalysisId ?? ''}
              onChange={(event) => setCurrentAnalysis(event.target.value || null)}
              fullWidth
              disabled={analyses.length === 0}
            >
              {analyses.map((analysis) => <MenuItem key={analysis.id} value={analysis.id}>{analysis.name}</MenuItem>)}
            </TextField>
          </Grid>
          <Grid item xs={12} md={2}>
            <Button
              variant="outlined"
              fullWidth
              onClick={() => createAnalysisMutation.mutate()}
              disabled={!currentProjectId || createAnalysisMutation.isPending}
            >
              {createAnalysisMutation.isPending ? 'Creating...' : 'New analysis'}
            </Button>
          </Grid>
          <Grid item xs={12} md={3}>
            <Stack direction="row" spacing={1}>
              <TextField
                size="small"
                label="New project"
                value={projectName}
                onChange={(event) => setProjectName(event.target.value)}
                fullWidth
              />
              <Button
                variant="contained"
                onClick={() => createProjectMutation.mutate()}
                disabled={!projectName.trim() || createProjectMutation.isPending}
              >
                Create
              </Button>
            </Stack>
          </Grid>
          {selectedProject && (
            <Grid item xs={12}>
              <Chip size="small" label={`Active project: ${selectedProject.name}`} color="primary" variant="outlined" />
            </Grid>
          )}
          {projectError && <Grid item xs={12}><Alert severity="error">{projectError}</Alert></Grid>}
        </Grid>
      </Paper>

      <Paper sx={{ p: { xs: 2, md: 3 }, mb: 3 }} elevation={0} variant="outlined">
        <Stack direction={{ xs: 'column', md: 'row' }} justifyContent="space-between" alignItems={{ xs: 'stretch', md: 'center' }} spacing={2} sx={{ mb: 2 }}>
          <Box>
            <Typography variant="h6" fontWeight={700}>Selected analysis run</Typography>
            <Typography variant="body2" color="text.secondary">
              Run-level overview and shortcuts to results already saved for this analysis.
            </Typography>
          </Box>
          {!!savedRuns.length && (
            <TextField
              select
              size="small"
              label="Saved run"
              value={selectedRunId}
              onChange={(event) => setCurrentRun(event.target.value || null)}
              sx={{ minWidth: { xs: '100%', md: 380 } }}
            >
              {savedRuns.map((run) => (
                <MenuItem key={run.id} value={run.id}>
                  {run.project_name ?? 'Saved analysis'} · {new Date(run.created_at).toLocaleString()} · {run.status}
                </MenuItem>
              ))}
            </TextField>
          )}
        </Stack>

        {runsLoading && <LinearProgress sx={{ mb: 2 }} />}
        {runsError && (
          <Alert severity="error" sx={{ mb: 2 }}>
            Saved analysis runs could not be loaded.
            {(savedRunsQueryError as Error | undefined)?.message ? ` ${savedRunsQueryError.message}` : ''}
          </Alert>
        )}
        {!runsLoading && !runsError && !savedRuns.length && (
          <Alert severity="info" sx={{ mb: 1 }}>No saved analysis runs are available yet.</Alert>
        )}
        {!!selectedRun && (
          <>
            <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap" sx={{ mb: 2 }}>
              <Chip size="small" label={`Run ${selectedRun.id}`} />
              <Chip size="small" color={selectedRun.status.toUpperCase() === 'COMPLETED' ? 'success' : 'default'} label={selectedRun.status} />
              <Chip size="small" variant="outlined" label={`Created ${new Date(selectedRun.created_at).toLocaleString()}`} />
              {selectedRun.stage && <Chip size="small" variant="outlined" label={`Stage: ${selectedRun.stage}`} />}
            </Stack>
            {(runSummaryLoading || runDatasetsLoading || runArtifactsLoading) && <LinearProgress sx={{ mb: 2 }} />}
            {(runSummaryError || runDatasetsError || runArtifactsError) && (
              <Alert severity="error" sx={{ mb: 2 }}>Some saved run details could not be loaded.</Alert>
            )}
            {!runSummaryError && !runDatasetsError && !runArtifactsError && (
              <Grid container spacing={1.5} sx={{ mb: 2 }}>
                <Grid item xs={6} md={3}>
                  <StatCard label="DATASETS" value={runDatasetsLoading ? '…' : runDatasets.length} color="#1677a8" />
                </Grid>
                <Grid item xs={6} md={3}>
                  <StatCard label="HUMAN SAMPLES" value={runDatasetsLoading ? '…' : humanSamples.toLocaleString()} color="#4361a8" />
                </Grid>
                <Grid item xs={6} md={3}>
                  <StatCard label="MOUSE SAMPLES" value={runDatasetsLoading ? '…' : mouseSamples.toLocaleString()} color="#be5a32" />
                </Grid>
                <Grid item xs={6} md={3}>
                  <StatCard label="SIGNIFICANT DEGs" value={runSummaryLoading ? '…' : significantDegs.toLocaleString()} color="#9a5b91" />
                </Grid>
                <Grid item xs={6} md={3}>
                  <StatCard label="NETWORKS" value={runSummaryLoading ? '…' : runSummary?.networks.length ?? 0} color="#25856b" />
                </Grid>
                <Grid item xs={6} md={3}>
                  <StatCard label="RESULT FILES" value={runArtifactsLoading ? '…' : runArtifacts?.total ?? 0} color="#b27b1f" />
                </Grid>
                <Grid item xs={6} md={3}>
                  <StatCard label="RESULT AREAS" value={runArtifactsLoading ? '…' : resultSections.length} color="#5364a5" />
                </Grid>
              </Grid>
            )}
            {!runArtifactsLoading && !runArtifactsError && resultSections.length > 0 && (
              <Box>
                <Typography variant="subtitle2" fontWeight={700} sx={{ mb: 1 }}>Available saved results</Typography>
                <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap">
                  {resultSections.map((section) => {
                    const page = runPages[section]
                    return page ? (
                      <Button
                        key={section}
                        size="small"
                        variant="outlined"
                        component={RouterLink}
                        to={`/runs/${selectedRunId}/${page.path}`}
                        endIcon={<ArrowForward />}
                      >
                        {page.label}
                      </Button>
                    ) : (
                      <Chip key={section} variant="outlined" label={section.replace(/_/g, ' ')} />
                    )
                  })}
                  <Button size="small" variant="contained" component={RouterLink} to="/reports">
                    Browse & download all
                  </Button>
                </Stack>
              </Box>
            )}
          </>
        )}
      </Paper>

      {!currentProjectId && !projectsLoading && (
        <Alert severity="info" sx={{ mb: 2 }}>Create a project to see its sample and analysis summary.</Alert>
      )}

      <Grid container spacing={2} sx={{ mb: 3 }}>
        <Grid item xs={12} sm={6} md={4}>
          <StatCard label="HUMAN SAMPLES" value={runDatasetsLoading ? '…' : selectedRun ? humanSamples.toLocaleString() : '—'} color="#1677a8" />
        </Grid>
        <Grid item xs={12} sm={6} md={4}>
          <StatCard label="MOUSE SAMPLES" value={runDatasetsLoading ? '…' : selectedRun ? mouseSamples.toLocaleString() : '—'} color="#be5a32" />
        </Grid>
        <Grid item xs={12} sm={6} md={4}>
          <StatCard label="ORTHOLOGS" value={formatNumber(runOrthology?.total_orthology_mappings)} color="#25856b" />
        </Grid>
        <Grid item xs={12} sm={6} md={4}>
          <StatCard label="HUMAN DEGs" value={runSummaryLoading ? '…' : humanDegs?.toLocaleString() ?? '—'} color="#4361a8" />
        </Grid>
        <Grid item xs={12} sm={6} md={4}>
          <StatCard label="MOUSE DEGs" value={runSummaryLoading ? '…' : mouseDegs?.toLocaleString() ?? '—'} color="#9a5b91" />
        </Grid>
        <Grid item xs={12} sm={6} md={4}>
          <StatCard label="ALIGNED DRIFT GENES" value={formatNumber(crossSpecies.aligned_gene_count)} color="#b27b1f" />
        </Grid>
      </Grid>

      <Paper sx={{ p: { xs: 2, md: 3 }, mb: 3 }} elevation={0} variant="outlined">
        <Typography variant="h6" fontWeight={700} gutterBottom>CROSS-SPECIES SUMMARY</Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2.5 }}>
          {runCrossSpecies
            ? `Saved comparison from run ${selectedRunId}.`
            : selectedRun
              ? 'No completed cross-species comparison is saved for this run.'
              : 'Select a saved analysis run to see its cross-species results.'}
        </Typography>
        <Stack
          direction={{ xs: 'column', sm: 'row' }}
          spacing={2}
          alignItems="center"
          justifyContent="center"
          sx={{ mb: 3 }}
        >
          <Paper variant="outlined" sx={{ p: 2, width: { xs: '100%', sm: 220 }, textAlign: 'center', borderColor: '#1677a8' }}>
            <Typography variant="caption" color="text.secondary">HUMAN</Typography>
            <Typography fontWeight={800}>NETWORK</Typography>
            <Typography variant="caption" color="text.secondary">
              {runCrossSpecies ? `${formatNumber(crossSpecies.human_nodes)} nodes` : 'Awaiting comparison'}
            </Typography>
          </Paper>
          <Stack direction="row" alignItems="center" spacing={1} sx={{ color: 'text.secondary' }}>
            <Divider sx={{ width: { xs: 28, sm: 44 } }} />
            <ArrowForward fontSize="small" />
            <Typography variant="caption" sx={{ whiteSpace: 'nowrap', fontWeight: 700 }}>ORTHOLOGY + DRIFT</Typography>
            <ArrowForward fontSize="small" />
            <Divider sx={{ width: { xs: 28, sm: 44 } }} />
          </Stack>
          <Paper variant="outlined" sx={{ p: 2, width: { xs: '100%', sm: 220 }, textAlign: 'center', borderColor: '#be5a32' }}>
            <Typography variant="caption" color="text.secondary">MOUSE</Typography>
            <Typography fontWeight={800}>NETWORK</Typography>
            <Typography variant="caption" color="text.secondary">
              {runCrossSpecies ? `${formatNumber(crossSpecies.mouse_nodes)} nodes` : 'Awaiting comparison'}
            </Typography>
          </Paper>
        </Stack>
        <Grid container spacing={2}>
          <Grid item xs={12} sm={6}>
            <Paper variant="outlined" sx={{ p: 2, height: '100%' }}>
              <Typography variant="body2" color="text.secondary">Edge conservation</Typography>
              <Typography variant="h5" fontWeight={800}>
                {conservationPercent == null ? '—' : `${conservationPercent.toFixed(1)}%`}
              </Typography>
            </Paper>
          </Grid>
          <Grid item xs={12} sm={6}>
            <Paper variant="outlined" sx={{ p: 2, height: '100%' }}>
              <Typography variant="body2" color="text.secondary">Mean gene drift score</Typography>
              <Typography variant="h5" fontWeight={800}>
                {typeof crossSpecies.mean_gene_drift_score === 'number' ? crossSpecies.mean_gene_drift_score.toFixed(3) : '—'}
              </Typography>
            </Paper>
          </Grid>
        </Grid>
      </Paper>

      <Paper sx={{ p: { xs: 2, md: 3 } }} elevation={0} variant="outlined">
        <Typography variant="h6" fontWeight={700}>Top affected pathways</Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5, mb: 2 }}>
          Significant terms from the selected saved analysis run.
        </Typography>
        {pathways.length ? (
          <Stack divider={<Divider flexItem />}>
            {pathways.map((pathway, index) => (
              <Stack
                key={`${pathway.pathway_id}-${index}`}
                direction="row"
                justifyContent="space-between"
                alignItems="center"
                spacing={2}
                sx={{ py: 1.25 }}
              >
                <Typography variant="body1">
                  <Box component="span" sx={{ color: 'text.secondary', mr: 1.25 }}>{index + 1}.</Box>
                  {pathway.pathway_name ?? pathway.pathway_id ?? 'Unnamed pathway'}
                </Typography>
                {pathway.adjusted_p_value != null && (
                  <Typography variant="caption" color="text.secondary" sx={{ whiteSpace: 'nowrap' }}>
                    FDR {Number(pathway.adjusted_p_value).toExponential(2)}
                  </Typography>
                )}
              </Stack>
            ))}
          </Stack>
        ) : (
          <Alert severity="info">
            {selectedRun ? 'No significant pathway enrichment results are saved for this run.' : 'Select a saved analysis run to see pathway enrichment results.'}
          </Alert>
        )}
      </Paper>
    </Box>
  )
}
