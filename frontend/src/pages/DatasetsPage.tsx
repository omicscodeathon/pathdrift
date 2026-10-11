 /**
 * Datasets Page — Upload, validate, and manage transcriptomic datasets.
 */
import { useState, useCallback, useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Box, Typography, Button, Paper, Grid, Chip, Dialog, DialogTitle,
  DialogContent, DialogActions, TextField, MenuItem, Alert, CircularProgress,
  Table, TableBody, TableCell, TableHead, TableRow, TableContainer, Stack,
  LinearProgress, IconButton, Tooltip, Card, CardContent,
  TablePagination,
} from '@mui/material'
import { useDropzone } from 'react-dropzone'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { CloudUpload, CheckCircle, ErrorOutline, Warning, Delete, Visibility, OpenInNew } from '@mui/icons-material'
import { useSnackbar } from 'notistack'
import {
  analysisApi, dataAcquisitionApi, datasetApi, preprocessingApi, degApi,
  networkApi, driftApi, pathwayApi,
} from '@/api/client'
import type { ManifestDataset } from '@/api/client'
import type { Dataset } from '@/types'
import { useProjectStore } from '@/store/projectStore'

const SPECIES_OPTIONS = [
  { value: 'human', label: 'Human (Homo sapiens)' },
  { value: 'mouse', label: 'Mouse (Mus musculus)' },
]

const DATA_TYPE_OPTIONS = [
  { value: 'raw_counts', label: 'Raw Counts (RNA-seq)' },
  { value: 'normalized', label: 'Already Normalized' },
  { value: 'microarray', label: 'Microarray' },
  { value: 'unknown', label: 'Unknown / Other' },
]

const displayDataType = (value?: string) => {
  const v = (value ?? 'unknown').toString().toLowerCase()
  if (v === 'raw_counts') return 'Raw Counts (RNA-seq)'
  if (v === 'normalized') return 'Already Normalized'
  if (v === 'microarray') return 'Microarray'
  return 'Unknown / Other'
}

const normalizeDatasetId = (dataset: unknown) => {
  const record = dataset as Record<string, unknown> | null
  const candidate =
    record?.id ??
    record?.dataset_id ??
    record?.datasetId ??
    record?.accession ??
    record?.name ??
    'downloaded-dataset'

  const normalized = String(candidate).trim()
  return normalized || 'downloaded-dataset'
}

interface AutomatedWorkflowState {
  projectId: string
  datasetId: string
  analysisId: string
  species: string
  preprocessingJobId: string | null
  degResultId: string | null
  degPathwayId: string | null
  healthyNetworkId: string | null
  diseaseNetworkId: string | null
  driftResultId: string | null
  driftPathwayId: string | null
  networkSkippedReason: string | null
  networkError: string | null
  driftError: string | null
  degPathwayError: string | null
  driftPathwayError: string | null
}

const getResultRef = (response: { data: { result_ref?: string | null } }) => {
  const resultRef = response.data.result_ref
  if (!resultRef) throw new Error('The server accepted the job but did not return its result ID.')
  return resultRef
}

function StatusChip({ status }: { status: string }) {
  const map: Record<string, { color: 'success' | 'error' | 'warning' | 'default'; icon: JSX.Element }> = {
    true:  { color: 'success', icon: <CheckCircle fontSize="small" /> },
    false: { color: 'error',   icon: <ErrorOutline fontSize="small" /> },
  }
  const s = map[String(status)] ?? { color: 'default', icon: <Warning fontSize="small" /> }
  return <Chip size="small" color={s.color} icon={s.icon} label={status ? 'Validated' : 'Not validated'} />
}

export default function DatasetsPage() {
  const { enqueueSnackbar } = useSnackbar()
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const { currentProjectId, currentAnalysisId, currentDatasetId, setCurrentAnalysis, setCurrentDataset, setWorkflowIds } = useProjectStore()
  const [uploadOpen, setUploadOpen] = useState(false)
  const [form, setForm] = useState({
    name: '', species: 'human', data_type: 'raw_counts',
    tissue: '', source: '', accession: '', platform: '', description: '',
  })
  const [exprFile, setExprFile] = useState<File | null>(null)
  const [metaFile, setMetaFile] = useState<File | null>(null)
  const [validationResult, setValidationResult] = useState<Record<string, unknown> | null>(null)
  const [previewDatasetId, setPreviewDatasetId] = useState<string | null>(null)
  const [previewRows, setPreviewRows] = useState<string[][]>([])
  const [previewLoading, setPreviewLoading] = useState(false)
  const [manifestPreviewDataset, setManifestPreviewDataset] = useState<ManifestDataset | null>(null)
  const [manifestPreviewOffset, setManifestPreviewOffset] = useState(0)
  const [manifestPreviewLimit, setManifestPreviewLimit] = useState(100)
  const [workflowState, setWorkflowState] = useState<AutomatedWorkflowState | null>(null)
  const [degStartedFor, setDegStartedFor] = useState<string | null>(null)
  const startedStages = useRef(new Set<string>())

  const { data: datasets = [], isLoading } = useQuery({
    queryKey: ['datasets', currentProjectId],
    queryFn: () => currentProjectId ? datasetApi.list(currentProjectId).then(r => r.data as Dataset[]) : [],
    enabled: !!currentProjectId,
  })

  const { data: projectAnalyses = [], isLoading: analysesLoading } = useQuery({
    queryKey: ['analyses', currentProjectId],
    queryFn: () => currentProjectId ? analysisApi.listForProject(currentProjectId).then(r => r.data) : [],
    enabled: !!currentProjectId,
  })

  const { data: manifestDatasets = [], isLoading: manifestDatasetsLoading, isError: manifestDatasetsError } = useQuery({
    queryKey: ['data-acquisition', 'manifest-datasets'],
    queryFn: () => dataAcquisitionApi.listManifestDatasets().then((response) => response.data),
  })

  const manifestPreviewQuery = useQuery({
    queryKey: ['data-acquisition', 'manifest-preview', manifestPreviewDataset?.id, manifestPreviewOffset, manifestPreviewLimit],
    queryFn: () => dataAcquisitionApi.previewManifestDataset(
      manifestPreviewDataset!.id,
      manifestPreviewOffset,
      manifestPreviewLimit,
    ).then((response) => response.data),
    enabled: !!manifestPreviewDataset,
  })
  const hasManifestPreview = Boolean(
    manifestPreviewQuery.data?.expression &&
    manifestPreviewQuery.data?.sample_metadata,
  )

  const mergedDatasets: Dataset[] = datasets
  const actualDatasetIds = new Set((datasets as Dataset[]).map((dataset) => String(dataset.id)))
  const isWorkflowEligibleDataset = (datasetId: string) => actualDatasetIds.has(String(datasetId))

  useEffect(() => {
    if (!currentProjectId) return
    queryClient.invalidateQueries({ queryKey: ['datasets', currentProjectId] })
  }, [currentProjectId, queryClient])

  useEffect(() => {
    if (!datasets.length) {
      if (currentDatasetId) setCurrentDataset(null)
      return
    }

    const datasetExists = datasets.some((dataset) => String(dataset.id) === String(currentDatasetId))
    if (!currentDatasetId || !datasetExists) {
      const latestDatasetId = String(datasets[datasets.length - 1].id)
      setCurrentDataset(latestDatasetId)
    }
  }, [currentDatasetId, datasets, setCurrentDataset])

  useEffect(() => {
    if (!analysesLoading && currentAnalysisId && !projectAnalyses.some((analysis) => analysis.id === currentAnalysisId)) {
      setCurrentAnalysis(null)
    }
  }, [analysesLoading, currentAnalysisId, projectAnalyses, setCurrentAnalysis])

  const uploadMutation = useMutation({
    mutationKey: ['datasets', 'upload'],
    mutationFn: async () => {
      if (!exprFile || !currentProjectId) throw new Error('Expression file and project required')
      const fd = new FormData()
      fd.append('project_id', currentProjectId)
      Object.entries(form).forEach(([k, v]) => { if (v) fd.append(k, v) })
      fd.append('expression_file', exprFile)
      if (metaFile) fd.append('metadata_file', metaFile)
      return datasetApi.upload(fd)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['datasets'] })
      setUploadOpen(false)
      setExprFile(null)
      setMetaFile(null)
      enqueueSnackbar('Dataset uploaded successfully', { variant: 'success' })
    },
    onError: (err: unknown) => {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail || 'Upload failed'
      enqueueSnackbar(msg, { variant: 'error' })
    },
  })

  const validateMutation = useMutation({
    mutationKey: ['datasets', 'validate'],
    mutationFn: (id: string) => datasetApi.validate(id).then(r => r.data),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['datasets'] })
      setValidationResult(data as Record<string, unknown>)
    },
    onError: () => enqueueSnackbar('Validation failed', { variant: 'error' }),
  })

  const deleteMutation = useMutation({
    mutationKey: ['datasets', 'delete'],
    mutationFn: (id: string) => datasetApi.delete(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['datasets'] })
      enqueueSnackbar('Dataset deleted', { variant: 'info' })
    },
  })

  const workflowMutation = useMutation({
    mutationKey: ['datasets', 'workflow'],
    mutationFn: async (datasetId: string) => {
      const canonicalDatasetId = normalizeDatasetId({ id: datasetId })
      if (!isWorkflowEligibleDataset(canonicalDatasetId)) {
        throw new Error('This dataset is not imported into the current project yet. Upload or import it first, then run preprocessing.')
      }
      const dataset = datasets.find((item) => String(item.id) === canonicalDatasetId)
      if (!dataset || (dataset.n_healthy ?? 0) < 2 || (dataset.n_cancer ?? 0) < 2) {
        throw new Error('DEG requires at least two real healthy and two real cancer samples with metadata labels.')
      }
      if (!currentProjectId) throw new Error('Select a project before starting an analysis.')

      let analysisId = currentAnalysisId
      if (!analysisId) {
        const analysisResponse = await analysisApi.create({
          project_id: currentProjectId,
          name: `${dataset.name} analysis`,
          description: `Automated analysis workflow for dataset ${canonicalDatasetId}`,
        })
        analysisId = analysisResponse.data.id
        await queryClient.invalidateQueries({ queryKey: ['analyses', currentProjectId] })
        setCurrentAnalysis(analysisId)
      }
      setCurrentDataset(canonicalDatasetId)

      const workflow: AutomatedWorkflowState = {
        projectId: currentProjectId,
        datasetId: canonicalDatasetId,
        analysisId,
        species: String(dataset.species).toLowerCase(),
        preprocessingJobId: null,
        degResultId: null,
        degPathwayId: null,
        healthyNetworkId: null,
        diseaseNetworkId: null,
        driftResultId: null,
        driftPathwayId: null,
        networkSkippedReason: (dataset.n_healthy ?? 0) < 5 || (dataset.n_cancer ?? 0) < 5
          ? 'Network drift requires at least five healthy and five cancer samples in this dataset.'
          : null,
        networkError: null,
        driftError: null,
        degPathwayError: null,
        driftPathwayError: null,
      }

      let preprocessingJobId: string | null = null
      if (dataset.data_type === 'normalized') {
        const degResponse = await degApi.run({
          analysis_id: analysisId,
          dataset_id: canonicalDatasetId,
          preprocessing_job_id: null,
          method: 'ttest',
          fdr_threshold: 0.05,
          lfc_threshold: 1.0,
        })
        return { ...workflow, degResultId: getResultRef(degResponse) }
      }

      const preprocessingResponse = await preprocessingApi.start({
        analysis_id: analysisId,
        dataset_id: canonicalDatasetId,
        normalization_method: dataset.data_type === 'raw_counts' ? 'log2cpm' : 'none',
        low_expr_threshold: 1.0,
        low_expr_min_samples: 3,
        min_gene_variance: 0.1,
        remove_duplicates: true,
        impute_missing: false,
        batch_correct: false,
        batch_correction_method: null,
        outlier_detection: true,
      })
      preprocessingJobId = getResultRef(preprocessingResponse)

      return { ...workflow, preprocessingJobId }
    },
    onSuccess: (data) => {
      setWorkflowState(data)
      setWorkflowIds({
        currentDatasetId: data.datasetId,
        preprocessingJobId: data.preprocessingJobId,
        degResultId: data.degResultId,
      })
      setDegStartedFor(null)
      startedStages.current.clear()
      enqueueSnackbar(data.degResultId
        ? 'DEG analysis queued. Pathway and eligible network analyses will follow automatically.'
        : 'Preprocessing queued. DEG and subsequent analyses will start automatically when it completes.', { variant: 'info' })
      queryClient.invalidateQueries({ queryKey: ['datasets'] })
    },
    onError: (error: unknown) => {
      const message = (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail || (error as Error)?.message || 'Workflow failed to start.'
      enqueueSnackbar(message, { variant: 'error' })
    },
  })

  const preprocessingStatusQuery = useQuery({
    queryKey: ['preprocessing-status', workflowState?.preprocessingJobId],
    queryFn: () => workflowState?.preprocessingJobId
      ? preprocessingApi.get(workflowState.preprocessingJobId).then((r) => r.data)
      : Promise.resolve(null),
    enabled: !!workflowState?.preprocessingJobId,
    refetchInterval: (query) => {
      const status = (query.state.data as { status?: string } | undefined)?.status
      return status === 'queued' || status === 'running' ? 2000 : false
    },
  })

  const degStatusQuery = useQuery({
    queryKey: ['deg-status', workflowState?.degResultId],
    queryFn: () => workflowState?.degResultId
      ? degApi.get(workflowState.degResultId).then((r) => r.data)
      : Promise.resolve(null),
    enabled: !!workflowState?.degResultId,
    refetchInterval: (query) => {
      const status = (query.state.data as { status?: string } | undefined)?.status
      return status === 'queued' || status === 'running' ? 2000 : false
    },
  })

  const startDegAfterPreprocessing = useMutation({
    mutationKey: ['datasets', 'deg-after-preprocessing'],
    mutationFn: ({ analysisId, datasetId, preprocessingJobId }: { analysisId: string; datasetId: string; preprocessingJobId: string }) =>
      degApi.run({
        analysis_id: analysisId,
        dataset_id: datasetId,
        preprocessing_job_id: preprocessingJobId,
        method: 'ttest',
        fdr_threshold: 0.05,
        lfc_threshold: 1.0,
      }).then(getResultRef),
    onSuccess: (result) => {
      setWorkflowState((current) => current ? { ...current, degResultId: result } : current)
      setWorkflowIds({ degResultId: result })
      enqueueSnackbar('Preprocessing completed; DEG analysis queued.', { variant: 'success' })
    },
    onError: (error: unknown) => {
      const message = (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail || (error as Error)?.message || 'Failed to queue DEG analysis.'
      enqueueSnackbar(message, { variant: 'error' })
    },
  })

  useEffect(() => {
    const preprocessingId = workflowState?.preprocessingJobId
    if (
      preprocessingId &&
      preprocessingStatusQuery.data?.status === 'completed' &&
      !workflowState.degResultId &&
      degStartedFor !== preprocessingId &&
      !startDegAfterPreprocessing.isPending
    ) {
      setDegStartedFor(preprocessingId)
      startDegAfterPreprocessing.mutate({
        analysisId: workflowState.analysisId,
        datasetId: workflowState.datasetId,
        preprocessingJobId: preprocessingId,
      })
    }
  }, [
    workflowState,
    preprocessingStatusQuery.data?.status,
    degStartedFor,
    startDegAfterPreprocessing,
  ])

  const startDegPathway = useMutation({
    mutationKey: ['datasets', 'automatic-deg-pathway'],
    mutationFn: async ({ analysisId, degResultId, species }: {
      analysisId: string; degResultId: string; species: string
    }) => getResultRef(await pathwayApi.run({
      analysis_id: analysisId,
      source: 'deg',
      source_id: degResultId,
      species,
      gene_set: 'GO_Biological_Process_2023',
      fdr_threshold: 0.05,
    })),
    onSuccess: (pathwayId) => {
      setWorkflowState((current) => current ? { ...current, degPathwayId: pathwayId } : current)
      setWorkflowIds({ pathwayResultId: pathwayId })
    },
    onError: (error: unknown) => {
      const message = (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail
        || (error as Error)?.message || 'Could not start DEG pathway enrichment.'
      setWorkflowState((current) => current ? { ...current, degPathwayError: message } : current)
      enqueueSnackbar(message, { variant: 'error' })
    },
  })

  const startNetworks = useMutation({
    mutationKey: ['datasets', 'automatic-networks'],
    mutationFn: async ({ analysisId, datasetId, preprocessingJobId, species }: {
      analysisId: string; datasetId: string; preprocessingJobId: string | null; species: string
    }) => {
      const common = {
        analysis_id: analysisId,
        dataset_id: datasetId,
        preprocessing_job_id: preprocessingJobId,
        species,
        correlation_method: 'pearson',
        correlation_threshold: 0.6,
        fdr_threshold: 0.05,
        top_n_genes: null,
        min_gene_variance: 0.1,
      }
      const healthyResponse = await networkApi.build({
        ...common,
        name: `${species} healthy co-expression`,
        disease_state: 'healthy',
      })
      const healthyNetworkId = getResultRef(healthyResponse)
      setWorkflowState((current) => current ? { ...current, healthyNetworkId } : current)
      const diseaseResponse = await networkApi.build({
        ...common,
        name: `${species} cancer co-expression`,
        disease_state: 'cancer',
      })
      return { healthyNetworkId, diseaseNetworkId: getResultRef(diseaseResponse) }
    },
    onSuccess: ({ healthyNetworkId, diseaseNetworkId }) => {
      setWorkflowState((current) => current ? { ...current, healthyNetworkId, diseaseNetworkId } : current)
      setWorkflowIds({ healthyNetworkId, diseaseNetworkId })
      queryClient.invalidateQueries({ queryKey: ['networks', workflowState?.projectId] })
    },
    onError: (error: unknown) => {
      const message = (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail
        || (error as Error)?.message || 'Could not start network construction.'
      setWorkflowState((current) => current ? { ...current, networkError: message } : current)
      enqueueSnackbar(message, { variant: 'error' })
    },
  })

  const startDrift = useMutation({
    mutationKey: ['datasets', 'automatic-drift'],
    mutationFn: async ({ analysisId, healthyNetworkId, diseaseNetworkId, species }: {
      analysisId: string; healthyNetworkId: string; diseaseNetworkId: string; species: string
    }) => getResultRef(await driftApi.run({
      analysis_id: analysisId,
      healthy_network_id: healthyNetworkId,
      disease_network_id: diseaseNetworkId,
      species,
    })),
    onSuccess: (driftResultId) => {
      setWorkflowState((current) => current ? { ...current, driftResultId } : current)
      setWorkflowIds(workflowState?.species === 'mouse'
        ? { mouseDriftId: driftResultId }
        : { humanDriftId: driftResultId })
      queryClient.invalidateQueries({ queryKey: ['drift-result'] })
    },
    onError: (error: unknown) => {
      const message = (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail
        || (error as Error)?.message || 'Could not start network drift analysis.'
      setWorkflowState((current) => current ? { ...current, driftError: message } : current)
      enqueueSnackbar(message, { variant: 'error' })
    },
  })

  const startDriftPathway = useMutation({
    mutationKey: ['datasets', 'automatic-drift-pathway'],
    mutationFn: async ({ analysisId, driftResultId, species }: {
      analysisId: string; driftResultId: string; species: string
    }) => getResultRef(await pathwayApi.run({
      analysis_id: analysisId,
      source: 'drift',
      source_id: driftResultId,
      species,
      gene_set: 'GO_Biological_Process_2023',
      fdr_threshold: 0.05,
    })),
    onSuccess: (pathwayId) => {
      setWorkflowState((current) => current ? { ...current, driftPathwayId: pathwayId } : current)
      setWorkflowIds({ pathwayResultId: pathwayId })
    },
    onError: (error: unknown) => {
      const message = (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail
        || (error as Error)?.message || 'Could not start drift pathway enrichment.'
      setWorkflowState((current) => current ? { ...current, driftPathwayError: message } : current)
      enqueueSnackbar(message, { variant: 'error' })
    },
  })

  const healthyNetworkQuery = useQuery({
    queryKey: ['automatic-network', workflowState?.healthyNetworkId],
    queryFn: () => networkApi.get(workflowState!.healthyNetworkId!).then((response) => response.data as { status: string }),
    enabled: !!workflowState?.healthyNetworkId,
    refetchInterval: (query) => ['queued', 'running'].includes((query.state.data as { status?: string } | undefined)?.status ?? '') ? 2000 : false,
  })
  const diseaseNetworkQuery = useQuery({
    queryKey: ['automatic-network', workflowState?.diseaseNetworkId],
    queryFn: () => networkApi.get(workflowState!.diseaseNetworkId!).then((response) => response.data as { status: string }),
    enabled: !!workflowState?.diseaseNetworkId,
    refetchInterval: (query) => ['queued', 'running'].includes((query.state.data as { status?: string } | undefined)?.status ?? '') ? 2000 : false,
  })
  const driftStatusQuery = useQuery({
    queryKey: ['automatic-drift', workflowState?.driftResultId],
    queryFn: () => driftApi.get(workflowState!.driftResultId!).then((response) => response.data as { status: string }),
    enabled: !!workflowState?.driftResultId,
    refetchInterval: (query) => ['queued', 'running'].includes((query.state.data as { status?: string } | undefined)?.status ?? '') ? 2000 : false,
  })
  const degPathwayQuery = useQuery({
    queryKey: ['automatic-pathway', workflowState?.degPathwayId],
    queryFn: () => pathwayApi.get(workflowState!.degPathwayId!).then((response) => response.data as { status: string }),
    enabled: !!workflowState?.degPathwayId,
    refetchInterval: (query) => ['queued', 'running'].includes((query.state.data as { status?: string } | undefined)?.status ?? '') ? 2000 : false,
  })
  const driftPathwayQuery = useQuery({
    queryKey: ['automatic-pathway', workflowState?.driftPathwayId],
    queryFn: () => pathwayApi.get(workflowState!.driftPathwayId!).then((response) => response.data as { status: string }),
    enabled: !!workflowState?.driftPathwayId,
    refetchInterval: (query) => ['queued', 'running'].includes((query.state.data as { status?: string } | undefined)?.status ?? '') ? 2000 : false,
  })
  const getWorkflowStatus = (data: unknown) =>
    String((data as { status?: string } | null)?.status ?? '').toLowerCase()
  const isWorkflowTerminal = (status: string) => status === 'completed' || status === 'failed'
  const preprocessingStatus = getWorkflowStatus(preprocessingStatusQuery.data)
  const degStatus = getWorkflowStatus(degStatusQuery.data)
  const healthyNetworkStatus = getWorkflowStatus(healthyNetworkQuery.data)
  const diseaseNetworkStatus = getWorkflowStatus(diseaseNetworkQuery.data)
  const driftStatus = getWorkflowStatus(driftStatusQuery.data)
  const degPathwayStatus = getWorkflowStatus(degPathwayQuery.data)
  const driftPathwayStatus = getWorkflowStatus(driftPathwayQuery.data)
  const workflowFailed = preprocessingStatus === 'failed' || degStatus === 'failed'
  const networksTerminal = isWorkflowTerminal(healthyNetworkStatus) && isWorkflowTerminal(diseaseNetworkStatus)
  const networksSucceeded = healthyNetworkStatus === 'completed' && diseaseNetworkStatus === 'completed'
  const driftPipelineInProgress = Boolean(
    networksTerminal &&
    networksSucceeded &&
    !workflowState?.driftError &&
    (
      startDrift.isPending ||
      !workflowState?.driftResultId ||
      ['queued', 'running'].includes(driftStatus) ||
      (driftStatus === 'completed' && !workflowState?.driftPathwayError && (
        startDriftPathway.isPending ||
        !workflowState?.driftPathwayId ||
        !isWorkflowTerminal(driftPathwayStatus)
      ))
    ),
  )
  const workflowInProgress = Boolean(
    workflowMutation.isPending ||
    (workflowState && !workflowFailed && (
      !isWorkflowTerminal(degStatus) ||
      startDegPathway.isPending ||
      (!workflowState.degPathwayError && !isWorkflowTerminal(degPathwayStatus)) ||
      (!workflowState.networkSkippedReason && !workflowState.networkError && (
        startNetworks.isPending ||
        !workflowState.healthyNetworkId ||
        !workflowState.diseaseNetworkId ||
        !isWorkflowTerminal(healthyNetworkStatus) ||
        !isWorkflowTerminal(diseaseNetworkStatus) ||
        driftPipelineInProgress
      ))
    )),
  )

  useEffect(() => {
    const degId = workflowState?.degResultId
    if (!degId || degStatusQuery.data?.status !== 'completed') return

    if (!workflowState.degPathwayId && !startedStages.current.has(`deg-pathway:${degId}`)) {
      startedStages.current.add(`deg-pathway:${degId}`)
      startDegPathway.mutate({
        analysisId: workflowState.analysisId,
        degResultId: degId,
        species: workflowState.species,
      })
    }

    if (
      !workflowState.networkSkippedReason &&
      !workflowState.healthyNetworkId &&
      !workflowState.networkError &&
      !startedStages.current.has(`networks:${degId}`)
    ) {
      startedStages.current.add(`networks:${degId}`)
      startNetworks.mutate({
        analysisId: workflowState.analysisId,
        datasetId: workflowState.datasetId,
        preprocessingJobId: workflowState.preprocessingJobId,
        species: workflowState.species,
      })
    }
  }, [
    workflowState,
    degStatusQuery.data?.status,
    datasets,
    startDegPathway,
    startNetworks,
  ])

  useEffect(() => {
    const healthyId = workflowState?.healthyNetworkId
    const diseaseId = workflowState?.diseaseNetworkId
    if (
      !workflowState ||
      !healthyId ||
      !diseaseId ||
      healthyNetworkQuery.data?.status !== 'completed' ||
      diseaseNetworkQuery.data?.status !== 'completed' ||
      workflowState.driftResultId ||
      startedStages.current.has(`drift:${healthyId}:${diseaseId}`)
    ) return
    startedStages.current.add(`drift:${healthyId}:${diseaseId}`)
    startDrift.mutate({
      analysisId: workflowState.analysisId,
      healthyNetworkId: healthyId,
      diseaseNetworkId: diseaseId,
      species: workflowState.species,
    })
  }, [
    workflowState,
    healthyNetworkQuery.data?.status,
    diseaseNetworkQuery.data?.status,
    datasets,
    startDrift,
  ])

  useEffect(() => {
    const driftId = workflowState?.driftResultId
    if (
      !workflowState ||
      !driftId ||
      driftStatusQuery.data?.status !== 'completed' ||
      workflowState.driftPathwayId ||
      startedStages.current.has(`drift-pathway:${driftId}`)
    ) return
    startedStages.current.add(`drift-pathway:${driftId}`)
    startDriftPathway.mutate({
      analysisId: workflowState.analysisId,
      driftResultId: driftId,
      species: workflowState.species,
    })
  }, [workflowState, driftStatusQuery.data?.status, datasets, startDriftPathway])

  const handlePreviewDataset = async (datasetId: string) => {
    setPreviewDatasetId(datasetId)
    setPreviewLoading(true)
    try {
      const response = await fetch(`/data/pathdrift/raw/${datasetId}.csv`)
      if (!response.ok) {
        setPreviewRows([])
        return
      }
      const text = await response.text()
      const rows = text
        .split(/\r?\n/)
        .map((line) => line.split(',').slice(0, 8))
        .filter((row) => row.some((cell) => cell.trim().length > 0))
        .slice(0, 8)
      setPreviewRows(rows)
    } catch {
      setPreviewRows([])
    } finally {
      setPreviewLoading(false)
    }
  }

  const onExprDrop = useCallback((accepted: File[]) => setExprFile(accepted[0] ?? null), [])
  const { getRootProps: getExprProps, getInputProps: getExprInput, isDragActive: exprDrag } = useDropzone({
    onDrop: onExprDrop, multiple: false,
    accept: { 'text/csv': ['.csv'], 'text/tab-separated-values': ['.tsv', '.txt'], 'application/gzip': ['.gz'] },
  })

  return (
    <Box>
      <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 3 }}>
        <Typography variant="h4" fontWeight={700}>Datasets</Typography>
        <Button variant="contained" startIcon={<CloudUpload />} onClick={() => setUploadOpen(true)}>
          Upload Dataset
        </Button>
      </Box>

      {!currentProjectId && (
        <Alert severity="info" sx={{ mb: 2 }}>
          No project is selected yet, but downloaded public datasets are still visible here for review.
        </Alert>
      )}

      {currentProjectId && (
        <Paper variant="outlined" sx={{ p: 2, mb: 2 }}>
          <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2} alignItems={{ sm: 'center' }}>
            <TextField
              select
              size="small"
              label="Analysis"
              value={currentAnalysisId ?? ''}
              onChange={(event) => setCurrentAnalysis(event.target.value || null)}
              sx={{ minWidth: 280 }}
            >
              {projectAnalyses.map((analysis) => (
                <MenuItem key={analysis.id} value={analysis.id}>{analysis.name}</MenuItem>
              ))}
            </TextField>
            <Typography variant="body2" color="text.secondary">
              The automated workflow uses this analysis and the dataset you start from.
              If no analysis is selected, one is created for you.
            </Typography>
          </Stack>
        </Paper>
      )}

      {isLoading && <LinearProgress />}

      {workflowState && (
        <Paper sx={{ p: 2.5, mb: 3 }} variant="outlined">
          <Typography variant="h6" fontWeight={700} gutterBottom>Automated workflow status</Typography>
          <Typography variant="body2" color="text.secondary" gutterBottom>
            Analysis: <strong>{workflowState.analysisId}</strong> · Dataset: <strong>{workflowState.datasetId}</strong>
          </Typography>
          <Grid container spacing={2}>
            {workflowState.preprocessingJobId && <Grid item xs={12} sm={6} md={4}>
              <Paper variant="outlined" sx={{ p: 2 }}>
                <Typography variant="subtitle2" gutterBottom>Preprocessing job</Typography>
                <Typography variant="body2">Job ID: {workflowState.preprocessingJobId ?? '—'}</Typography>
                <Typography variant="body2">Status: {preprocessingStatusQuery.data?.status ?? 'pending'}</Typography>
              </Paper>
            </Grid>}
            <Grid item xs={12} sm={6} md={4}>
              <Paper variant="outlined" sx={{ p: 2 }}>
                <Typography variant="subtitle2" gutterBottom>DEG result</Typography>
                <Typography variant="body2">Result ID: {workflowState.degResultId ?? 'queued after preprocessing'}</Typography>
                <Typography variant="body2">Status: {degStatusQuery.data?.status ?? 'pending'}</Typography>
              </Paper>
            </Grid>
            <Grid item xs={12} sm={6} md={4}>
              <Paper variant="outlined" sx={{ p: 2 }}>
                <Typography variant="subtitle2" gutterBottom>DEG pathway enrichment</Typography>
                <Typography variant="body2">Status: {degPathwayQuery.data?.status ?? (workflowState.degPathwayId ? 'queued' : 'waiting for DEG')}</Typography>
              </Paper>
            </Grid>
            {!workflowState.networkSkippedReason && (
              <>
                <Grid item xs={12} sm={6} md={4}>
                  <Paper variant="outlined" sx={{ p: 2 }}>
                    <Typography variant="subtitle2" gutterBottom>Healthy network</Typography>
                    <Typography variant="body2">Status: {healthyNetworkQuery.data?.status ?? (workflowState.healthyNetworkId ? 'queued' : 'waiting for DEG')}</Typography>
                  </Paper>
                </Grid>
                <Grid item xs={12} sm={6} md={4}>
                  <Paper variant="outlined" sx={{ p: 2 }}>
                    <Typography variant="subtitle2" gutterBottom>Cancer network</Typography>
                    <Typography variant="body2">Status: {diseaseNetworkQuery.data?.status ?? (workflowState.diseaseNetworkId ? 'queued' : 'waiting for healthy network')}</Typography>
                  </Paper>
                </Grid>
                <Grid item xs={12} sm={6} md={4}>
                  <Paper variant="outlined" sx={{ p: 2 }}>
                    <Typography variant="subtitle2" gutterBottom>Network drift</Typography>
                    <Typography variant="body2">Status: {driftStatusQuery.data?.status ?? (workflowState.driftResultId ? 'queued' : 'waiting for networks')}</Typography>
                  </Paper>
                </Grid>
                {workflowState.driftPathwayId && (
                  <Grid item xs={12} sm={6} md={4}>
                    <Paper variant="outlined" sx={{ p: 2 }}>
                      <Typography variant="subtitle2" gutterBottom>Drift pathway enrichment</Typography>
                      <Typography variant="body2">Status: {driftPathwayQuery.data?.status ?? 'queued'}</Typography>
                    </Paper>
                  </Grid>
                )}
              </>
            )}
          </Grid>
          {workflowState.networkSkippedReason && <Alert severity="info" sx={{ mt: 2 }}>{workflowState.networkSkippedReason} DEG and DEG-based enrichment are still run.</Alert>}
          {workflowState.networkError && <Alert severity="error" sx={{ mt: 2 }}>{workflowState.networkError}</Alert>}
          {workflowState.degPathwayError && <Alert severity="error" sx={{ mt: 2 }}>DEG pathway enrichment: {workflowState.degPathwayError}</Alert>}
          {workflowState.driftError && <Alert severity="error" sx={{ mt: 2 }}>Network drift: {workflowState.driftError}</Alert>}
          {workflowState.driftPathwayError && <Alert severity="error" sx={{ mt: 2 }}>Drift pathway enrichment: {workflowState.driftPathwayError}</Alert>}
          {!workflowState.networkSkippedReason && (
            <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 1.5 }}>
              Cross-species comparison requires completed workflows for both human and mouse cohorts; this run handles the selected dataset only.
            </Typography>
          )}
        </Paper>
      )}

      <Box sx={{ mb: 3 }}>
        <Typography variant="h5" fontWeight={700} gutterBottom>Acquired public datasets</Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          Curated source datasets recorded in the acquisition manifest. Preview expression values and sample metadata without importing a second copy into a project.
        </Typography>
        {manifestDatasetsLoading && <LinearProgress sx={{ mb: 2 }} />}
        {manifestDatasetsError && <Alert severity="error" sx={{ mb: 2 }}>Could not load the acquired dataset manifest.</Alert>}
        {!manifestDatasetsLoading && !manifestDatasetsError && manifestDatasets.length === 0 && (
          <Alert severity="info">No acquired public datasets are registered in the manifest.</Alert>
        )}
        <Grid container spacing={2}>
          {manifestDatasets.map((dataset) => (
            <Grid item xs={12} lg={6} key={dataset.id}>
              <Card variant="outlined" sx={{ height: '100%' }}>
                <CardContent>
                  <Stack direction={{ xs: 'column', sm: 'row' }} justifyContent="space-between" spacing={1}>
                    <Box>
                      <Typography variant="h6" fontWeight={700}>{dataset.name}</Typography>
                      <Typography variant="body2" color="text.secondary">
                        {dataset.repository} · {dataset.accession} · {dataset.species}
                      </Typography>
                    </Box>
                    <Chip size="small" color={dataset.status === 'ready' ? 'success' : 'default'} label={dataset.status} />
                  </Stack>
                  <Stack direction="row" flexWrap="wrap" gap={1} sx={{ mt: 2 }}>
                    <Chip size="small" label={dataset.tissue} />
                    <Chip size="small" label={dataset.condition} />
                    <Chip size="small" label={`${(dataset.n_genes ?? dataset.gene_count ?? 0).toLocaleString()} genes`} />
                    <Chip size="small" label={`${(dataset.n_samples ?? dataset.sample_count).toLocaleString()} analysis samples`} />
                    {dataset.raw_sample_count != null && dataset.raw_sample_count !== dataset.sample_count && (
                      <Chip size="small" variant="outlined" label={`${dataset.raw_sample_count.toLocaleString()} raw aliquots`} />
                    )}
                    <Chip size="small" variant="outlined" label={`${dataset.n_healthy ?? 0} healthy / ${dataset.n_cancer ?? 0} cancer`} />
                    {dataset.download_date && <Chip size="small" variant="outlined" label={`Downloaded ${dataset.download_date}`} />}
                  </Stack>
                  <Typography variant="body2" color="text.secondary" sx={{ mt: 1.5 }}>
                    {dataset.platform || dataset.source_data_type || 'Platform not recorded'}
                    {dataset.genome_build ? ` · ${dataset.genome_build}` : ''}
                    {dataset.normalization_method ? ` · ${dataset.normalization_method}` : ''}
                  </Typography>
                  {dataset.analysis_note && (
                    <Alert severity="info" sx={{ mt: 1.5 }}>{dataset.analysis_note}</Alert>
                  )}
                  <Stack direction="row" spacing={1} sx={{ mt: 1.5 }}>
                    <Button size="small" variant="outlined" startIcon={<Visibility />} onClick={() => {
                      setManifestPreviewOffset(0)
                      setManifestPreviewDataset(dataset)
                    }}>
                      View dataset
                    </Button>
                    {dataset.source_url && (
                      <Button size="small" component="a" href={dataset.source_url} target="_blank" rel="noreferrer" endIcon={<OpenInNew />}>
                        Source record
                      </Button>
                    )}
                  </Stack>
                </CardContent>
              </Card>
            </Grid>
          ))}
        </Grid>
      </Box>

      <Typography variant="h5" fontWeight={700} gutterBottom>Project datasets</Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        Uploaded or imported into the selected project. These are the records used by project analysis workflows.
      </Typography>
      {mergedDatasets.length === 0 && !isLoading ? (
        <Paper sx={{ p: 4, textAlign: 'center' }} variant="outlined">
          <Typography color="text.secondary">
            No project datasets yet. Upload an expression matrix or import a public cohort from Data Acquisition.
          </Typography>
        </Paper>
      ) : (
        <TableContainer component={Paper} variant="outlined">
          <Table size="small">
            <TableHead>
              <TableRow sx={{ '& th': { fontWeight: 600 } }}>
                <TableCell>Name</TableCell>
                <TableCell>Dataset ID</TableCell>
                <TableCell>Species</TableCell>
                <TableCell>Type</TableCell>
                <TableCell>Tissue</TableCell>
                <TableCell>Accession</TableCell>
                <TableCell>Genes</TableCell>
                <TableCell>Samples</TableCell>
                <TableCell>Healthy</TableCell>
                <TableCell>Cancer</TableCell>
                <TableCell>Status</TableCell>
                <TableCell>Actions</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {mergedDatasets.map((ds) => (
                <TableRow key={ds.id} hover>
                  <TableCell>
                    <Typography variant="body2" fontWeight={500}>{ds.name}</Typography>
                    <Typography variant="caption" color="text.secondary" display="block">{ds.source || 'Data acquisition'}</Typography>
                  </TableCell>
                  <TableCell>
                    <Typography variant="body2" fontWeight={500}>{ds.id}</Typography>
                  </TableCell>
                  <TableCell>
                    <Chip size="small" label={String(ds.species).toLowerCase() === 'human' ? '🧬 Human' : String(ds.species).toLowerCase() === 'mouse' ? '🐭 Mouse' : String(ds.species || 'Unknown')} />
                  </TableCell>
                  <TableCell>{displayDataType(ds.data_type)}</TableCell>
                  <TableCell>{ds.tissue || '—'}</TableCell>
                  <TableCell>{ds.accession || '—'}</TableCell>
                  <TableCell>{ds.n_genes?.toLocaleString() ?? '—'}</TableCell>
                  <TableCell>{ds.n_samples?.toLocaleString() ?? '—'}</TableCell>
                  <TableCell>{ds.n_healthy ?? '—'}</TableCell>
                  <TableCell>{ds.n_cancer ?? '—'}</TableCell>
                  <TableCell><StatusChip status={String(ds.is_validated)} /></TableCell>
                  <TableCell>
                    <Tooltip title="Preview rows">
                      <IconButton size="small" onClick={() => handlePreviewDataset(ds.id)}>
                        <Visibility fontSize="small" />
                      </IconButton>
                    </Tooltip>
                    <Tooltip title={(ds.n_healthy ?? 0) < 2 || (ds.n_cancer ?? 0) < 2
                      ? 'DEG needs at least two real healthy and two real cancer samples.'
                      : 'Automatically run preprocessing, DEG, pathways, and eligible network drift analyses.'}>
                      <span>
                        <Button
                          size="small"
                          variant="contained"
                          color="secondary"
                          disabled={
                            workflowInProgress ||
                            !currentProjectId ||
                            !isWorkflowEligibleDataset(ds.id) ||
                            (ds.n_healthy ?? 0) < 2 ||
                            (ds.n_cancer ?? 0) < 2
                          }
                          onClick={() => workflowMutation.mutate(normalizeDatasetId(ds))}
                          sx={{ ml: 0.5, minWidth: 0, px: 1.5 }}
                        >
                          {workflowInProgress ? 'Workflow running' : 'Analyze dataset'}
                        </Button>
                      </span>
                    </Tooltip>
                    <Tooltip title="Validate">
                      <IconButton size="small" onClick={() => validateMutation.mutate(ds.id)}>
                        <CheckCircle fontSize="small" />
                      </IconButton>
                    </Tooltip>
                    <Tooltip title="Delete">
                      <IconButton size="small" color="error" onClick={() => deleteMutation.mutate(ds.id)}>
                        <Delete fontSize="small" />
                      </IconButton>
                    </Tooltip>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      )}

      {manifestPreviewDataset && (
        <Dialog open onClose={() => setManifestPreviewDataset(null)} maxWidth="xl" fullWidth>
          <DialogTitle>{manifestPreviewDataset.name}</DialogTitle>
          <DialogContent dividers>
            {manifestPreviewQuery.isLoading && <LinearProgress sx={{ mb: 2 }} />}
            {(manifestPreviewQuery.isError || (manifestPreviewQuery.data && !hasManifestPreview)) && (
              <Alert severity="error" sx={{ mb: 2 }}>
                {manifestPreviewQuery.error instanceof Error
                  ? `Could not read the dataset preview: ${manifestPreviewQuery.error.message}`
                  : 'This backend did not return expression and sample-metadata preview data. Restart the backend to load the updated dataset preview route.'}
              </Alert>
            )}
            {hasManifestPreview && manifestPreviewQuery.data && (
              <Stack spacing={2}>
                <Grid container spacing={1}>
                  <Grid item xs={12} sm={6} md={3}><Typography variant="caption" color="text.secondary">Source</Typography><Typography variant="body2">{manifestPreviewDataset.repository} · {manifestPreviewDataset.accession}</Typography></Grid>
                  <Grid item xs={12} sm={6} md={3}><Typography variant="caption" color="text.secondary">Data</Typography><Typography variant="body2">{manifestPreviewDataset.source_data_type || manifestPreviewDataset.data_type}</Typography></Grid>
                  <Grid item xs={12} sm={6} md={3}><Typography variant="caption" color="text.secondary">Expression file</Typography><Typography variant="body2" sx={{ overflowWrap: 'anywhere' }}>{manifestPreviewDataset.raw_expression_path}</Typography></Grid>
                  <Grid item xs={12} sm={6} md={3}><Typography variant="caption" color="text.secondary">Sample metadata file</Typography><Typography variant="body2" sx={{ overflowWrap: 'anywhere' }}>{manifestPreviewDataset.metadata_path || 'Not recorded'}</Typography></Grid>
                </Grid>
                <Box>
                  <Typography variant="subtitle1" fontWeight={700} gutterBottom>Expression matrix preview</Typography>
                  {manifestPreviewQuery.data.expression.rows.length ? (
                    <TableContainer component={Paper} variant="outlined" sx={{ maxHeight: 520 }}>
                      <Table size="small" stickyHeader sx={{ minWidth: 'max-content' }}>
                        <TableHead><TableRow>{manifestPreviewQuery.data.expression.columns.map((column) => <TableCell key={column} sx={{ fontWeight: 700, whiteSpace: 'nowrap' }}>{column}</TableCell>)}</TableRow></TableHead>
                        <TableBody>
                          {manifestPreviewQuery.data.expression.rows.map((row, rowIndex) => (
                            <TableRow hover key={`${manifestPreviewDataset.id}-expression-${rowIndex}`}>
                              {row.map((value, columnIndex) => <TableCell key={`${rowIndex}-${columnIndex}`} sx={{ whiteSpace: 'nowrap' }}>{value == null ? '—' : String(value)}</TableCell>)}
                            </TableRow>
                          ))}
                        </TableBody>
                      </Table>
                    </TableContainer>
                  ) : <Alert severity="info">No expression rows are available to preview.</Alert>}
                  <TablePagination
                    component="div"
                    count={manifestPreviewQuery.data.expression.total_rows}
                    page={Math.floor(manifestPreviewOffset / manifestPreviewLimit)}
                    onPageChange={(_, page) => setManifestPreviewOffset(page * manifestPreviewLimit)}
                    rowsPerPage={manifestPreviewLimit}
                    onRowsPerPageChange={(event) => {
                      setManifestPreviewLimit(Number(event.target.value))
                      setManifestPreviewOffset(0)
                    }}
                    rowsPerPageOptions={[50, 100, 250]}
                  />
                  <Typography variant="caption" color="text.secondary">
                    Browse the complete matrix by gene; all sample columns are included. Each page loads only the selected rows.
                  </Typography>
                </Box>
                <Box>
                  <Typography variant="subtitle1" fontWeight={700} gutterBottom>Sample metadata preview</Typography>
                  {manifestPreviewQuery.data.sample_metadata.columns.length ? (
                    <TableContainer component={Paper} variant="outlined" sx={{ maxHeight: 300 }}>
                      <Table size="small" stickyHeader>
                        <TableHead><TableRow>{manifestPreviewQuery.data.sample_metadata.columns.map((column) => <TableCell key={column} sx={{ fontWeight: 700, whiteSpace: 'nowrap' }}>{column}</TableCell>)}</TableRow></TableHead>
                        <TableBody>
                          {manifestPreviewQuery.data.sample_metadata.rows.map((row, rowIndex) => (
                            <TableRow hover key={`${manifestPreviewDataset.id}-metadata-${rowIndex}`}>
                              {row.map((value, columnIndex) => <TableCell key={`${rowIndex}-${columnIndex}`} sx={{ whiteSpace: 'nowrap' }}>{value == null ? '—' : String(value)}</TableCell>)}
                            </TableRow>
                          ))}
                        </TableBody>
                      </Table>
                    </TableContainer>
                  ) : <Alert severity="info">Sample metadata is not recorded for this dataset.</Alert>}
                  <Typography variant="caption" color="text.secondary">
                    Showing all {manifestPreviewQuery.data.sample_metadata.rows.length} sample metadata records.
                  </Typography>
                </Box>
              </Stack>
            )}
          </DialogContent>
          <DialogActions><Button onClick={() => setManifestPreviewDataset(null)}>Close</Button></DialogActions>
        </Dialog>
      )}

      {/* Dataset preview dialog */}
      {previewDatasetId && (
        <Dialog open onClose={() => setPreviewDatasetId(null)} maxWidth="md" fullWidth>
          <DialogTitle>Dataset preview: {previewDatasetId}</DialogTitle>
          <DialogContent dividers>
            {previewLoading ? (
              <Box sx={{ display: 'flex', justifyContent: 'center', py: 3 }}>
                <CircularProgress size={24} />
              </Box>
            ) : previewRows.length > 0 ? (
              <Table size="small">
                <TableBody>
                  {previewRows.map((row, rowIndex) => (
                    <TableRow key={`${previewDatasetId}-${rowIndex}`}>
                      {row.map((cell, cellIndex) => (
                        <TableCell key={`${previewDatasetId}-${rowIndex}-${cellIndex}`} sx={{ fontSize: 12 }}>
                          {cell}
                        </TableCell>
                      ))}
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            ) : (
              <Alert severity="info">No preview rows were available for this dataset yet.</Alert>
            )}
          </DialogContent>
          <DialogActions>
            <Button onClick={() => setPreviewDatasetId(null)}>Close</Button>
          </DialogActions>
        </Dialog>
      )}

      {/* Validation result dialog */}
      {validationResult && (
        <Dialog open onClose={() => setValidationResult(null)} maxWidth="sm" fullWidth>
          <DialogTitle>Validation Result</DialogTitle>
          <DialogContent>
            <Alert severity={(validationResult.is_valid as boolean) ? 'success' : 'error'} sx={{ mb: 2 }}>
              {(validationResult.is_valid as boolean) ? 'Dataset passed validation' : 'Dataset has validation errors'}
            </Alert>
            {(validationResult.errors as string[])?.length > 0 && (
              <Box mb={2}>
                <Typography variant="subtitle2" gutterBottom>Errors:</Typography>
                {(validationResult.errors as string[]).map((e, i) => (
                  <Alert key={i} severity="error" sx={{ mb: 0.5 }}>{e}</Alert>
                ))}
              </Box>
            )}
            {(validationResult.warnings as string[])?.length > 0 && (
              <Box>
                <Typography variant="subtitle2" gutterBottom>Warnings:</Typography>
                {(validationResult.warnings as string[]).map((w, i) => (
                  <Alert key={i} severity="warning" sx={{ mb: 0.5 }}>{w}</Alert>
                ))}
              </Box>
            )}
          </DialogContent>
          <DialogActions>
            <Button onClick={() => setValidationResult(null)}>Close</Button>
          </DialogActions>
        </Dialog>
      )}

      {/* Upload dialog */}
      <Dialog open={uploadOpen} onClose={() => setUploadOpen(false)} maxWidth="md" fullWidth>
        <DialogTitle>Upload Expression Dataset</DialogTitle>
        <DialogContent>
          <Grid container spacing={2} sx={{ mt: 0.5 }}>
            <Grid item xs={12} sm={6}>
              <TextField
                label="Dataset Name" fullWidth required
                value={form.name} onChange={e => setForm(f => ({ ...f, name: e.target.value }))}
              />
            </Grid>
            <Grid item xs={12} sm={6}>
              <TextField
                select label="Species" fullWidth required
                value={form.species} onChange={e => setForm(f => ({ ...f, species: e.target.value }))}
              >
                {SPECIES_OPTIONS.map(o => <MenuItem key={o.value} value={o.value}>{o.label}</MenuItem>)}
              </TextField>
            </Grid>
            <Grid item xs={12} sm={6}>
              <TextField
                select label="Data Type" fullWidth required
                value={form.data_type} onChange={e => setForm(f => ({ ...f, data_type: e.target.value }))}
              >
                {DATA_TYPE_OPTIONS.map(o => <MenuItem key={o.value} value={o.value}>{o.label}</MenuItem>)}
              </TextField>
            </Grid>
            <Grid item xs={12} sm={6}>
              <TextField label="Tissue" fullWidth value={form.tissue}
                onChange={e => setForm(f => ({ ...f, tissue: e.target.value }))} />
            </Grid>
            <Grid item xs={12} sm={6}>
              <TextField label="Source (TCGA, GEO, GTEx...)" fullWidth value={form.source}
                onChange={e => setForm(f => ({ ...f, source: e.target.value }))} />
            </Grid>
            <Grid item xs={12} sm={6}>
              <TextField label="Accession (e.g. GSE12345)" fullWidth value={form.accession}
                onChange={e => setForm(f => ({ ...f, accession: e.target.value }))} />
            </Grid>
            <Grid item xs={12}>
              <Typography variant="subtitle2" gutterBottom>Expression Matrix *</Typography>
              <Box
                {...getExprProps()}
                sx={{
                  border: '2px dashed', borderColor: exprDrag ? 'primary.main' : 'divider',
                  borderRadius: 2, p: 3, textAlign: 'center', cursor: 'pointer',
                  bgcolor: exprDrag ? 'action.hover' : 'background.default',
                }}
              >
                <input {...getExprInput()} />
                {exprFile ? (
                  <Typography variant="body2" color="success.main" fontWeight={500}>
                    ✓ {exprFile.name} ({(exprFile.size / 1024 / 1024).toFixed(1)} MB)
                  </Typography>
                ) : (
                  <Typography variant="body2" color="text.secondary">
                    Drop expression matrix (CSV/TSV/TXT/GZ) or click to browse.<br />
                    Rows = genes, columns = samples.
                  </Typography>
                )}
              </Box>
            </Grid>
            <Grid item xs={12}>
              <Typography variant="subtitle2" gutterBottom>Sample Metadata (optional but strongly recommended)</Typography>
              <input
                type="file"
                accept=".csv,.tsv,.txt"
                onChange={e => setMetaFile(e.target.files?.[0] ?? null)}
              />
              <Typography variant="caption" color="text.secondary" display="block" mt={0.5}>
                Must include columns: sample_id, disease_state (healthy/cancer/normal/tumor).
                Optional: stage, batch, age, sex.
              </Typography>
            </Grid>
          </Grid>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setUploadOpen(false)}>Cancel</Button>
          <Button
            variant="contained"
            onClick={() => uploadMutation.mutate()}
            disabled={uploadMutation.isPending || !exprFile || !form.name}
            startIcon={uploadMutation.isPending ? <CircularProgress size={16} /> : undefined}
          >
            Upload
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  )
}
