import { useEffect, useState } from 'react'
import {
  Box, Grid, Paper, Typography, Chip, Alert, Button, TextField, MenuItem,
  Stack,
} from '@mui/material'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { analysisApi, healthApi, orthologyApi, projectApi } from '@/api/client'
import { useAuthStore } from '@/store/authStore'
import { useProjectStore } from '@/store/projectStore'

const EMPTY_PROJECTS: Array<{ id: string; name: string }> = []
const EMPTY_ANALYSES: Array<{ id: string; name: string }> = []

function StatCard({ label, value, color = 'primary.main' }: { label: string; value: string | number; color?: string }) {
  return (
    <Paper sx={{ p: 2.5 }} elevation={0} variant="outlined">
      <Typography variant="body2" color="text.secondary" gutterBottom>{label}</Typography>
      <Typography variant="h5" fontWeight={700} sx={{ color }}>{value}</Typography>
    </Paper>
  )
}

export default function DashboardPage() {
  const { user } = useAuthStore()
  const queryClient = useQueryClient()
  const { currentProjectId, currentAnalysisId, setCurrentProject, setCurrentAnalysis } = useProjectStore()
  const [projectName, setProjectName] = useState('')
  const [projectDescription, setProjectDescription] = useState('')
  const [researchQuestion, setResearchQuestion] = useState('')
  const [projectError, setProjectError] = useState<string | null>(null)

  const { data: health } = useQuery({
    queryKey: ['health'],
    queryFn: () => healthApi.check().then(r => r.data),
    refetchInterval: 30_000,
  })

  const { data: orthStats } = useQuery({
    queryKey: ['orthology-stats'],
    queryFn: () => orthologyApi.stats().then(r => r.data),
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

  const createProjectMutation = useMutation({
    mutationKey: ['projects', 'create'],
    mutationFn: async () => {
      const name = projectName.trim()
      if (!name) throw new Error('Project name is required')

      return projectApi.create({
        name,
        description: projectDescription.trim() || undefined,
        research_question: researchQuestion.trim() || undefined,
        is_public: false,
      })
    },
    onSuccess: (response) => {
      queryClient.invalidateQueries({ queryKey: ['projects'] })
      setCurrentProject(response.data.id)
      setProjectName('')
      setProjectDescription('')
      setResearchQuestion('')
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

  return (
    <Box>
      <Typography variant="h4" fontWeight={700} gutterBottom>Dashboard</Typography>
      <Typography variant="body1" color="text.secondary" mb={3}>
        Welcome back, <strong>{user?.full_name || user?.username}</strong>.
        PathDrift is a computational research platform for cross-species gene network drift analysis.
      </Typography>

      {health?.status !== 'ok' && (
        <Alert severity="warning" sx={{ mb: 2 }}>
          Backend API is not reachable. Ensure the backend server is running.
        </Alert>
      )}

      {orthStats?.status === 'not_loaded' && (
        <Alert severity="info" sx={{ mb: 2 }}>
          Orthology data is not yet loaded. Run{' '}
          <code>python scripts/seed_orthology.py</code>{' '}
          in the backend directory to populate human–mouse orthology mappings.
        </Alert>
      )}

      <Paper sx={{ p: 3, mb: 3 }} elevation={0} variant="outlined">
        <Stack direction={{ xs: 'column', md: 'row' }} spacing={2} alignItems={{ xs: 'stretch', md: 'center' }} justifyContent="space-between">
          <Box>
            <Typography variant="subtitle2" color="text.secondary" gutterBottom>Active Project</Typography>
            {projects.length > 0 ? (
              <TextField
                select
                size="small"
                value={currentProjectId ?? ''}
                onChange={(event) => setCurrentProject(event.target.value || null)}
                sx={{ minWidth: 260 }}
              >
                {projects.map((project) => (
                  <MenuItem key={project.id} value={project.id}>{project.name}</MenuItem>
                ))}
              </TextField>
            ) : (
              <Typography variant="body2" color="text.secondary">No projects yet. Create one to begin.</Typography>
            )}
            {selectedProject && (
              <Chip label={selectedProject.name} color="primary" variant="outlined" sx={{ mt: 1.5 }} />
            )}
            <Box sx={{ mt: 2 }}>
              <Typography variant="subtitle2" color="text.secondary" gutterBottom>Selected Analysis</Typography>
              {analyses.length > 0 ? (
                <TextField
                  select
                  size="small"
                  value={currentAnalysisId ?? ''}
                  onChange={(event) => setCurrentAnalysis(event.target.value || null)}
                  sx={{ minWidth: 260 }}
                >
                  {analyses.map((analysis) => (
                    <MenuItem key={analysis.id} value={analysis.id}>{analysis.name}</MenuItem>
                  ))}
                </TextField>
              ) : (
                <Typography variant="body2" color="text.secondary">No analyses yet for this project.</Typography>
              )}
              <Button
                variant="outlined"
                size="small"
                sx={{ ml: 1 }}
                onClick={() => createAnalysisMutation.mutate()}
                disabled={!currentProjectId || createAnalysisMutation.isPending}
              >
                {createAnalysisMutation.isPending ? 'Creating...' : 'New analysis'}
              </Button>
            </Box>
          </Box>

          <Box sx={{ minWidth: { xs: '100%', md: 420 } }}>
            <Typography variant="subtitle2" color="text.secondary" gutterBottom>Create a Project</Typography>
            <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1}>
              <TextField
                size="small"
                label="Project name"
                value={projectName}
                onChange={(event) => setProjectName(event.target.value)}
                fullWidth
              />
              <Button
                variant="contained"
                onClick={() => createProjectMutation.mutate()}
                disabled={createProjectMutation.isPending}
              >
                {createProjectMutation.isPending ? 'Creating...' : 'Create'}
              </Button>
            </Stack>
            <TextField
              size="small"
              label="Description"
              value={projectDescription}
              onChange={(event) => setProjectDescription(event.target.value)}
              fullWidth
              sx={{ mt: 1 }}
            />
            <TextField
              size="small"
              label="Research question"
              value={researchQuestion}
              onChange={(event) => setResearchQuestion(event.target.value)}
              fullWidth
              sx={{ mt: 1 }}
            />
            {projectError && (
              <Alert severity="error" sx={{ mt: 1 }}>{projectError}</Alert>
            )}
          </Box>
        </Stack>
      </Paper>

      <Grid container spacing={2} mb={3}>
        <Grid item xs={6} sm={3}>
          <StatCard label="System Status" value={health?.status === 'ok' ? 'Online' : 'Offline'}
            color={health?.status === 'ok' ? 'success.main' : 'error.main'} />
        </Grid>
        <Grid item xs={6} sm={3}>
          <StatCard label="Ortholog Pairs" value={orthStats?.total_mappings?.toLocaleString() ?? '—'} />
        </Grid>
        <Grid item xs={6} sm={3}>
          <StatCard label="API Version" value={health?.version ?? '—'} />
        </Grid>
        <Grid item xs={6} sm={3}>
          <StatCard label="Environment" value={health?.environment ?? '—'} />
        </Grid>
      </Grid>

      <Paper sx={{ p: 3, mb: 3 }} elevation={0} variant="outlined">
        <Typography variant="h6" fontWeight={600} gutterBottom>Research Hypothesis</Typography>
        <Typography variant="body2" color="text.secondary" sx={{ fontStyle: 'italic', lineHeight: 1.8 }}>
          "Conserved gene-network drift between human and mouse breast-cancer states contains
          biologically meaningful information that can improve early breast-cancer state prediction
          compared with conventional gene-expression features alone."
        </Typography>
      </Paper>

      <Paper sx={{ p: 3 }} elevation={0} variant="outlined">
        <Typography variant="h6" fontWeight={600} gutterBottom>Recommended Workflow</Typography>
        <Box component="ol" sx={{ pl: 2.5, '& li': { mb: 1, color: 'text.secondary', fontSize: 14 } }}>
          <li>Upload or import transcriptomic datasets (human TCGA-BRCA / GEO; mouse mammary GEO)</li>
          <li>Validate datasets — check for errors and inconsistencies</li>
          <li>Run preprocessing pipeline (normalization, QC, outlier detection)</li>
          <li>Perform DEG analysis (baseline comparison)</li>
          <li>Construct separate gene networks for healthy and disease states (both species)</li>
          <li>Run drift detection (healthy → disease for each species)</li>
          <li>Map orthologues and run cross-species drift comparison</li>
          <li>Extract features and train ML models (expression-only, drift-only, combined)</li>
          <li>Validate on independent external dataset</li>
          <li>Perform pathway enrichment on drifting genes</li>
          <li>Generate reproducible research report</li>
        </Box>
      </Paper>
    </Box>
  )
}
