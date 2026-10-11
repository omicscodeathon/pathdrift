import { useEffect, useMemo, useState } from 'react'
import { Alert, Box, Button, Chip, CircularProgress, Grid, LinearProgress, MenuItem, Paper, Stack, TextField, Typography } from '@mui/material'
import { useMutation, useQuery } from '@tanstack/react-query'
import { useSnackbar } from 'notistack'
import { phase3Api } from '@/api/client'
import { useAuthStore } from '@/store/authStore'
import { useProjectStore } from '@/store/projectStore'
import type { Run } from './analysis/shared'

type RunArtifact = { path: string; name: string; section: string; size_bytes: number }

function formatFileSize(bytes: number) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function saveBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
}

export default function ReportsPage() {
  const { enqueueSnackbar } = useSnackbar()
  const userId = useAuthStore((state) => state.user?.id)
  const currentRunId = useProjectStore((state) => state.currentRunId)
  const setCurrentRun = useProjectStore((state) => state.setCurrentRun)
  const { data: runs = [], isLoading: runsLoading, isError: runsError } = useQuery({
    queryKey: ['saved-analysis-runs', userId],
    queryFn: () => phase3Api.savedRuns().then((response) => response.data as Run[]),
  })
  const selectedRunId = runs.some((run) => run.id === currentRunId) ? currentRunId! : ''
  const { data: artifactResponse, isLoading: artifactsLoading, isError: artifactsError } = useQuery({
    queryKey: ['run-artifacts', selectedRunId],
    queryFn: () => phase3Api.artifacts(selectedRunId).then((response) => response.data as { items: RunArtifact[]; total: number }),
    enabled: !!selectedRunId,
  })
  const artifacts = artifactResponse?.items ?? []
  const groupedArtifacts = useMemo(() => artifacts.reduce<Record<string, RunArtifact[]>>((groups, artifact) => {
    ;(groups[artifact.section] ??= []).push(artifact)
    return groups
  }, {}), [artifacts])

  useEffect(() => {
    if (!runsLoading && runs.length && !runs.some((run) => run.id === currentRunId)) {
      setCurrentRun(runs.find((run) => run.status.toUpperCase() === 'COMPLETED')?.id ?? runs[0].id)
    }
  }, [currentRunId, runs, runsLoading, setCurrentRun])

  const downloadOneMutation = useMutation({
    mutationFn: ({ runId, path }: { runId: string; path: string }) => phase3Api.artifact(runId, path),
    onSuccess: (response, variables) => saveBlob(response.data as Blob, variables.path.split('/').pop() ?? 'result'),
    onError: () => enqueueSnackbar('Could not download this result file', { variant: 'error' }),
  })
  const downloadAllMutation = useMutation({
    mutationFn: (runId: string) => phase3Api.downloadAllArtifacts(runId),
    onSuccess: (response, runId) => saveBlob(response.data, `pathdrift-results-${runId}.zip`),
    onError: () => enqueueSnackbar('Could not download the saved results bundle', { variant: 'error' }),
  })

  return (
    <Box>
      <Typography variant="h4" fontWeight={700} gutterBottom>Reports</Typography>
      <Typography variant="body2" color="text.secondary" mb={3}>
        Browse and download saved result files from an analysis run.
      </Typography>

      <Paper sx={{ p: 3, mb: 3 }} variant="outlined">
        <Stack direction={{ xs: 'column', sm: 'row' }} justifyContent="space-between" alignItems={{ xs: 'stretch', sm: 'center' }} spacing={2} sx={{ mb: 2 }}>
          <Box>
            <Typography variant="h6" fontWeight={600}>Saved run results</Typography>
            <Typography variant="body2" color="text.secondary">All saved tables, summaries, figures, and reports for a run.</Typography>
          </Box>
          {selectedRunId && artifacts.length > 0 && (
            <Button
              variant="contained"
              onClick={() => downloadAllMutation.mutate(selectedRunId)}
              disabled={downloadAllMutation.isPending}
              startIcon={downloadAllMutation.isPending ? <CircularProgress size={18} color="inherit" /> : undefined}
            >
              Download all ({artifacts.length})
            </Button>
          )}
        </Stack>
        {runsLoading && <LinearProgress sx={{ mb: 2 }} />}
        {runsError && <Alert severity="error" sx={{ mb: 2 }}>Saved analysis runs could not be loaded.</Alert>}
        {!runsLoading && !runsError && !runs.length && <Alert severity="info">No saved analysis runs are available.</Alert>}
        {!!runs.length && (
          <TextField
            select
            fullWidth
            size="small"
            label="Analysis run"
            value={selectedRunId}
            onChange={(event) => setCurrentRun(event.target.value || null)}
            sx={{ mb: 2 }}
          >
            {runs.map((run) => (
              <MenuItem key={run.id} value={run.id}>
                {run.project_name ?? 'Saved analysis'} · {new Date(run.created_at).toLocaleString()} · {run.status}
              </MenuItem>
            ))}
          </TextField>
        )}
        {selectedRunId && artifactsLoading && <LinearProgress sx={{ mb: 2 }} />}
        {selectedRunId && artifactsError && <Alert severity="error" sx={{ mb: 2 }}>Saved result artifacts could not be loaded.</Alert>}
        {selectedRunId && !artifactsLoading && !artifactsError && artifacts.length === 0 && (
          <Alert severity="info">No downloadable result artifacts are available for this run.</Alert>
        )}
        {selectedRunId && !artifactsLoading && !artifactsError && artifacts.length > 0 && (
          <>
            <Chip size="small" label={`${artifactResponse?.total ?? artifacts.length} files`} sx={{ mb: 1.5 }} />
            <Grid container spacing={2}>
              {Object.entries(groupedArtifacts).map(([section, sectionArtifacts]) => (
                <Grid item xs={12} md={6} key={section}>
                  <Paper variant="outlined" sx={{ p: 1.5, height: '100%' }}>
                    <Typography variant="subtitle1" fontWeight={700} sx={{ mb: 1 }}>
                      {section.replace(/_/g, ' ')} <Typography component="span" variant="caption" color="text.secondary">({sectionArtifacts.length})</Typography>
                    </Typography>
                    <Stack spacing={0.75}>
                      {sectionArtifacts.map((artifact) => (
                        <Stack key={artifact.path} direction="row" justifyContent="space-between" alignItems="center" spacing={1}>
                          <Box sx={{ minWidth: 0 }}>
                            <Typography variant="body2" noWrap title={artifact.path}>{artifact.path}</Typography>
                            <Typography variant="caption" color="text.secondary">{formatFileSize(artifact.size_bytes)}</Typography>
                          </Box>
                          <Button
                            size="small"
                            onClick={() => downloadOneMutation.mutate({ runId: selectedRunId, path: artifact.path })}
                            disabled={downloadOneMutation.isPending}
                          >
                            Download
                          </Button>
                        </Stack>
                      ))}
                    </Stack>
                  </Paper>
                </Grid>
              ))}
            </Grid>
          </>
        )}
      </Paper>

    </Box>
  )
}
