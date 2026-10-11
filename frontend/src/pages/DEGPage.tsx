import { useEffect } from 'react'
import { Link as RouterLink } from 'react-router-dom'
import { Alert, Box, Button, LinearProgress, Typography } from '@mui/material'
import { useQuery } from '@tanstack/react-query'
import { phase3Api } from '@/api/client'
import { useAuthStore } from '@/store/authStore'
import { useProjectStore } from '@/store/projectStore'
import DifferentialExpressionPage from './DifferentialExpressionPage'

interface SavedAnalysisRun {
  id: string
  project_name?: string
  status: string
  created_at: string
}

const PUBLIC_DEG_RUN_ID = '1c782941-d15c-4c3a-a291-5172f1d23937'

export default function DEGPage() {
  const userId = useAuthStore((state) => state.user?.id)
  const currentRunId = useProjectStore((state) => state.currentRunId)
  const setCurrentRun = useProjectStore((state) => state.setCurrentRun)
  const {
    data: runs = [],
    isLoading,
    isError,
    error,
  } = useQuery({
    queryKey: ['saved-analysis-runs', userId],
    queryFn: () => phase3Api.savedRuns().then((response) => response.data as SavedAnalysisRun[]),
  })

  const completedRuns = runs
    .filter((run) => run.status.toUpperCase() === 'COMPLETED')
    .sort((first, second) => Date.parse(second.created_at) - Date.parse(first.created_at))
  const selectedRun = completedRuns.find((run) => run.id === PUBLIC_DEG_RUN_ID)
    ?? completedRuns.find((run) => run.id === currentRunId)
    ?? completedRuns[0]
  const resultRunId = selectedRun?.id ?? (!isError ? PUBLIC_DEG_RUN_ID : undefined)

  useEffect(() => {
    if (resultRunId && resultRunId !== currentRunId) setCurrentRun(resultRunId)
  }, [currentRunId, resultRunId, setCurrentRun])

  if (resultRunId) return <DifferentialExpressionPage savedRunId={resultRunId} />

  return (
    <Box sx={{ maxWidth: 1100, mx: 'auto' }}>
      <Typography variant="h4" fontWeight={800} gutterBottom>Differential Expression</Typography>
      <Typography color="text.secondary" sx={{ mb: 2.5 }}>
        Explore saved differential-expression results from completed analyses.
      </Typography>
      {isLoading && <LinearProgress />}
      {isError && <Alert severity="error">Saved analysis runs could not be loaded: {(error as Error).message}</Alert>}
      {!isLoading && !isError && (
        <Alert
          severity="info"
          action={<Button component={RouterLink} to="/" color="inherit" size="small">Go to Dashboard</Button>}
        >
          No completed analysis runs are available yet. Complete an analysis from the Dashboard to view its DEG results here.
        </Alert>
      )}
    </Box>
  )
}
