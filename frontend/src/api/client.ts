/**
 * PathDrift API Client
 * All backend communication goes through this module.
 * Uses axios with JWT authentication.
 */
import axios, { AxiosInstance, AxiosError } from 'axios'

const BASE_URL = import.meta.env.VITE_API_BASE_URL || ''

export const apiClient: AxiosInstance = axios.create({
  baseURL: `${BASE_URL}/api/v1`,
  headers: { 'Content-Type': 'application/json' },
  timeout: 30_000,
})

// Attach JWT token to every request
apiClient.interceptors.request.use((config) => {
  const token = localStorage.getItem('pathdrift_token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// Handle 401 by clearing token
apiClient.interceptors.response.use(
  (res) => res,
  (error: AxiosError) => {
    if (error.response?.status === 401) {
      localStorage.removeItem('pathdrift_token')
      window.location.href = '/login'
    }
    return Promise.reject(error)
  }
)

// ── Auth ──────────────────────────────────────────────────────────────────────

export const authApi = {
  login: (username: string, password: string) =>
    apiClient.post<{ access_token: string; token_type: string }>('/auth/login', { username, password }),
  register: (data: { email: string; username: string; password: string; full_name?: string; institution?: string }) =>
    apiClient.post('/auth/register', data),
  getMe: () => apiClient.get('/users/me'),
}

// ── Projects ──────────────────────────────────────────────────────────────────

export const projectApi = {
  list: () => apiClient.get('/projects/'),
  create: (data: { name: string; description?: string; research_question?: string; is_public?: boolean }) =>
    apiClient.post('/projects/', data),
}

export interface DashboardSummary {
  human_samples: number
  mouse_samples: number
  orthologs: number
  human_degs: number | null
  mouse_degs: number | null
  drifted_genes: number | null
  conservation_score: number | null
  top_pathways: Array<{ term: string; adjusted_pvalue: number | null }>
  cross_species_analysis_id: string | null
}

export const dashboardApi = {
  getSummary: (projectId: string) =>
    apiClient.get<DashboardSummary>(`/projects/${projectId}/dashboard-summary`),
}

export const analysisApi = {
  list: () => apiClient.get('/analyses/'),
  listForProject: (projectId: string) => apiClient.get(`/analyses/project/${projectId}`),
  create: (data: { project_id: string; name: string; description?: string; random_seed?: number }) =>
    apiClient.post('/analyses/', data),
  get: (id: string) => apiClient.get(`/analyses/${id}`),
}

// ── Datasets ──────────────────────────────────────────────────────────────────

export const datasetApi = {
  upload: (formData: FormData) =>
    apiClient.post('/datasets/upload', formData, { headers: { 'Content-Type': 'multipart/form-data' } }),
  list: (projectId: string) => apiClient.get(`/datasets/project/${projectId}`),
  get: (id: string) => apiClient.get(`/datasets/${id}`),
  validate: (id: string) => apiClient.post(`/datasets/${id}/validate`),
  getSamples: (id: string) => apiClient.get(`/datasets/${id}/samples`),
  delete: (id: string) => apiClient.delete(`/datasets/${id}`),
}

export interface DatasetQuality {
  dataset_id: string
  before_sample_count: number
  after_sample_count: number | null
  preprocessing_status: string | null
  pca_source: 'raw' | 'preprocessed'
  pca_gene_count: number
  pca_points: Array<{ sample_id: string; group: string; pc1: number; pc2: number }>
  explained_variance_ratio: number[]
  pca_message: string | null
  outlier_samples: string[]
}

export const dataQualityApi = {
  get: (datasetId: string) =>
    apiClient.get<DatasetQuality>(`/datasets/${datasetId}/quality`),
}

export const runQcApi = {
  acquisitionDatasets: () => apiClient.get<AcquisitionQCDataset[]>('/runs/acquisition-qc'),
  acquisitionDataset: (accession: string) =>
    apiClient.get<AcquisitionQCDatasetReport>(`/runs/acquisition-qc/${encodeURIComponent(accession)}`),
  acquisitionArtifact: (accession: string, artifactName: string) =>
    apiClient.get<Blob>(
      `/runs/acquisition-qc/${encodeURIComponent(accession)}/artifacts/${encodeURIComponent(artifactName)}`,
      { responseType: 'blob' },
    ),
  list: (projectId: string) => apiClient.get('/runs/project/' + projectId),
  datasets: (runId: string) => apiClient.get(`/runs/${runId}/datasets`),
  summary: (runId: string) => apiClient.get(`/runs/${runId}/qc`),
  pca: (runId: string) => apiClient.get(`/runs/${runId}/qc/pca`),
  correlation: (runId: string) => apiClient.get(`/runs/${runId}/qc/correlation`),
  clustering: (runId: string) => apiClient.get(`/runs/${runId}/qc/clustering`),
}

// ── Run-scoped analysis results ──────────────────────────────────────────────

export const phase3Api = {
  listRuns: (projectId: string) => apiClient.get(`/runs/project/${projectId}`),
  savedRuns: () => apiClient.get('/runs/saved'),
  datasets: (runId: string) => apiClient.get(`/runs/${runId}/datasets`),
  summary: (runId: string) => apiClient.get(`/runs/${runId}/analysis-summary`),
  deg: (runId: string, params: { species?: string; comparison?: string; limit?: number; offset?: number; significant?: boolean }) =>
    apiClient.get(`/runs/${runId}/deg`, { params }),
  degTable: (runId: string, species: string, tableName: string, params: { comparison?: string; limit?: number; offset?: number }) =>
    apiClient.get(`/runs/${runId}/deg/${species}/tables/${encodeURIComponent(tableName)}`, { params }),
  degArtifacts: (runId: string, species: string, comparison?: string) =>
    apiClient.get(`/runs/${runId}/deg/${species}/artifacts`, { params: { comparison } }),
  degArtifact: (runId: string, species: string, artifactName: string, comparison?: string) =>
    apiClient.get(`/runs/${runId}/deg/${species}/artifacts/${encodeURIComponent(artifactName)}`, {
      params: { comparison },
      responseType: 'blob',
    }),
  integrated: (runId: string, params: { species: string; limit?: number; offset?: number }) =>
    apiClient.get(`/runs/${runId}/integrated`, { params }),
  artifacts: (runId: string) => apiClient.get(`/runs/${runId}/artifacts`),
  artifact: (runId: string, artifactPath: string) =>
    apiClient.get(`/runs/${runId}/artifacts/${artifactPath.split('/').map(encodeURIComponent).join('/')}`, { responseType: 'blob' }),
  downloadAllArtifacts: (runId: string) =>
    apiClient.get<Blob>(`/runs/${runId}/artifacts/download-all`, { responseType: 'blob' }),
  networks: (runId: string) => apiClient.get(`/runs/${runId}/networks`),
  network: (runId: string, networkId: string) => apiClient.get(`/runs/${runId}/networks/${networkId}`),
  nodes: (runId: string, networkId: string, limit = 100, offset = 0) =>
    apiClient.get(`/runs/${runId}/networks/${networkId}/nodes`, { params: { limit, offset } }),
  edges: (runId: string, networkId: string, limit = 200, offset = 0) =>
    apiClient.get(`/runs/${runId}/networks/${networkId}/edges`, { params: { limit, offset } }),
  modules: (runId: string, params: { species?: string; limit?: number; offset?: number } = {}) =>
    apiClient.get(`/runs/${runId}/modules`, { params }),
  module: (runId: string, moduleId: string) =>
    apiClient.get(`/runs/${runId}/modules/${moduleId}`),
  moduleGenes: (runId: string, moduleId: string, limit = 100, offset = 0) =>
    apiClient.get(`/runs/${runId}/modules/${moduleId}/genes`, { params: { limit, offset } }),
}

export interface AcquisitionQCDataset {
  accession: string
  name: string
  species: string
  tissue: string
  condition: string
  source_data_type?: string
  gene_identifier_type: string
  status: string
  run_id: string | null
  created_at: string | null
  summary: FilesystemQcDatasetSummary | null
  artifacts: string[]
}

export interface FilesystemQcDatasetSummary {
  initial_samples: number
  retained_samples: number
  initial_genes: number
  retained_genes: number
  excluded_samples: string[]
  excluded_genes: number
  normalization_method: string
  normalization_data_type?: string
  gene_identifier_type?: string
  invalid_gene_ids?: number
  non_numeric_cells?: number
  missing_cells_imputed?: number
  outliers: Array<{ sample_id: string; decision: string; metric: number; threshold: number }>
}

export interface AcquisitionQCSampleRow {
  [key: string]: string | number | boolean | null
}

export interface AcquisitionQCDatasetReport {
  accession: string
  run_id: string
  created_at: string
  summary: FilesystemQcDatasetSummary
  sample_qc: AcquisitionQCSampleRow[]
  pca_coordinates: Array<{ sample_id: string; cluster?: number | null; is_outlier?: boolean; [key: string]: string | number | boolean | null | undefined }>
  correlation: { samples: string[]; values: Array<Array<number | null>> }
  clustering: Array<{ sample_id: string; cluster: number }>
  artifacts: string[]
}

export const dataAcquisitionApi = {
  search: (params: { disease?: string; species?: string }) =>
    apiClient.get('/data-acquisition/search', { params }),
  select: (payload: { disease: string; species: string[]; selected_ids: string[]; analysis_type: string }) =>
    apiClient.post('/data-acquisition/select', payload),
  download: (payload: { project_id: string; selected_ids: string[]; disease: string }) =>
    apiClient.post('/data-acquisition/download', payload, { timeout: 600_000 }),
  getJob: (jobId: string) => apiClient.get(`/data-acquisition/jobs/${jobId}`),
  listDatasets: () => apiClient.get('/data-acquisition/datasets'),
  listManifestDatasets: () => apiClient.get<ManifestDataset[]>('/data-acquisition/datasets'),
  previewManifestDataset: (datasetId: string, offset = 0, limit = 100) =>
    apiClient.get<ManifestDataset & ManifestDatasetPreview>(
      `/data-acquisition/datasets/${encodeURIComponent(datasetId)}`,
      { params: { offset, limit } },
    ),
}

export interface ManifestDataset {
  id: string
  dataset_id?: string
  name: string
  repository: string
  accession: string
  species: string
  tissue: string
  condition: string
  disease: string
  data_type: string
  sample_count: number
  raw_sample_count?: number
  n_samples?: number
  n_healthy?: number
  n_cancer?: number
  gene_count?: number
  n_genes?: number
  normalization_method?: string
  platform?: string
  source_data_type?: string
  genome_build?: string
  download_date?: string
  status: string
  is_validated?: boolean
  suitability_score?: number
  source_url?: string
  analysis_note?: string
  raw_expression_path?: string
  metadata_path?: string
  processed_expression_path?: string
  clinical_coverage?: Record<string, number>
  sample_origins?: Record<string, number>
}

export interface ManifestDatasetPreview {
  dataset_id: string
  expression: {
    columns: string[]
    rows: Array<Array<string | number | null>>
    offset: number
    limit: number
    total_rows: number
  }
  sample_metadata: { columns: string[]; rows: Array<Array<string | number | null>> }
}

// ── Import ────────────────────────────────────────────────────────────────────

export const importApi = {
  fromGEO: (data: { project_id: string; accession: string; species: string; tissue?: string }) =>
    apiClient.post('/import/geo', data),
  fromTCGA: (data: { project_id: string; project_code: string; tissue?: string }) =>
    apiClient.post('/import/tcga', data),
}

// ── Preprocessing ──────────────────────────────────────────────────────────────

export const preprocessingApi = {
  start: (config: object) => apiClient.post('/preprocessing/', config),
  get: (jobId: string) => apiClient.get(`/preprocessing/${jobId}`),
  getLatestForAnalysis: (analysisId: string) => apiClient.get(`/preprocessing/latest/analysis/${analysisId}`),
}

// ── DEG ───────────────────────────────────────────────────────────────────────

export const degApi = {
  listForProject: (projectId: string) => apiClient.get(`/deg/project/${projectId}`),
  run: (config: object) => apiClient.post('/deg/', config),
  get: (id: string) => apiClient.get(`/deg/${id}`),
  getLatestForAnalysis: (analysisId: string) => apiClient.get(`/deg/latest/analysis/${analysisId}`),
  getGenes: (id: string, significantOnly = true, limit = 500) =>
    apiClient.get(`/deg/${id}/genes`, { params: { significant_only: significantOnly, limit } }),
  getLatestGenesForAnalysis: (analysisId: string, significantOnly = true) =>
    apiClient.get(`/deg/latest/analysis/${analysisId}/genes`, { params: { significant_only: significantOnly } }),
}

// ── Networks ──────────────────────────────────────────────────────────────────

export const networkApi = {
  build: (config: object) => apiClient.post('/networks/', config),
  listForProject: (projectId: string) => apiClient.get(`/networks/project/${projectId}`),
  get: (id: string) => apiClient.get(`/networks/${id}`),
  getEdges: (id: string, limit = 2500) => apiClient.get(`/networks/${id}/edges`, { params: { limit } }),
  getNodes: (id: string, limit = 500) => apiClient.get(`/networks/${id}/nodes`, { params: { limit } }),
  getGeneDetails: (id: string, geneId: string) => apiClient.get(`/networks/${id}/genes/${encodeURIComponent(geneId)}`),
  getModules: (id: string) => apiClient.get(`/networks/${id}/modules`),
  enrichModule: (id: string, moduleId: string, geneSet: string) =>
    apiClient.post(`/networks/${id}/modules/${encodeURIComponent(moduleId)}/enrichment`, { gene_set: geneSet }),
}

// ── Drift ─────────────────────────────────────────────────────────────────────

export const driftApi = {
  run: (config: object) => apiClient.post('/drift/', config),
  listForProject: (projectId: string) => apiClient.get(`/drift/project/${projectId}`),
  get: (id: string) => apiClient.get(`/drift/${id}`),
  getSummary: (id: string) => apiClient.get(`/drift/${id}/summary`),
  getNodes: (id: string, limit = 500) => apiClient.get(`/drift/${id}/nodes`, { params: { limit } }),
  getEdges: (id: string, edgeType?: string) =>
    apiClient.get(`/drift/${id}/edges`, { params: { edge_type: edgeType } }),
}

// ── Cross-Species ──────────────────────────────────────────────────────────────

export const crossSpeciesApi = {
  run: (config: object) => apiClient.post('/cross-species/', config),
  listForProject: (projectId: string) => apiClient.get(`/cross-species/project/${projectId}`),
  get: (id: string) => apiClient.get(`/cross-species/${id}`),
  getNetworkAlignment: (id: string) => apiClient.get(`/cross-species/${id}/network-alignment`),
  getGeneNetworkDrift: (id: string, geneId: string, species: string) =>
    apiClient.get(`/cross-species/${id}/genes/${encodeURIComponent(geneId)}/network-drift`, { params: { species } }),
  getGenes: (id: string, classification?: string, limit = 500) =>
    apiClient.get(`/cross-species/${id}/genes`, { params: { classification, limit } }),
}

// ── ML ────────────────────────────────────────────────────────────────────────

export const mlApi = {
  createExperiment: (config: object) => apiClient.post('/ml/experiments', config),
  getExperiment: (id: string) => apiClient.get(`/ml/experiments/${id}`),
  getMetrics: (id: string) => apiClient.get(`/ml/experiments/${id}/metrics`),
  getFeatureImportances: (id: string) => apiClient.get(`/ml/experiments/${id}/feature-importances`),
}

export interface Phase6ConfusionMatrix {
  tn: number
  fp: number
  fn: number
  tp: number
}

export interface Phase6ModelMetrics {
  out_of_fold_metrics: {
    roc_auc: number
    pr_auc: number
    accuracy: number
    balanced_accuracy: number
    sensitivity: number
    specificity: number | null
    precision: number
    f1: number
    brier_score: number
    threshold: number
    confusion_matrix: Phase6ConfusionMatrix
  }
  auc_95_percentile_interval: [number, number] | null
  auc_interval_resampling_unit: string
  fold_metrics: Array<Record<string, number | null | Phase6ConfusionMatrix>>
  calibration_curve: Array<{ mean_predicted_probability: number; fraction_positive: number }>
  n_samples: number
  n_features_before_fold_selection: number
  n_features_selected_per_fold: number
  feature_selection: string
}

export interface Phase6Summary {
  analysis_version: string
  run_id: string
  species: string
  status: string
  scientific_scope: string
  sample_counts: {
    total: number
    class_counts: { healthy: number; cancer: number }
    independent_patient_groups: number | null
  }
  preprocessing: Record<string, unknown>
  data_provenance: {
    accession: string
    expression_path: string
    metadata_path: string
    feature_source: string
    feature_ids: string
  }
  validation_split: { name: string; folds: number; grouped_by_patient: boolean }
  models: Record<string, Phase6ModelMetrics>
  model_comparison: Array<{
    model: string
    metrics: Phase6ModelMetrics['out_of_fold_metrics']
    auc_95_percentile_interval: [number, number] | null
    interval_resampling_unit: string
  }>
  feature_group_comparison: Array<{
    comparison: string
    status: string
    feature_groups: string[]
    reason: string
    model_metrics: Record<string, Partial<Phase6ModelMetrics['out_of_fold_metrics']>> | null
    delta_from_expression_baseline?: { roc_auc: number; pr_auc: number; f1: number } | null
    roc_auc_95_percentile_interval?: [number, number] | null
  }>
  biological_experiments?: {
    status: string
    scientific_scope: string
    baseline: {
      model: string
      metrics: Phase6ModelMetrics['out_of_fold_metrics']
      roc_auc_95_percentile_interval: [number, number] | null
    }
    experiments: Record<string, {
      label: string
      status: string
      reason?: string
      metrics: Phase6ModelMetrics['out_of_fold_metrics'] | null
      delta_from_expression_baseline: { roc_auc: number; pr_auc: number; f1: number } | null
      roc_auc_95_percentile_interval?: [number, number] | null
      folds_completed: number
      folds_total: number
      candidate_features: Array<{
        gene_id: string
        gene_symbol?: string | null
        folds_selected: number
        selection_frequency: number
        mean_absolute_coefficient: number
        selected_as_deg: boolean
        selected_as_hub: boolean
        selected_as_drift: boolean
        mean_drift_score: number | null
      }>
    }>
    fold_evidence: Array<Record<string, string | number | null>>
    limitations: string[]
  }
  feature_groups: Record<string, {
    status: string
    reason?: string
    source?: string | null
    sources?: string[]
    features?: number
    sample_level?: boolean
  }>
  predictive_features: {
    status: string
    ranking_method: string
    feature_count: number
    interpretation: string
  }
  cross_species_analysis: { status: string; interpretation: string; artifact: string }
  independent_validation: {
    status: string
    reason: string
    cross_species_transfer: { status: string; reason: string }
    permutation_test: { status: string; reason: string }
  }
  artifacts: {
    predictions: string
    feature_importance: string
    plots: string[]
  }
  seed: number
  model_configuration: Record<string, Record<string, unknown>>
  software: Record<string, string>
  completed_at: string
}

export interface Phase6MouseAvailabilitySummary {
  analysis_version: string
  run_id: string
  species: 'mouse'
  status: 'NOT_ESTIMABLE' | 'NOT_RUN'
  scientific_scope: string
  reason: string
  cohorts: Array<{
    accession: string
    tissue?: string | null
    total_samples: number
    healthy_samples: number
    cancer_samples: number
    other_label_samples: number
    reference_role?: string | null
  }>
  estimable_cohorts: string[]
  next_step: string
}

export type Phase6SummaryResponse = Phase6Summary | Phase6MouseAvailabilitySummary

export interface Phase6Prediction {
  sample_id: string
  model: string
  fold: number
  true_label: number
  predicted_probability: number
  predicted_label: number
}

export interface Phase6Biomarker {
  gene_id: string
  gene_symbol?: string | null
  mean_model_rank?: number | null
  models_with_gene_selected?: number | null
  mean_selection_frequency_across_models?: number | null
  deg_log2fc?: number | null
  deg_adjusted_p_value?: number | null
  deg_significant?: boolean | null
  deg_direction?: string | null
  network_degree?: number | null
  network_weighted_degree?: number | null
  network_betweenness?: number | null
  network_eigenvector?: number | null
  network_module_id?: string | null
  hub_supported?: boolean | null
  mouse_ensembl_id?: string | null
  mouse_symbol?: string | null
  mouse_expression_status?: string | null
  mouse_cancer_network_status?: string | null
  orthology_type?: string | null
  relationship_cardinality?: string | null
  confidence?: number | null
  drift_score?: number | null
  drift_category?: string | null
  edge_loss_rate?: number | null
  neighbor_similarity?: number | null
  enriched_pathway_names?: string | null
  key_drifted_pathway_names?: string | null
  morphology_status?: string | null
  morphology_evidence?: string | null
  candidate_interpretation?: string | null
}

export interface Phase6FeatureImportance {
  gene_id: string
  model: string
  importance: number
  mean_signed_weight: number | null
  direction: string
  selected_folds: number
  selection_frequency: number
  importance_method: string
}

export const phase6Api = {
  summary: (runId: string, species: 'human' | 'mouse' = 'human') =>
    apiClient.get<Phase6SummaryResponse>(`/runs/${runId}/phase6`, { params: { species } }),
  predictions: (runId: string, limit = 50, offset = 0, species: 'human' | 'mouse' = 'human') =>
    apiClient.get<{ total: number; limit: number; offset: number; items: Phase6Prediction[] }>(
      `/runs/${runId}/phase6/predictions`, { params: { limit, offset, species } },
    ),
  biomarkers: (runId: string, limit = 25, offset = 0, species: 'human' | 'mouse' = 'human') =>
    apiClient.get<{ total: number; limit: number; offset: number; items: Phase6Biomarker[] }>(
      `/runs/${runId}/phase6/biomarkers`, { params: { limit, offset, species } },
    ),
  featureImportance: (runId: string, model: string, limit = 25, offset = 0, species: 'human' | 'mouse' = 'human') =>
    apiClient.get<{ total: number; limit: number; offset: number; items: Phase6FeatureImportance[] }>(
      `/runs/${runId}/phase6/feature-importance`, { params: { model, limit, offset, species } },
    ),
  validation: (runId: string, species: 'human' | 'mouse' = 'human') =>
    apiClient.get<Phase6Summary['independent_validation']>(`/runs/${runId}/phase6/validation`, { params: { species } }),
  artifact: (runId: string, artifactName: string, species: 'human' | 'mouse' = 'human') =>
    apiClient.get<Blob>(`/runs/${runId}/phase6/artifacts/${encodeURIComponent(artifactName)}`, { params: { species }, responseType: 'blob' }),
}

// ── Gene Loss ───────────────────────────────────────────────────────────────

export const geneLossApi = {
  analyze: (payload: object) => apiClient.post('/gene-loss/analyze', payload),
  getEvidence: (comparisonId: string) => apiClient.get(`/gene-loss/evidence/${comparisonId}`),
}

export const ppiApi = {
  search: (payload: { identifier: string; species: 'human' | 'mouse'; confidence: 'high' | 'medium' | 'all' }) =>
    apiClient.post('/ppi/network', payload, { timeout: 30_000 }),
}

// ── Validation ────────────────────────────────────────────────────────────────

export const validationApi = {
  compareModels: (expId: string) => apiClient.get(`/validation/experiments/${expId}/comparison`),
  createRun: (payload: { drift_analysis_id: string; permutations: number; random_seed?: number }) =>
    apiClient.post('/validation/runs', payload),
  getRun: (jobId: string) => apiClient.get(`/validation/runs/${jobId}`),
}

// ── Pathways ──────────────────────────────────────────────────────────────────

export const pathwayApi = {
  run: (config: object) => apiClient.post('/pathways/', config),
  get: (id: string) => apiClient.get(`/pathways/${id}`),
  getTerms: (id: string, significantOnly = true) =>
    apiClient.get(`/pathways/${id}/terms`, { params: { significant_only: significantOnly } }),
}

// ── Jobs ──────────────────────────────────────────────────────────────────────

export const jobsApi = {
  get: (id: string) => apiClient.get(`/jobs/${id}`),
  getForAnalysis: (analysisId: string) => apiClient.get(`/jobs/analysis/${analysisId}`),
  cancel: (id: string) => apiClient.post(`/jobs/${id}/cancel`),
}

// ── Orthology ──────────────────────────────────────────────────────────────────

export const orthologyApi = {
  stats: () => apiClient.get('/orthology/stats'),
  search: (params: { human_symbol?: string; mouse_symbol?: string }) =>
    apiClient.get('/orthology/search', { params }),
}

export const phase4Api = {
  orthology: (runId: string, limit = 100, offset = 0) =>
    apiClient.get(`/runs/${runId}/orthology`, { params: { limit, offset } }),
  orthologySummary: (runId: string) => apiClient.get(`/runs/${runId}/orthology/summary`),
  crossSpeciesSummary: (runId: string) => apiClient.get(`/runs/${runId}/cross-species/summary`),
  crossSpeciesNodes: (runId: string, limit = 100, offset = 0) =>
    apiClient.get(`/runs/${runId}/cross-species/nodes`, { params: { limit, offset } }),
  crossSpeciesEdges: (runId: string, status?: string, limit = 100, offset = 0) =>
    apiClient.get(`/runs/${runId}/cross-species/edges`, { params: { status, limit, offset } }),
  driftSummary: (runId: string) => apiClient.get(`/runs/${runId}/drift/summary`),
  driftGenes: (runId: string, limit = 100, offset = 0) =>
    apiClient.get(`/runs/${runId}/drift/genes`, { params: { limit, offset } }),
  driftEdges: (runId: string, status?: string, limit = 100, offset = 0) =>
    apiClient.get(`/runs/${runId}/drift/edges`, { params: { status, limit, offset } }),
  driftModules: (runId: string, limit = 100, offset = 0) =>
    apiClient.get(`/runs/${runId}/drift/modules`, { params: { limit, offset } }),
}

export const phase5Api = {
  summary: (runId: string) => apiClient.get(`/runs/${runId}/phase5/summary`),
  pathwayGeneSets: (runId: string, species?: string) =>
    apiClient.get(`/runs/${runId}/phase5/pathways/gene-sets`, { params: { species } }),
  geneLossSummary: (runId: string) => apiClient.get(`/runs/${runId}/phase5/gene-loss/summary`),
  geneLossFigure: (runId: string) => apiClient.get<Blob>(`/runs/${runId}/phase5/gene-loss/figure`, { responseType: 'blob' }),
  table: (
    runId: string,
    resultName:
      | 'gene-loss' | 'high-risk' | 'gene-loss-evidence' | 'biomarkers'
      | 'hub-human-cancer' | 'hub-human-healthy' | 'hub-mouse-cancer' | 'hub-mouse-healthy'
      | 'pathway-gene-sets' | 'pathway-enrichment' | 'pathway-comparisons'
      | 'key-drifted-pathways' | 'pathway-gsea' | 'candidate-profiles'
      | 'phenotype-samples' | 'phenotype-variables',
    limit = 50,
    offset = 0,
    filters: { species?: string; gene_set_key?: string; database?: string; significant_only?: boolean } = {},
  ) => apiClient.get(`/runs/${runId}/phase5/${resultName}`, { params: { limit, offset, ...filters } }),
}

// ── Reports ────────────────────────────────────────────────────────────────────

export const reportsApi = {
  generate: (config: object) => apiClient.post('/reports/generate', config),
  downloadUrl: (analysisId: string, format = 'pdf') =>
    `${BASE_URL}/api/v1/reports/${analysisId}/download?format=${format}`,
}

// ── Health ─────────────────────────────────────────────────────────────────────

export const healthApi = {
  check: () => axios.get(`${BASE_URL}/api/health`),
}
